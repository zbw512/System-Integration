"""Minimal in-process job execution.

Design choices (also documented in README §"任务机制"):

* **one** background thread, **one** queue, **one** job at a time. The future
  MiniCPM adapter needs the whole 8 GB GPU, so serialising is deliberate, not a
  shortcut;
* no Redis/Celery — a single-process development deployment gains nothing from
  them, and the task book forbids adding heavy infrastructure without approval;
* the HTTP request only enqueues; it never waits for the analysis to finish;
* no ``sleep`` is used to fake progress. The mock adapter is genuinely fast, so
  intermediate stages are simply brief; tests that need to observe ``running``
  use a deliberately blocking adapter instead of a timer;
* every state change is a guarded SQL ``UPDATE ... WHERE status = ...`` (see
  :class:`storage.repositories.JobRepository`), and the job row and the video
  row are updated inside **one** transaction.

``canceled`` is part of the standard's state machine but has no cancellation
mechanism in P0-3; the API therefore never reports a job as canceled.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Callable

from adapters.vlm.base import AnalysisRequest, VlmAdapter
from common.timeutil import utc_timestamp
from config import Config
from schemas.enums import JobStage, JobStatus, PredictionSource
from schemas.job import Job
from schemas.segment import Segment
from services.errors import (
    JobStateError,
    ServiceError,
    StoredFileMissingError,
    VlmResultInvalidError,
)
from storage import files as storage_files
from storage.db import connect
from storage.repositories import JobRepository, VideoRepository

logger = logging.getLogger(__name__)

DEFAULT_DRAIN_TIMEOUT = 30.0


class JobRunner:
    """Serialises analysis jobs and drives the job/video state machine."""

    def __init__(
        self,
        config: Config,
        *,
        adapter_getter: Callable[[], VlmAdapter],
        job_service,
    ) -> None:
        self._config = config
        self._db_path = config.database_path
        self._adapter_getter = adapter_getter
        self._job_service = job_service
        self._jobs = JobRepository(self._db_path)
        self._videos = VideoRepository(self._db_path)

        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
        self._thread.start()
        logger.info("job runner started (single worker thread)")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        logger.info("job runner stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ #
    # Queue
    # ------------------------------------------------------------------ #
    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def run_until_idle(self, timeout: float = DEFAULT_DRAIN_TIMEOUT) -> int:
        """Execute everything currently queued, synchronously.

        Used by the tests (deterministic, no threads) and available for manual
        operation. Returns the number of executed jobs.
        """
        deadline = time.monotonic() + timeout
        executed = 0
        while time.monotonic() < deadline:
            try:
                job_id = self._queue.get_nowait()
            except queue.Empty:
                return executed
            self._execute(job_id)
            executed += 1
        raise TimeoutError("任务队列未在超时时间内清空")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._execute(job_id)
            except Exception:  # pragma: no cover - last-resort guard
                logger.exception("job runner crashed while executing %s", job_id)

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    def _execute(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            logger.warning("job %s not found, skipping", job_id)
            return
        if job.status is not JobStatus.QUEUED:
            logger.info("job %s is %s, skipping", job_id, job.status.value)
            return

        video = self._videos.get(job.video_id)
        if video is None:
            self._fail(
                job_id=job_id,
                video_id=None,
                stage=JobStage.QUEUED,
                code="VIDEO_NOT_FOUND",
                message="视频不存在",
                retryable=False,
            )
            return

        stage_state = {"stage": JobStage.LOADING_VIDEO}

        def report_progress(stage_name: str, progress: float) -> None:
            """Adapter-facing hook: persist a real stage/progress pair."""
            try:
                job_stage = JobStage(stage_name)
            except ValueError:  # pragma: no cover - adapter bug guard
                return
            stage_state["stage"] = job_stage
            self._set_progress(job_id, job_stage, progress)

        try:
            with connect(self._db_path) as connection:
                self._jobs.mark_running(
                    connection,
                    job_id,
                    stage=JobStage.LOADING_VIDEO.value,
                    progress=0.1,
                    started_at=utc_timestamp(),
                )

            video_path = self._resolve_video_path(video)
            adapter = self._adapter_getter()

            if getattr(adapter, "uses_frame_sampling", False):
                # Sampling/inference stages are reported by the adapter itself.
                report_progress(JobStage.SAMPLING_FRAMES.value, 0.2)
            else:
                report_progress(JobStage.INFERENCE.value, 0.35)

            output = adapter.analyze(
                AnalysisRequest(
                    job_id=job_id,
                    video_id=video.video_id,
                    video_path=video_path,
                    duration_s=video.duration_s,
                    video_metadata=dict(video.metadata),
                    on_progress=report_progress,
                )
            )

            report_progress(JobStage.PARSING.value, 0.8)
            segments = self._validated_segments(output.segments, video.duration_s)

            report_progress(JobStage.SAVING.value, 0.9)

            self._complete(job=job, video=video, output=output, segments=segments)

        except JobStateError:
            # The job was completed/failed elsewhere — nothing left to do.
            logger.warning("job %s state changed during execution, aborting", job_id)
        except ServiceError as exc:
            logger.warning("job %s failed: %s %s", job_id, exc.code, exc.message)
            self._fail(
                job_id=job_id,
                video_id=video.video_id,
                stage=stage_state["stage"],
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                details=exc.details,
            )
        except Exception:
            logger.exception("job %s crashed", job_id)
            self._fail(
                job_id=job_id,
                video_id=video.video_id,
                stage=stage_state["stage"],
                code="INTERNAL_ERROR",
                message="任务执行失败",
                retryable=True,
            )

    # -- steps -----------------------------------------------------------
    def _resolve_video_path(self, video) -> str:
        if not video.storage_path:
            raise StoredFileMissingError(details={"video_id": video.video_id})
        try:
            path = storage_files.resolve_stored_path(
                self._config.data_dir, video.storage_path
            )
        except storage_files.PathEscapeError as exc:
            raise StoredFileMissingError(details={"video_id": video.video_id}) from exc
        if not os.path.isfile(path):
            raise StoredFileMissingError(details={"video_id": video.video_id})
        return path

    def _set_progress(self, job_id: str, stage: JobStage, progress: float) -> None:
        with connect(self._db_path) as connection:
            self._jobs.update_progress(
                connection, job_id, stage=stage.value, progress=progress
            )

    def _validated_segments(
        self, raw: Any, duration_s: float | None
    ) -> list[dict[str, Any]]:
        """Re-validate adapter output; the adapter cannot bypass the standard."""
        if not isinstance(raw, list):
            raise VlmResultInvalidError("适配器返回的 segments 不是数组")

        validated: list[dict[str, Any]] = []
        previous_end: float | None = None

        for position, item in enumerate(raw):
            if not isinstance(item, dict):
                raise VlmResultInvalidError(
                    "segment 必须是对象", details={"position": position}
                )
            try:
                segment = Segment(
                    index=item.get("index", position),
                    start_s=item["start_s"],
                    end_s=item["end_s"],
                    scene_label=item["scene_label"],
                    confidence=item.get("confidence"),
                    evidence=item.get("evidence", ""),
                    is_uncertain=bool(item.get("is_uncertain", False)),
                )
                segment.validate(duration_s=duration_s)
            except KeyError as exc:
                raise VlmResultInvalidError(
                    f"segment 缺少字段：{exc}", details={"position": position}
                ) from exc
            except (TypeError, ValueError) as exc:
                raise VlmResultInvalidError(
                    f"segment 不合法：{exc}", details={"position": position}
                ) from exc

            if previous_end is not None and segment.start_s < previous_end - 1e-6:
                raise VlmResultInvalidError(
                    "segments 必须按时间升序且不重叠", details={"position": position}
                )
            previous_end = segment.end_s
            validated.append(segment.to_dict())

        return validated

    def _complete(self, *, job: Job, video, output, segments: list[dict[str, Any]]) -> None:
        prediction_source = PredictionSource(output.prediction_source)
        model = dict(output.model) if output.model else None
        is_mock = bool(output.metadata.get("is_mock")) or (
            prediction_source is PredictionSource.MOCK
        )

        result = {
            "video_id": video.video_id,
            "prediction_source": prediction_source.value,
            "provider": output.provider,
            "model": model,
            "segments": segments,
            "segment_count": len(segments),
            "is_mock": is_mock,
        }

        analysis_metadata = {
            "job_id": job.job_id,
            "provider": output.provider,
            "model": model,
            "prediction_source": prediction_source.value,
            "is_mock": is_mock,
            "prompt_version": (model or {}).get("prompt_version"),
        }
        video_metadata = dict(video.metadata)
        video_metadata["analysis"] = analysis_metadata

        job_metadata = dict(job.metadata)
        job_metadata.update(
            {
                "adapter": output.metadata.get("adapter"),
                "is_mock": is_mock,
            }
        )

        finished_at = utc_timestamp()
        with connect(self._db_path) as connection:
            self._jobs.mark_completed(
                connection,
                job.job_id,
                result=result,
                finished_at=finished_at,
                provider=output.provider,
                model=model,
                metadata=job_metadata,
            )
            self._videos.set_processed(
                connection,
                video.video_id,
                prediction_source=prediction_source.value,
                provider=output.provider,
                model=model,
                segments=segments,
                metadata=video_metadata,
            )

    def _fail(
        self,
        *,
        job_id: str,
        video_id: str | None,
        stage: JobStage,
        code: str,
        message: str,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        error: dict[str, Any] = {
            "code": code,
            "message": message,
            "retryable": bool(retryable),
        }
        if details:
            error["details"] = details

        try:
            with connect(self._db_path) as connection:
                self._jobs.mark_failed(
                    connection,
                    job_id,
                    stage=stage.value,
                    error=error,
                    finished_at=utc_timestamp(),
                )
                if video_id:
                    self._videos.set_failed(connection, video_id)
        except JobStateError:
            logger.warning("job %s could not be marked failed (state moved on)", job_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to persist failure for job %s", job_id)
