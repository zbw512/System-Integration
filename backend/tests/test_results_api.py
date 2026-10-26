"""API tests for P0-4: result query and JSON/CSV export.

Everything here drives the real endpoints through Flask's test client and, where
it matters, compares the response with the bytes actually stored in SQLite.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from typing import Any

import pytest

from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from assertions import assert_unified_error
from media_fixtures import make_minimal_mp4
from services.errors import VlmAnalysisError

CSV_COLUMNS = [
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
]

REQUIRED_JSON_FIELDS = {
    "schema_version",
    "video_id",
    "name",
    "status",
    "duration_s",
    "prediction_source",
    "provider",
    "model",
    "evaluation_eligible",
    "segments",
    "metadata",
    # additive, derived from stored data
    "job_id",
    "prompt_version",
    "is_mock",
    "segment_count",
    "exported_at",
}


class _StubAdapter(VlmAdapter):
    """Adapter double returning caller-provided segments (for export tests)."""

    name = "stub"

    def __init__(self, segments: list[dict[str, Any]]):
        self._segments = segments

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "status": "stub"}

    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        return AnalysisOutput(
            prediction_source="mock",
            provider="mock_vlm",
            model={
                "name": "mock-vlm",
                "version": "0.1.0-mock",
                "prompt_version": "mock-scene-v1",
            },
            segments=self._segments,
            metadata={"is_mock": True},
        )


def upload_video(client, *, name: str = "clip.mp4", duration: float = 3.0) -> str:
    data = {"file": (io.BytesIO(make_minimal_mp4(duration)), name)}
    response = client.post(
        "/api/v1/videos/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def analyze_video(client, **kwargs) -> tuple[str, str]:
    """Upload -> create job -> run the queue to completion (worker is off in tests)."""
    video_id = upload_video(client, **kwargs)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    client.application.extensions["job_runner"].run_until_idle()
    return video_id, job_id


def read_csv(response) -> list[list[str]]:
    assert response.data.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM"
    text = response.data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline="")))


# --------------------------------------------------------------------------- #
# JSON result
# --------------------------------------------------------------------------- #
def test_json_result_for_completed_mock_job(client, drain):
    video_id, job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format=json")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert REQUIRED_JSON_FIELDS <= set(body), sorted(REQUIRED_JSON_FIELDS - set(body))
    assert body["schema_version"] == "1.0"
    assert body["video_id"] == video_id
    assert body["name"] == "clip.mp4"
    assert body["status"] == "processed"
    assert body["duration_s"] == 3.0
    assert body["segment_count"] == len(body["segments"]) == 3
    assert body["job_id"] == job_id
    assert body["prompt_version"] == "mock-scene-v1"


def test_json_segments_match_database(client, drain, config):
    video_id, _job_id = analyze_video(client)

    body = client.get(f"/api/v1/videos/{video_id}/results").get_json()

    connection = sqlite3.connect(f"file:{config.database_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT segments_json FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    stored_segments = json.loads(row[0])
    assert body["segments"] == stored_segments
    assert len(stored_segments) == 3


def test_json_reports_mock_source_and_not_evaluation_eligible(client, drain):
    video_id, _job_id = analyze_video(client)

    body = client.get(f"/api/v1/videos/{video_id}/results").get_json()

    assert body["prediction_source"] == "mock"
    assert body["provider"] == "mock_vlm"
    assert body["model"]["name"] == "mock-vlm"
    assert body["model"]["version"] == "0.1.0-mock"
    assert body["evaluation_eligible"] is False
    assert body["is_mock"] is True


def test_default_format_is_json(client, drain):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results")

    assert response.status_code == 200
    assert response.mimetype == "application/json"


@pytest.mark.parametrize("fmt", ["JSON", "Csv"])
def test_format_is_case_insensitive(client, drain, fmt):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format={fmt}")

    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
def test_csv_has_header_and_one_row_per_segment(client, drain):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format=csv")

    assert response.status_code == 200
    rows = read_csv(response)
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 1 + 3

    for index, row in enumerate(rows[1:]):
        assert row[0] == video_id
        assert row[1] == "clip.mp4"
        assert row[2] == str(index)
        assert row[9] == "mock"
        assert row[10] == "mock_vlm"
        assert row[11] == "mock-vlm"
        assert row[12] == "0.1.0-mock"
        assert row[13] == "mock-scene-v1"
        assert row[14] == "false"


def test_csv_sets_download_headers(client, drain):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format=csv")

    assert response.headers["Content-Type"].startswith("text/csv")
    assert "charset=utf-8" in response.headers["Content-Type"]
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="results_{video_id}.csv"'
    )


def test_csv_escapes_chinese_commas_quotes_and_newlines(client, drain):
    evidence = '教师转身，学生开始"讨论"\n第二行内容, 含逗号'
    segment = {
        "index": 0,
        "start_s": 0.0,
        "end_s": 3.0,
        "scene_label": "小组讨论",
        "confidence": 0.812,
        "evidence": evidence,
        "is_uncertain": False,
    }
    client.application.extensions["vlm_adapter"] = _StubAdapter([segment])

    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format=csv")
    rows = read_csv(response)

    assert len(rows) == 2
    row = rows[1]
    assert row[5] == "小组讨论"
    assert row[7] == evidence  # quoting round-trips the raw value exactly
    assert row[6] == "0.812"
    assert row[8] == "false"


def test_csv_and_json_core_fields_agree(client, drain):
    video_id, _job_id = analyze_video(client)

    payload = client.get(f"/api/v1/videos/{video_id}/results?format=json").get_json()
    rows = read_csv(client.get(f"/api/v1/videos/{video_id}/results?format=csv"))

    assert len(rows) - 1 == len(payload["segments"])
    for segment, row in zip(payload["segments"], rows[1:]):
        assert row[2] == str(segment["index"])
        assert float(row[3]) == float(segment["start_s"])
        assert float(row[4]) == float(segment["end_s"])
        assert row[5] == segment["scene_label"]
        assert float(row[6]) == float(segment["confidence"])
        assert row[7] == segment["evidence"]
        assert row[8] == ("true" if segment["is_uncertain"] else "false")


def test_csv_contains_no_fake_row_for_empty_segments(client, drain):
    client.application.extensions["vlm_adapter"] = _StubAdapter([])

    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format=csv")
    rows = read_csv(response)

    assert rows == [CSV_COLUMNS], "没有分段时必须只返回表头"

    payload = client.get(f"/api/v1/videos/{video_id}/results?format=json").get_json()
    assert payload["segments"] == []
    assert payload["segment_count"] == 0
    assert payload["status"] == "processed"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_unknown_video_returns_unified_404(client):
    for fmt in ("json", "csv"):
        response = client.get(f"/api/v1/videos/vid_missing/results?format={fmt}")
        error = assert_unified_error(response, status=404, code="VIDEO_NOT_FOUND")
        assert error["details"]["video_id"] == "vid_missing"


@pytest.mark.parametrize("fmt", ["xml", "yaml", "pdf", "JSONL"])
def test_invalid_format_returns_unified_400(client, drain, fmt):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format={fmt}")

    error = assert_unified_error(response, status=400, code="VALIDATION_ERROR")
    assert error["details"]["field"] == "format"
    assert error["details"]["allowed"] == ["json", "csv"]


def test_unanalysed_video_is_not_reported_as_success(client):
    video_id = upload_video(client)

    for fmt in ("json", "csv"):
        response = client.get(f"/api/v1/videos/{video_id}/results?format={fmt}")
        error = assert_unified_error(
            response, status=409, code="VIDEO_NOT_PROCESSED"
        )
        assert error["details"]["video_id"] == video_id
        assert error["details"]["status"] == "registered"


def test_processing_video_returns_conflict_with_job_context(client):
    video_id = upload_video(client)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    # Deliberately not drained: the video stays `processing`.

    error = assert_unified_error(
        client.get(f"/api/v1/videos/{video_id}/results"),
        status=409,
        code="VIDEO_NOT_PROCESSED",
    )

    assert error["details"]["status"] == "processing"
    assert error["details"]["job"]["job_id"] == job_id
    assert error["details"]["job"]["status"] == "queued"
    assert error["details"]["job"]["progress"] == 0.0


def test_failed_video_returns_conflict_with_job_error(client, drain):
    client.application.extensions["vlm_adapter"] = _StubAdapter([])
    client.application.extensions["vlm_adapter"].analyze = lambda request: (_ for _ in ()).throw(
        VlmAnalysisError("适配器故障")
    )

    video_id = upload_video(client)
    client.post(f"/api/v1/videos/{video_id}/process")
    drain()

    error = assert_unified_error(
        client.get(f"/api/v1/videos/{video_id}/results"),
        status=409,
        code="VIDEO_NOT_PROCESSED",
    )

    assert error["details"]["status"] == "failed"
    assert error["details"]["job"]["status"] == "failed"
    assert error["details"]["job"]["error"]["code"] == "VLM_UPSTREAM_ERROR"
    assert error["details"]["job"]["error"]["retryable"] is True


def test_unknown_video_and_unprocessed_video_use_different_codes(client):
    missing = client.get("/api/v1/videos/vid_missing/results?format=csv")
    video_id = upload_video(client)
    exists = client.get(f"/api/v1/videos/{video_id}/results?format=csv")

    assert missing.status_code == 404
    assert exists.status_code == 409
    assert missing.get_json()["error"]["code"] == "VIDEO_NOT_FOUND"
    assert exists.get_json()["error"]["code"] == "VIDEO_NOT_PROCESSED"


# --------------------------------------------------------------------------- #
# Side effects & leaks
# --------------------------------------------------------------------------- #
def test_export_does_not_create_analysis_jobs(client, drain):
    video_id, job_id = analyze_video(client)
    before = client.get("/api/v1/jobs").get_json()["pagination"]["total"]

    client.get(f"/api/v1/videos/{video_id}/results?format=json")
    client.get(f"/api/v1/videos/{video_id}/results?format=csv")
    client.get(f"/api/v1/videos/{video_id}/results?format=json")

    after = client.get("/api/v1/jobs").get_json()["pagination"]["total"]
    assert after == before == 1

    jobs = client.get("/api/v1/jobs").get_json()["items"]
    assert [job["job_id"] for job in jobs] == [job_id]
    assert jobs[0]["status"] == "completed"

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "processed"


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_export_does_not_leak_host_paths(client, drain, fmt):
    video_id, _job_id = analyze_video(client)

    response = client.get(f"/api/v1/videos/{video_id}/results?format={fmt}")
    raw = response.data.decode("utf-8-sig")

    assert "C:\\" not in raw
    assert "app.db" not in raw
    assert "smoke" not in raw
