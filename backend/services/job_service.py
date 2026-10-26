"""Job business logic: creation policy, lookup and listing.

The service owns the rules the client must not decide:

* a job is created as ``queued`` with ``progress = 0``;
* the video moves to ``processing`` in the **same transaction** as the job row,
  so a crash cannot leave a queued job whose video still looks untouched;
* duplicate submission is rejected explicitly (``409 JOB_ALREADY_RUNNING``)
  while the video already has a queued/running job.
"""

from __future__ import annotations

import uuid

from common.timeutil import utc_timestamp
from config import Config
from schemas.enums import JobStage, JobStatus, JobType, enum_values
from schemas.job import Job
from services.errors import (
    InvalidVideoRequestError,
    JobAlreadyRunningError,
    JobNotFoundError,
    VideoNotFoundError,
)
from storage.db import connect
from storage.repositories import JobRepository, VideoRepository

JOB_ID_PREFIX = "job_"


class JobService:
    """Creates and reads analysis jobs."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._jobs = JobRepository(config.database_path)
        self._videos = VideoRepository(config.database_path)
        self._runner = None

    def attach_runner(self, runner) -> None:
        """Wire the execution queue after construction (the runner needs us)."""
        self._runner = runner

    # ------------------------------------------------------------------ #
    # Creation
    # ------------------------------------------------------------------ #
    def create_video_process_job(self, video_id: str) -> Job:
        """Queue a ``video_process`` job for an existing video."""
        video = self._videos.get(video_id)
        if video is None:
            raise VideoNotFoundError(video_id)

        active = self._jobs.find_active_for_video(video_id)
        if active is not None:
            # Explicit rejection instead of silently piling up duplicate work.
            raise JobAlreadyRunningError(
                video_id, active.job_id, active.status.value
            )

        job = Job(
            job_id=f"{JOB_ID_PREFIX}{uuid.uuid4().hex[:12]}",
            job_type=JobType.VIDEO_PROCESS,
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            progress=0.0,
            video_id=video_id,
            created_at=utc_timestamp(),
            metadata={"requested_from": "api"},
        )

        # One transaction: job row + video status change.
        with connect(self._config.database_path) as connection:
            self._jobs.create_in(connection, job)
            self._videos.set_processing(connection, video_id)

        if self._runner is not None:
            self._runner.submit(job.job_id)
        return job

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def list_jobs(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        video_id: str | None = None,
        job_type: str | None = None,
    ) -> dict:
        status_value = self._validate_enum("status", status, JobStatus)
        job_type_value = self._validate_enum("job_type", job_type, JobType)

        jobs, total = self._jobs.list(
            limit=limit,
            offset=offset,
            status=status_value,
            video_id=video_id or None,
            job_type=job_type_value,
        )
        items = [job.to_dict() for job in jobs]

        return {
            "items": items,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_next": offset + len(items) < total,
            },
            # Transition alias required by the standard (section 1.4).
            "jobs": items,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_enum(field: str, value: str | None, enum_cls) -> str | None:
        if not value:
            return None
        try:
            return enum_cls(value).value
        except ValueError as exc:
            raise InvalidVideoRequestError(
                f"{field} 不是合法值",
                details={"field": field, "allowed": enum_values(enum_cls)},
            ) from exc
