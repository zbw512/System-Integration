"""API tests for P0-3: job creation, query, mock analysis and consistency."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import create_app
from assertions import TIMESTAMP_RE, assert_unified_error
from config import Config
from media_fixtures import make_ftyp_only_mp4, make_minimal_mp4
from schemas.enums import SceneLabel

JOB_FIELDS = {
    "schema_version",
    "job_id",
    "job_type",
    "status",
    "stage",
    "progress",
    "video_id",
    "created_at",
    "started_at",
    "finished_at",
    "result",
    "error",
    "provider",
    "model",
    "metadata",
}


def upload_video(client, *, name: str = "clip.mp4", duration: float = 3.0) -> str:
    data = {"file": (io.BytesIO(make_minimal_mp4(duration)), name)}
    response = client.post(
        "/api/v1/videos/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def upload_video_without_duration(client, *, name: str = "nodur.mp4") -> str:
    data = {"file": (io.BytesIO(make_ftyp_only_mp4()), name)}
    response = client.post(
        "/api/v1/videos/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201
    assert response.get_json()["duration_s"] is None
    return response.get_json()["video_id"]


def start_job(client, video_id: str):
    return client.post(f"/api/v1/videos/{video_id}/process")


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #
def test_create_job_returns_202_with_queued_job(client):
    video_id = upload_video(client)

    response = start_job(client, video_id)

    assert response.status_code == 202
    body = response.get_json()
    assert set(body) == JOB_FIELDS, f"字段与标准不一致：{sorted(body)}"
    assert body["schema_version"] == "1.0"
    assert body["job_id"].startswith("job_")
    assert body["job_type"] == "video_process"
    assert body["status"] == "queued"
    assert body["stage"] == "queued"
    assert body["progress"] == 0.0
    assert body["video_id"] == video_id
    assert body["started_at"] is None
    assert body["finished_at"] is None
    assert body["result"] is None
    assert body["error"] is None
    assert TIMESTAMP_RE.match(body["created_at"])
    assert response.headers["Location"] == f"/api/v1/jobs/{body['job_id']}"


def test_create_job_for_unknown_video_returns_unified_404(client):
    response = start_job(client, "vid_does_not_exist")

    error = assert_unified_error(response, status=404, code="VIDEO_NOT_FOUND")
    assert error["details"]["video_id"] == "vid_does_not_exist"


def test_create_job_moves_video_to_processing_without_faking_result(client):
    video_id = upload_video(client)

    start_job(client, video_id)

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "processing"
    # A queued job is not an analysis result.
    assert video["segments"] == []
    assert video["model"] is None
    assert video["provider"] is None
    assert video["prediction_source"] == "none"
    assert video["evaluation_eligible"] is False


def test_duplicate_submission_is_rejected_explicitly(client):
    video_id = upload_video(client)
    first = start_job(client, video_id).get_json()

    response = start_job(client, video_id)

    error = assert_unified_error(response, status=409, code="JOB_ALREADY_RUNNING")
    assert error["details"]["job_id"] == first["job_id"]
    assert error["details"]["video_id"] == video_id
    assert error["details"]["job_status"] == "queued"

    # Still exactly one job.
    listing = client.get(f"/api/v1/jobs?video_id={video_id}").get_json()
    assert listing["pagination"]["total"] == 1


def test_duplicate_submission_is_allowed_after_completion(client, drain):
    video_id = upload_video(client)
    start_job(client, video_id)
    drain()

    second = start_job(client, video_id)

    assert second.status_code == 202
    listing = client.get(f"/api/v1/jobs?video_id={video_id}").get_json()
    assert listing["pagination"]["total"] == 2


def test_cancel_endpoint_is_not_implemented(client):
    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]

    # No fake "canceled" response: the route simply does not exist.
    response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code in (404, 405)
    assert response.mimetype == "application/json"


# --------------------------------------------------------------------------- #
# Query
# --------------------------------------------------------------------------- #
def test_job_detail_and_list(client):
    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]

    detail = client.get(f"/api/v1/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.get_json()["job_id"] == job_id

    listing = client.get("/api/v1/jobs").get_json()
    assert set(listing) == {"items", "pagination", "jobs"}
    assert listing["jobs"] == listing["items"]
    assert listing["pagination"]["total"] == 1
    assert listing["pagination"]["has_next"] is False


def test_unknown_job_returns_unified_404(client):
    response = client.get("/api/v1/jobs/job_does_not_exist")

    error = assert_unified_error(response, status=404, code="JOB_NOT_FOUND")
    assert error["details"] == {
        "resource": "job",
        "job_id": "job_does_not_exist",
    }


def test_job_list_filters(client, drain):
    first_video = upload_video(client, name="a.mp4")
    second_video = upload_video(client, name="b.mp4")
    first_job = start_job(client, first_video).get_json()["job_id"]
    start_job(client, second_video)
    drain()

    by_video = client.get(f"/api/v1/jobs?video_id={first_video}").get_json()
    assert by_video["pagination"]["total"] == 1
    assert by_video["items"][0]["job_id"] == first_job

    by_status = client.get("/api/v1/jobs?status=completed").get_json()
    assert by_status["pagination"]["total"] == 2

    by_type = client.get("/api/v1/jobs?job_type=video_process").get_json()
    assert by_type["pagination"]["total"] == 2

    empty = client.get("/api/v1/jobs?status=failed").get_json()
    assert empty["pagination"]["total"] == 0


def test_job_list_pagination(client, drain):
    video_id = upload_video(client)
    for _ in range(3):
        start_job(client, video_id)
        drain()

    first = client.get("/api/v1/jobs?limit=2&offset=0").get_json()
    second = client.get("/api/v1/jobs?limit=2&offset=2").get_json()

    assert first["pagination"] == {"limit": 2, "offset": 0, "total": 3, "has_next": True}
    assert second["pagination"] == {"limit": 2, "offset": 2, "total": 3, "has_next": False}
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1

    seen = {item["job_id"] for item in first["items"] + second["items"]}
    assert len(seen) == 3


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "limit=x", "offset=-1", "offset=y"])
def test_job_list_rejects_invalid_pagination(client, query):
    assert_unified_error(
        client.get(f"/api/v1/jobs?{query}"), status=400, code="VALIDATION_ERROR"
    )


@pytest.mark.parametrize("query", ["status=bogus", "job_type=bogus"])
def test_job_list_rejects_invalid_enum_filters(client, query):
    assert_unified_error(
        client.get(f"/api/v1/jobs?{query}"), status=400, code="VALIDATION_ERROR"
    )


# --------------------------------------------------------------------------- #
# Execution results (mock adapter)
# --------------------------------------------------------------------------- #
def test_job_completes_with_mock_marked_result(client, drain):
    video_id = upload_video(client, duration=3.0)
    job_id = start_job(client, video_id).get_json()["job_id"]

    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "completed"
    assert job["stage"] == "done"
    assert job["progress"] == 1.0
    assert job["started_at"] is not None
    assert TIMESTAMP_RE.match(job["finished_at"])
    assert job["error"] is None
    assert "mock" in job["provider"]
    assert "mock" in job["model"]["name"]

    result = job["result"]
    assert result["is_mock"] is True
    assert result["prediction_source"] == "mock"
    assert result["segment_count"] == len(result["segments"]) == 3

    legal_labels = {label.value for label in SceneLabel}
    for segment in result["segments"]:
        assert segment["scene_label"] in legal_labels
        assert 0.0 <= segment["confidence"] <= 1.0
        assert 0.0 <= segment["start_s"] < segment["end_s"] <= 3.0


def test_completed_job_updates_video_consistently(client, drain):
    video_id = upload_video(client, duration=3.0)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    video = client.get(f"/api/v1/videos/{video_id}").get_json()

    assert video["status"] == "processed"
    assert video["prediction_source"] == "mock"
    assert video["provider"] == job["provider"]
    assert video["model"] == job["model"]
    assert video["segments"] == job["result"]["segments"]
    assert video["metadata"]["analysis"]["job_id"] == job_id
    assert video["metadata"]["analysis"]["is_mock"] is True
    # P0-2 metadata survives the analysis.
    assert video["metadata"]["sha256"]


def test_mock_result_is_never_evaluation_eligible(client, drain):
    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    video = client.get(f"/api/v1/videos/{video_id}").get_json()

    assert job["result"]["prediction_source"] == "mock"
    assert video["prediction_source"] == "mock"
    assert video["evaluation_eligible"] is False
    assert video["evaluation_eligible"] is not True


def test_job_fails_when_duration_is_unknown(client, drain):
    video_id = upload_video_without_duration(client)
    job_id = start_job(client, video_id).get_json()["job_id"]

    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"]["code"] == "VLM_UPSTREAM_ERROR"
    assert job["error"]["retryable"] is True
    assert job["error"]["message"]

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"
    assert video["segments"] == []
    assert video["prediction_source"] == "none"


def test_job_missing_video_file_fails_cleanly(client, drain, config):
    video_id = upload_video(client)
    (Path(config.videos_dir) / f"{video_id}.mp4").unlink()
    job_id = start_job(client, video_id).get_json()["job_id"]

    drain()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VIDEO_FILE_MISSING"


def test_job_progress_is_always_within_range(client, drain):
    video_id = upload_video(client)
    start_job(client, video_id)
    queued = client.get("/api/v1/jobs").get_json()["items"][0]
    assert queued["progress"] == 0.0

    drain()

    for job in client.get("/api/v1/jobs").get_json()["items"]:
        assert 0.0 <= job["progress"] <= 1.0
        if job["status"] == "completed":
            assert job["progress"] == 1.0
            assert job["stage"] == "done"


def test_job_payload_does_not_leak_host_paths(client, drain):
    video_id = upload_video(client)
    job_id = start_job(client, video_id).get_json()["job_id"]
    drain()

    response = client.get(f"/api/v1/jobs/{job_id}")

    raw = response.get_data(as_text=True)
    assert "C:\\" not in raw
    assert "/data/" not in raw
    assert "app.db" not in raw


# --------------------------------------------------------------------------- #
# Persistence across restarts
# --------------------------------------------------------------------------- #
def test_completed_job_survives_restart(tmp_path: Path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
    )
    first_app = create_app(config)
    first_client = first_app.test_client()
    video_id = upload_video(first_client)
    job_id = start_job(first_client, video_id).get_json()["job_id"]
    first_app.extensions["job_runner"].run_until_idle()

    second_client = create_app(config).test_client()

    job = second_client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "completed"
    assert job["progress"] == 1.0
    assert job["result"]["prediction_source"] == "mock"

    listing = second_client.get("/api/v1/jobs").get_json()
    assert listing["pagination"]["total"] == 1

    video = second_client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "processed"


def test_restart_fails_interrupted_jobs_instead_of_pretending(tmp_path: Path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
    )
    first_app = create_app(config)
    first_client = first_app.test_client()
    video_id = upload_video(first_client)
    job_id = start_job(first_client, video_id).get_json()["job_id"]
    # Simulate a crash: the job stays queued and is never drained.

    second_client = create_app(config).test_client()

    job = second_client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "JOB_INTERRUPTED"
    assert job["error"]["retryable"] is True

    video = second_client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"
    assert video["segments"] == []
