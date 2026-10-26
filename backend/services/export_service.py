"""Analysis-result query and export.

Both formats are built from **the same persisted row** (`videos` table):

* :meth:`ExportService.build_json_result` serializes the stored ``Video``;
* :meth:`ExportService.build_csv` renders one CSV line per stored segment.

Nothing here re-runs analysis, calls the VLM adapter, or invents fields. Values
that genuinely do not exist in storage (e.g. ``prompt_version`` for an
``oracle`` result with no model block) are emitted as an empty CSV cell or
``null`` in JSON, never as a made-up value.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from common.timeutil import utc_timestamp
from config import Config
from schemas.enums import VideoStatus
from schemas.video import Video
from services.errors import VideoNotProcessedError
from storage.repositories import JobRepository

#: UTF-8 BOM so Excel (Windows) detects the encoding instead of guessing GBK.
UTF8_BOM = "\ufeff"

#: Excel-friendly line terminator; the ``csv`` module quotes fields as needed.
LINE_TERMINATOR = "\r\n"

CSV_COLUMNS = (
    "video_id",
    "video_name",
    "segment_index",
    "start_s",
    "end_s",
    "scene_label",
    "confidence",
    "evidence",
    "is_uncertain",
    "prediction_source",
    "provider",
    "model_name",
    "model_version",
    "prompt_version",
    "evaluation_eligible",
)


def _format_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _format_scalar(value: Any) -> str:
    """Render a scalar for CSV, keeping ``None`` distinguishable from ``""``."""
    if value is None:
        return ""
    if isinstance(value, bool):  # pragma: no cover - booleans handled explicitly
        return _format_bool(value)
    return str(value)


class ExportService:
    """Read-only view over a video's persisted analysis result."""

    def __init__(self, config: Config) -> None:
        self._config = config
        # Only jobs are needed here: the video itself comes from VideoService,
        # so the "unknown video -> 404" rule stays in one place.
        self._jobs = JobRepository(config.database_path)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def build_json_result(self, video: Video) -> dict[str, Any]:
        """Serialize the stored result; raises when there is nothing to export."""
        self._ensure_processed(video)

        payload = video.to_dict()
        analysis = self._analysis_metadata(video)
        model = video.model or {}

        # Additive fields, all derived from data that is already persisted.
        payload["job_id"] = analysis.get("job_id")
        payload["prompt_version"] = model.get("prompt_version") or analysis.get(
            "prompt_version"
        )
        payload["is_mock"] = bool(analysis.get("is_mock"))
        payload["segment_count"] = len(video.segments)
        payload["exported_at"] = utc_timestamp()
        return payload

    def build_csv(self, video: Video) -> str:
        """Render one CSV row per stored segment (header only when empty)."""
        self._ensure_processed(video)

        analysis = self._analysis_metadata(video)
        model = video.model or {}
        prompt_version = model.get("prompt_version") or analysis.get("prompt_version")

        buffer = io.StringIO(newline="")
        writer = csv.writer(
            buffer, lineterminator=LINE_TERMINATOR, quoting=csv.QUOTE_MINIMAL
        )
        writer.writerow(CSV_COLUMNS)

        for segment in video.segments:
            writer.writerow(
                [
                    video.video_id,
                    video.name,
                    segment.get("index"),
                    segment.get("start_s"),
                    segment.get("end_s"),
                    segment.get("scene_label"),
                    _format_scalar(segment.get("confidence")),
                    segment.get("evidence") or "",
                    _format_bool(segment.get("is_uncertain")),
                    video.prediction_source.value
                    if hasattr(video.prediction_source, "value")
                    else video.prediction_source,
                    video.provider or "",
                    model.get("name") or "",
                    model.get("version") or "",
                    prompt_version or "",
                    _format_bool(video.evaluation_eligible),
                ]
            )

        return UTF8_BOM + buffer.getvalue()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _analysis_metadata(video: Video) -> dict[str, Any]:
        analysis = (video.metadata or {}).get("analysis")
        return analysis if isinstance(analysis, dict) else {}

    def _ensure_processed(self, video: Video) -> None:
        status = (
            video.status.value if hasattr(video.status, "value") else str(video.status)
        )
        if status != VideoStatus.PROCESSED.value:
            raise VideoNotProcessedError(
                video.video_id, status, self._latest_job_context(video.video_id)
            )

    def _latest_job_context(self, video_id: str) -> dict[str, Any] | None:
        """Most recent job for the video, used to explain why there is no result."""
        try:
            jobs, _total = self._jobs.list(limit=1, offset=0, video_id=video_id)
        except Exception:  # pragma: no cover - defensive: never fail the error path
            return None
        if not jobs:
            return None

        job = jobs[0]
        context: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "stage": job.stage.value,
            "progress": job.progress,
        }
        if job.error:
            context["error"] = {
                "code": job.error.get("code"),
                "message": job.error.get("message"),
                "retryable": job.error.get("retryable"),
            }
        return context
