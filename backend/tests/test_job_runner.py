"""Job runner / state machine tests.

These tests cover the mechanics that the HTTP tests deliberately avoid:

* the real queued -> running -> completed transition of the background thread;
* adapter failures and illegal adapter output being turned into ``failed`` jobs;
* the guarded SQL transitions refusing illegal changes;
* progress bounds.
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from adapters.vlm.mock import MockVlmAdapter
from app import create_app
from config import Config
from media_fixtures import make_minimal_mp4
from schemas.enums import JobStage, JobStatus
from schemas.job import Job, JobValidationError
from services.errors import JobStateError, VlmAnalysisError
from storage.db import connect
from storage.repositories import JobRepository


class StubAdapter(VlmAdapter):
    """Adapter double with an optional gate and injectable failure."""

    name = "stub"

    def __init__(self, *, output=None, error=None, gate: threading.Event | None = None):
        self._output = output
        self._error = error
        self._gate = gate
        self.calls = 0

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "status": "stub"}

    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        self.calls += 1
        if self._gate is not None:
            self._gate.wait(timeout=10)
        if self._error is not None:
            raise self._error
        if self._output is not None:
            return self._output
        return MockVlmAdapter().analyze(request)


def mock_output(duration_s: float = 3.0) -> AnalysisOutput:
    return MockVlmAdapter().analyze(
        AnalysisRequest(
            job_id="job_unit",
            video_id="vid_unit",
            video_path="unused.mp4",
            duration_s=duration_s,
        )
    )


def upload_video(client, name: str = "clip.mp4", duration: float = 3.0) -> str:
    data = {"file": (io.BytesIO(make_minimal_mp4(duration)), name)}
    response = client.post(
        "/api/v1/videos/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def start_job(client, video_id: str):
    return client.post(f"/api/v1/videos/{video_id}/process")


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------- #
# Real background thread: queued -> running -> completed
# --------------------------------------------------------------------------- #
def test_job_transitions_queued_running_completed(tmp_path: Path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=True,
    )
    app = create_app(config)
    gate = threading.Event()
    app.extensions["vlm_adapter"] = StubAdapter(gate=gate, output=mock_output(3.0))
    client = app.test_client()

    try:
        video_id = upload_video(client)
        response = start_job(client, video_id)

        assert response.status_code == 202
        job_id = response.get_json()["job_id"]
        assert response.get_json()["status"] == "queued"

        def job_state() -> dict:
            return client.get(f"/api/v1/jobs/{job_id}").get_json()

        # The worker picks the job up...
        assert wait_for(lambda: job_state()["status"] == "running")
        # ...advances to the inference stage and blocks inside the adapter.
        assert wait_for(lambda: job_state()["stage"] == "inference")

        running = job_state()
        assert running["status"] == "running"
        assert 0.0 < running["progress"] < 1.0
        assert running["started_at"] is not None
        assert running["finished_at"] is None

        gate.set()

        assert wait_for(lambda: job_state()["status"] == "completed")
        done = job_state()
        assert done["stage"] == "done"
        assert done["progress"] == 1.0
        assert done["finished_at"] is not None
        assert done["error"] is None

        video = client.get(f"/api/v1/videos/{video_id}").get_json()
        assert video["status"] == "processed"
        assert video["prediction_source"] == "mock"
    finally:
        app.extensions["job_runner"].stop()


# --------------------------------------------------------------------------- #
# Failure paths
# --------------------------------------------------------------------------- #
def test_adapter_error_fails_job_and_video(client, drain):
    adapters = client.application.extensions
    adapters["vlm_adapter"] = StubAdapter(error=VlmAnalysisError("模型不可用"))

    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VLM_UPSTREAM_ERROR"
    assert job["error"]["retryable"] is True
    assert job["result"] is None

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"
    assert video["segments"] == []
    assert video["prediction_source"] == "none"
    assert video["evaluation_eligible"] is False


def test_unexpected_adapter_exception_becomes_internal_error(client, drain):
    client.application.extensions["vlm_adapter"] = StubAdapter(
        error=RuntimeError("secret internal detail")
    )

    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    response = client.get(f"/api/v1/jobs/{job_id}")
    job = response.get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.get_data(as_text=True)


def test_illegal_segments_from_adapter_are_rejected(client, drain):
    broken = AnalysisOutput(
        prediction_source="mock",
        provider="stub",
        model={"name": "stub"},
        segments=[
            {"index": 0, "start_s": 2.0, "end_s": 1.0, "scene_label": "听讲", "confidence": 0.5}
        ],
    )
    client.application.extensions["vlm_adapter"] = StubAdapter(output=broken)

    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VLM_RESULT_INVALID"
    assert job["result"] is None


def test_missing_video_file_fails_job(client, drain, config):
    video_id = upload_video(client)
    stored = Path(config.videos_dir) / f"{video_id}.mp4"
    stored.unlink()

    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VIDEO_FILE_MISSING"

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"


def test_failed_job_can_be_submitted_again(client, drain):
    client.application.extensions["vlm_adapter"] = StubAdapter(
        error=VlmAnalysisError("第一次失败")
    )
    video_id = upload_video(client)
    first_job = start_job(client, video_id).get_json()["job_id"]
    drain()
    assert client.get(f"/api/v1/jobs/{first_job}").get_json()["status"] == "failed"

    # Restore a working adapter and retry: a new job is created, no conflict.
    client.application.extensions["vlm_adapter"] = MockVlmAdapter()
    second = start_job(client, video_id)
    assert second.status_code == 202
    assert second.get_json()["job_id"] != first_job

    drain()
    assert client.get(f"/api/v1/jobs/{second.get_json()['job_id']}").get_json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# Guarded transitions and progress bounds
# --------------------------------------------------------------------------- #
@pytest.fixture()
def job_id(client) -> str:
    video_id = upload_video(client)
    return start_job(client, video_id).get_json()["job_id"]


def test_mark_running_twice_is_rejected(client, config, job_id):
    repository = JobRepository(config.database_path)

    with connect(config.database_path) as connection:
        repository.mark_running(
            connection, job_id, stage=JobStage.LOADING_VIDEO.value, progress=0.1,
            started_at="2026-10-22T00:00:00Z",
        )

    with pytest.raises(JobStateError):
        with connect(config.database_path) as connection:
            repository.mark_running(
                connection, job_id, stage=JobStage.INFERENCE.value, progress=0.3,
                started_at="2026-10-22T00:00:01Z",
            )


def test_completing_a_queued_job_is_rejected(client, config, job_id):
    repository = JobRepository(config.database_path)

    with pytest.raises(JobStateError):
        with connect(config.database_path) as connection:
            repository.mark_completed(
                connection,
                job_id,
                result={"segments": []},
                finished_at="2026-10-22T00:00:00Z",
            )


@pytest.mark.parametrize("progress", [-0.1, 1.1, "abc"])
def test_progress_outside_range_is_rejected(config, progress):
    with pytest.raises(JobValidationError):
        Job(
            job_id="job_x",
            job_type="video_process",
            status=JobStatus.RUNNING,
            stage=JobStage.INFERENCE,
            progress=progress,
            video_id="vid_x",
            created_at="2026-10-22T00:00:00Z",
            started_at="2026-10-22T00:00:00Z",
        )


def test_completed_job_must_have_progress_one():
    with pytest.raises(JobValidationError):
        Job(
            job_id="job_x",
            job_type="video_process",
            status=JobStatus.COMPLETED,
            stage=JobStage.DONE,
            progress=0.9,
            video_id="vid_x",
            created_at="2026-10-22T00:00:00Z",
            finished_at="2026-10-22T00:00:01Z",
        )


def test_failed_job_must_carry_error_and_no_result():
    with pytest.raises(JobValidationError):
        Job(
            job_id="job_x",
            job_type="video_process",
            status=JobStatus.FAILED,
            stage=JobStage.INFERENCE,
            progress=0.3,
            video_id="vid_x",
            created_at="2026-10-22T00:00:00Z",
            finished_at="2026-10-22T00:00:01Z",
        )

    with pytest.raises(JobValidationError):
        Job(
            job_id="job_x",
            job_type="video_process",
            status=JobStatus.FAILED,
            stage=JobStage.INFERENCE,
            progress=0.3,
            video_id="vid_x",
            created_at="2026-10-22T00:00:00Z",
            finished_at="2026-10-22T00:00:01Z",
            error={"code": "X", "message": "y"},
            result={"segments": []},
        )


def test_queued_job_must_have_zero_progress():
    with pytest.raises(JobValidationError):
        Job(
            job_id="job_x",
            job_type="video_process",
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            progress=0.5,
            video_id="vid_x",
            created_at="2026-10-22T00:00:00Z",
        )


def test_runner_skips_jobs_that_are_not_queued(client, drain, job_id):
    drain()
    runner = client.application.extensions["job_runner"]

    # Submitting a completed job id again must not resurrect it.
    runner.submit(job_id)
    assert runner.run_until_idle() == 1

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "completed"
    assert job["progress"] == 1.0


def test_run_until_idle_returns_zero_when_queue_is_empty(client):
    runner = client.application.extensions["job_runner"]
    assert runner.run_until_idle() == 0
