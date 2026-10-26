"""SQL access for video records.

The repository is the only place that knows the database layout; services work
with :class:`schemas.video.Video` objects only.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from schemas.enums import (
    JobStage,
    JobStatus,
    JobType,
    PredictionSource,
    VideoStatus,
    is_evaluation_eligible,
)
from schemas.job import Job
from schemas.video import Video
from services.errors import DuplicateVideoError, JobStateError, StorageError
from storage.db import connect

_COLUMNS = (
    "video_id",
    "name",
    "source",
    "status",
    "duration_s",
    "size_bytes",
    "created_at",
    "file_url",
    "prediction_source",
    "provider",
    "evaluation_eligible",
    "model_json",
    "segments_json",
    "metadata_json",
    "storage_path",
)

_INSERT_SQL = (
    f"INSERT INTO videos ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _COLUMNS)})"
)

_SELECT_SQL = f"SELECT {', '.join(_COLUMNS)} FROM videos"


def _row_to_video(row: sqlite3.Row) -> Video:
    return Video(
        video_id=row["video_id"],
        name=row["name"],
        source=row["source"],
        status=row["status"],
        size_bytes=int(row["size_bytes"]),
        created_at=row["created_at"],
        duration_s=None if row["duration_s"] is None else float(row["duration_s"]),
        file_url=row["file_url"],
        prediction_source=row["prediction_source"],
        provider=row["provider"],
        model=json.loads(row["model_json"]) if row["model_json"] else None,
        segments=json.loads(row["segments_json"] or "[]"),
        metadata=json.loads(row["metadata_json"] or "{}"),
        storage_path=row["storage_path"],
    )


def _video_to_params(video: Video) -> tuple[Any, ...]:
    return (
        video.video_id,
        video.name,
        video.source.value,
        video.status.value,
        video.duration_s,
        int(video.size_bytes),
        video.created_at,
        video.file_url,
        video.prediction_source.value,
        video.provider,
        1 if video.evaluation_eligible else 0,
        None if video.model is None else json.dumps(video.model, ensure_ascii=False),
        json.dumps(video.segments, ensure_ascii=False),
        json.dumps(video.metadata, ensure_ascii=False),
        video.storage_path,
    )


class VideoRepository:
    """CRUD for the ``videos`` table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(self, video: Video) -> Video:
        try:
            with connect(self._db_path) as connection:
                connection.execute(_INSERT_SQL, _video_to_params(video))
        except sqlite3.IntegrityError as exc:
            raise DuplicateVideoError(video.video_id) from exc
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "write_failed"}) from exc
        return video

    def get(self, video_id: str) -> Video | None:
        try:
            with connect(self._db_path) as connection:
                row = connection.execute(
                    f"{_SELECT_SQL} WHERE video_id = ?", (video_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc
        return _row_to_video(row) if row is not None else None

    def exists(self, video_id: str) -> bool:
        try:
            with connect(self._db_path) as connection:
                row = connection.execute(
                    "SELECT 1 FROM videos WHERE video_id = ? LIMIT 1", (video_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc
        return row is not None

    def list(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        source: str | None = None,
    ) -> tuple[list[Video], int]:
        """Return ``(items, total)`` for the requested page."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source:
            clauses.append("source = ?")
            params.append(source)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        try:
            with connect(self._db_path) as connection:
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM videos{where}", tuple(params)
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    f"{_SELECT_SQL}{where} "
                    "ORDER BY created_at DESC, video_id ASC LIMIT ? OFFSET ?",
                    tuple(params) + (int(limit), int(offset)),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc

        return [_row_to_video(row) for row in rows], total

    def count(self) -> int:
        try:
            with connect(self._db_path) as connection:
                return int(connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc

    # ------------------------------------------------------------------ #
    # Transactional state transitions (driven by the job runner)
    # ------------------------------------------------------------------ #
    def set_processing(self, connection: sqlite3.Connection, video_id: str) -> None:
        """Mark the video as being analysed and drop any stale result.

        Clearing the previous analysis keeps ``status``, ``segments``,
        ``prediction_source`` and ``evaluation_eligible`` mutually consistent: a
        ``processing`` or ``failed`` video never carries labels from an earlier
        run.
        """
        connection.execute(
            "UPDATE videos SET status = ?, prediction_source = ?, provider = NULL, "
            "model_json = NULL, segments_json = '[]', evaluation_eligible = 0 "
            "WHERE video_id = ?",
            (VideoStatus.PROCESSING.value, PredictionSource.NONE.value, video_id),
        )

    def set_processed(
        self,
        connection: sqlite3.Connection,
        video_id: str,
        *,
        prediction_source: str,
        provider: str | None,
        model: dict[str, Any] | None,
        segments: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        """Persist a finished analysis; eligibility is recomputed here."""
        eligible = 1 if is_evaluation_eligible(prediction_source) else 0
        connection.execute(
            "UPDATE videos SET status = ?, prediction_source = ?, provider = ?, "
            "model_json = ?, segments_json = ?, evaluation_eligible = ?, "
            "metadata_json = ? WHERE video_id = ?",
            (
                VideoStatus.PROCESSED.value,
                PredictionSource(prediction_source).value,
                provider,
                None if model is None else json.dumps(model, ensure_ascii=False),
                json.dumps(segments, ensure_ascii=False),
                eligible,
                json.dumps(metadata, ensure_ascii=False),
                video_id,
            ),
        )

    def set_failed(self, connection: sqlite3.Connection, video_id: str) -> None:
        """Mark a processing video as failed.

        Guarded by ``status = 'processing'`` so a late failure can never
        overwrite a newer job's state.
        """
        connection.execute(
            "UPDATE videos SET status = ? WHERE video_id = ? AND status = ?",
            (VideoStatus.FAILED.value, video_id, VideoStatus.PROCESSING.value),
        )


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
_JOB_COLUMNS = (
    "job_id",
    "job_type",
    "status",
    "stage",
    "progress",
    "video_id",
    "created_at",
    "started_at",
    "finished_at",
    "result_json",
    "error_json",
    "provider",
    "model_json",
    "metadata_json",
)

_JOB_INSERT_SQL = (
    f"INSERT INTO jobs ({', '.join(_JOB_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _JOB_COLUMNS)})"
)

_JOB_SELECT_SQL = f"SELECT {', '.join(_JOB_COLUMNS)} FROM jobs"

ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=row["status"],
        stage=row["stage"],
        progress=float(row["progress"]),
        video_id=row["video_id"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=json.loads(row["error_json"]) if row["error_json"] else None,
        provider=row["provider"],
        model=json.loads(row["model_json"]) if row["model_json"] else None,
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def _job_to_params(job: Job) -> tuple[Any, ...]:
    return (
        job.job_id,
        JobType(job.job_type).value,
        JobStatus(job.status).value,
        JobStage(job.stage).value,
        float(job.progress),
        job.video_id,
        job.created_at,
        job.started_at,
        job.finished_at,
        None if job.result is None else json.dumps(job.result, ensure_ascii=False),
        None if job.error is None else json.dumps(job.error, ensure_ascii=False),
        job.provider,
        None if job.model is None else json.dumps(job.model, ensure_ascii=False),
        json.dumps(job.metadata, ensure_ascii=False),
    )


class JobRepository:
    """Persistence for analysis jobs plus their guarded state transitions.

    Every transition is expressed as a conditional ``UPDATE ... WHERE status IN
    (...)``; when no row matches, the transition is illegal and
    :class:`JobStateError` is raised. That is what keeps ``status``,
    ``progress``, ``started_at`` and ``finished_at`` mutually consistent even if
    two code paths race.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # -- reads / create -----------------------------------------------------
    def create_in(self, connection: sqlite3.Connection, job: Job) -> Job:
        """Insert a job using a caller-supplied connection.

        Used by the service so the job insert and the video status change share
        one transaction.
        """
        connection.execute(_JOB_INSERT_SQL, _job_to_params(job))
        return job

    def create(self, job: Job) -> Job:
        try:
            with connect(self._db_path) as connection:
                self.create_in(connection, job)
        except sqlite3.IntegrityError as exc:
            raise StorageError(details={"reason": "job_id_conflict"}) from exc
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "write_failed"}) from exc
        return job

    def get(self, job_id: str) -> Job | None:
        try:
            with connect(self._db_path) as connection:
                row = connection.execute(
                    f"{_JOB_SELECT_SQL} WHERE job_id = ?", (job_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc
        return _row_to_job(row) if row is not None else None

    def list(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        video_id: str | None = None,
        job_type: str | None = None,
    ) -> tuple[list[Job], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if video_id:
            clauses.append("video_id = ?")
            params.append(video_id)
        if job_type:
            clauses.append("job_type = ?")
            params.append(job_type)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        try:
            with connect(self._db_path) as connection:
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM jobs{where}", tuple(params)
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    f"{_JOB_SELECT_SQL}{where} "
                    "ORDER BY created_at DESC, job_id ASC LIMIT ? OFFSET ?",
                    tuple(params) + (int(limit), int(offset)),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc

        return [_row_to_job(row) for row in rows], total

    def find_active_for_video(self, video_id: str) -> Job | None:
        """Return the queued/running job of a video, if any."""
        placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
        try:
            with connect(self._db_path) as connection:
                row = connection.execute(
                    f"{_JOB_SELECT_SQL} WHERE video_id = ? AND status IN ({placeholders}) "
                    "ORDER BY created_at DESC LIMIT 1",
                    (video_id, *ACTIVE_JOB_STATUSES),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "read_failed"}) from exc
        return _row_to_job(row) if row is not None else None

    # -- guarded transitions ------------------------------------------------
    @staticmethod
    def _expect_one(cursor: sqlite3.Cursor, job_id: str, expected: str) -> None:
        if cursor.rowcount != 1:
            raise JobStateError(job_id, expected=expected)

    def mark_running(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        *,
        stage: str,
        progress: float,
        started_at: str,
    ) -> None:
        cursor = connection.execute(
            "UPDATE jobs SET status = ?, stage = ?, progress = ?, started_at = ? "
            "WHERE job_id = ? AND status = ?",
            (
                JobStatus.RUNNING.value,
                JobStage(stage).value,
                Job.validate_progress(progress),
                started_at,
                job_id,
                JobStatus.QUEUED.value,
            ),
        )
        self._expect_one(cursor, job_id, "queued -> running")

    def update_progress(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        *,
        stage: str,
        progress: float,
    ) -> None:
        cursor = connection.execute(
            "UPDATE jobs SET stage = ?, progress = ? WHERE job_id = ? AND status = ?",
            (
                JobStage(stage).value,
                Job.validate_progress(progress),
                job_id,
                JobStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:  # pragma: no cover - defensive
            raise JobStateError(job_id, expected="running -> running")

    def mark_completed(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        *,
        result: dict[str, Any],
        finished_at: str,
        provider: str | None = None,
        model: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cursor = connection.execute(
            "UPDATE jobs SET status = ?, stage = ?, progress = 1.0, result_json = ?, "
            "finished_at = ?, provider = COALESCE(?, provider), "
            "model_json = COALESCE(?, model_json), "
            "metadata_json = COALESCE(?, metadata_json) "
            "WHERE job_id = ? AND status = ?",
            (
                JobStatus.COMPLETED.value,
                JobStage.DONE.value,
                json.dumps(result, ensure_ascii=False),
                finished_at,
                provider,
                None if model is None else json.dumps(model, ensure_ascii=False),
                None if metadata is None else json.dumps(metadata, ensure_ascii=False),
                job_id,
                JobStatus.RUNNING.value,
            ),
        )
        self._expect_one(cursor, job_id, "running -> completed")

    def mark_failed(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        *,
        stage: str,
        error: dict[str, Any],
        finished_at: str,
    ) -> None:
        placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
        cursor = connection.execute(
            "UPDATE jobs SET status = ?, stage = ?, error_json = ?, "
            "finished_at = ?, result_json = NULL "
            f"WHERE job_id = ? AND status IN ({placeholders})",
            (
                JobStatus.FAILED.value,
                JobStage(stage).value,
                json.dumps(error, ensure_ascii=False),
                finished_at,
                job_id,
                *ACTIVE_JOB_STATUSES,
            ),
        )
        if cursor.rowcount != 1:  # pragma: no cover - defensive
            raise JobStateError(job_id, expected="queued|running -> failed")

    def fail_orphaned(
        self,
        connection: sqlite3.Connection,
        *,
        finished_at: str,
        error: dict[str, Any] | None = None,
    ) -> list[tuple[str, str]]:
        """Fail jobs left queued/running by a previous process.

        A single-process worker cannot resume work that a crash interrupted;
        pretending such a job is still running would be a lie, so it is marked
        ``failed`` with a readable reason (and its video with it).
        """
        payload = error or {
            "code": "JOB_INTERRUPTED",
            "message": "服务重启导致任务中断，请重新提交",
            "retryable": True,
        }
        placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
        rows = connection.execute(
            f"SELECT job_id, video_id FROM jobs WHERE status IN ({placeholders})",
            ACTIVE_JOB_STATUSES,
        ).fetchall()

        result: list[tuple[str, str]] = []
        for row in rows:
            connection.execute(
                "UPDATE jobs SET status = ?, error_json = ?, finished_at = ?, "
                "result_json = NULL "
                f"WHERE job_id = ? AND status IN ({placeholders})",
                (
                    JobStatus.FAILED.value,
                    json.dumps(payload, ensure_ascii=False),
                    finished_at,
                    row["job_id"],
                    *ACTIVE_JOB_STATUSES,
                ),
            )
            result.append((row["job_id"], row["video_id"]))
        return result

