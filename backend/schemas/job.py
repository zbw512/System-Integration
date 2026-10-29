"""``Job`` schema — interface standard section 3.3.

A job is the persistent record of one asynchronous analysis attempt. The
standard defines the first twelve fields below; ``provider``, ``model`` and
``metadata`` are additive (the standard allows backward-compatible additions)
and record *which* adapter produced the result — mandatory for P0-3, where the
adapter is a mock and must never be mistaken for real MiniCPM inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import SCHEMA_VERSION
from schemas.enums import JobStage, JobStatus, JobType

#: Inclusive range every ``progress`` value must fall into.
PROGRESS_MIN = 0.0
PROGRESS_MAX = 1.0


class JobValidationError(ValueError):
    """Raised when a job record would violate the standard's constraints."""

    def __init__(self, message: str, *, field_name: str) -> None:
        self.field = field_name
        super().__init__(message)


@dataclass
class Job:
    job_id: str
    job_type: JobType | str
    status: JobStatus | str
    stage: JobStage | str
    progress: float
    video_id: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    # Additive fields (not in the standard's Job example).
    provider: str | None = None
    model: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None

    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.job_type = JobType(self.job_type)
        self.status = JobStatus(self.status)
        self.stage = JobStage(self.stage)
        self.progress = self.validate_progress(self.progress)

        if not isinstance(self.metadata, dict):
            raise JobValidationError("metadata 必须是对象", field_name="metadata")
        if self.result is not None and not isinstance(self.result, dict):
            raise JobValidationError("result 必须是对象或 null", field_name="result")
        if self.error is not None and not isinstance(self.error, dict):
            raise JobValidationError("error 必须是对象或 null", field_name="error")

        # Status/stage/progress invariants (kept in one place so the runner and
        # the repository cannot drift apart).
        if self.status is JobStatus.QUEUED and self.progress != 0.0:
            raise JobValidationError(
                "queued 状态的 progress 必须为 0", field_name="progress"
            )
        if self.status is JobStatus.COMPLETED:
            if self.progress != PROGRESS_MAX:
                raise JobValidationError(
                    "completed 状态的 progress 必须为 1", field_name="progress"
                )
            if self.finished_at is None:
                raise JobValidationError(
                    "completed 状态必须有 finished_at", field_name="finished_at"
                )
        if self.status is JobStatus.FAILED:
            if self.error is None:
                raise JobValidationError(
                    "failed 状态必须记录 error", field_name="error"
                )
            if self.result is not None:
                raise JobValidationError(
                    "failed 状态不得带 result（避免伪造成功）", field_name="result"
                )
        if self.status is JobStatus.RUNNING and self.started_at is None:
            raise JobValidationError(
                "running 状态必须有 started_at", field_name="started_at"
            )

    @staticmethod
    def validate_progress(value: float) -> float:
        try:
            progress = float(value)
        except (TypeError, ValueError) as exc:
            raise JobValidationError("progress 必须是数字", field_name="progress") from exc
        if not PROGRESS_MIN <= progress <= PROGRESS_MAX:
            raise JobValidationError(
                "progress 必须在 0 到 1 之间", field_name="progress"
            )
        return progress

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format defined by the standard."""
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "job_type": JobType(self.job_type).value,
            "status": JobStatus(self.status).value,
            "stage": JobStage(self.stage).value,
            "progress": self.progress,
            "video_id": self.video_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "provider": self.provider,
            "model": self.model,
            "metadata": self.metadata,
        }

    @property
    def is_active(self) -> bool:
        """Whether the job still occupies the video (queued or running)."""
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)
