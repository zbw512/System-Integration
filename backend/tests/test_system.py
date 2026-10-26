"""Tests for the P0-1 HTTP shell and the unified error contract.

Covered:

* ``GET /health`` and ``GET /api/v1/info`` success payloads;
* unified 404 / 405 error responses;
* :class:`api.errors.ApiError` handling and the unexpected-exception path
  (must not leak the exception text, a stack trace or a filesystem path);
* ``X-Request-Id`` propagation;
* the prediction-source / evaluation eligibility rule (standard section 2.2).
"""

from __future__ import annotations

import pytest
from flask import Flask

from api.errors import ApiError
from assertions import (
    GENERATED_REQUEST_ID_RE,
    TIMESTAMP_RE,
    assert_unified_error,
)
from schemas.enums import (
    EVALUATION_ELIGIBLE_SOURCES,
    PredictionSource,
    enum_values,
    is_evaluation_eligible,
)


# --------------------------------------------------------------------------- #
# Success endpoints
# --------------------------------------------------------------------------- #
def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "1.0"
    assert body["service"]["name"] == "learning-state-backend"
    assert body["service"]["version"] == "0.5.0"
    assert TIMESTAMP_RE.match(body["time"])
    assert isinstance(body["uptime_s"], (int, float)) and body["uptime_s"] >= 0
    assert set(body["checks"]) == {"http", "storage", "vlm_adapter", "eeg_adapter"}
    assert body["checks"]["http"] == "ok"
    assert body["request_id"]


def test_health_reports_component_status_honestly(client):
    checks = client.get("/health").get_json()["checks"]

    # Storage exists since P0-2; the VLM and EEG adapters still do not.
    assert checks["storage"] == "ok"
    assert checks["vlm_adapter"] == "not_implemented"
    assert checks["eeg_adapter"] == "not_implemented"


def test_info_returns_contract(client):
    response = client.get("/api/v1/info")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert body["schema_version"] == "1.0"
    assert body["api"]["prefix"] == "/api/v1"
    assert body["api"]["version"] == "v1"
    assert body["api"]["time_format"].startswith("RFC3339")
    assert set(body["api"]["list_format"]["pagination"]) == {
        "limit",
        "offset",
        "total",
        "has_next",
    }
    assert body["limits"]["list_default_limit"] == 50
    assert body["limits"]["list_max_limit"] == 500

    endpoints = {(item["method"], item["path"]) for item in body["endpoints"]}
    assert ("GET", "/health") in endpoints
    assert ("GET", "/api/v1/info") in endpoints


def test_info_capabilities_match_implementation(client):
    body = client.get("/api/v1/info").get_json()

    capabilities = body["capabilities"]
    # P0-2 implements upload/registration; P0-3 adds job execution.
    assert capabilities["video_upload"] is True
    assert capabilities["video_registration"] is True
    assert capabilities["job_execution"] is True
    assert capabilities["result_export"] is True

    # No real VLM yet: analysis itself stays false, as does everything that
    # belongs to later phases.
    for name in (
        "video_analysis",
        "evaluation",
        "eeg_ingest",
        "fusion",
        "realtime_stream",
    ):
        assert capabilities[name] is False, name

    vlm = body["adapters"]["vlm"]
    assert vlm["status"] == "mock"
    assert vlm["prediction_source"] == "mock"
    assert "mock" in vlm["provider"]
    assert "mock" in vlm["model"]["name"]
    assert vlm["evaluation_eligible"] is False
    assert body["adapters"]["eeg"]["status"] == "not_implemented"
    assert body["storage"]["engine"] == "sqlite"

    # The published job policy must match the implementation.
    assert body["job_policy"]["cancel_supported"] is False
    assert body["job_policy"]["concurrency"] == 1


def test_info_publishes_standard_enums(client):
    enums = client.get("/api/v1/info").get_json()["enums"]

    assert enums["prediction_source"] == ["model", "oracle", "mock", "manual", "none"]
    assert enums["video_status"] == ["registered", "processing", "processed", "failed"]
    assert enums["video_source"] == ["upload", "sav_clip", "local_path"]
    assert enums["job_status"] == ["queued", "running", "completed", "failed", "canceled"]
    assert enums["job_stage"] == [
        "queued",
        "loading_video",
        "sampling_frames",
        "inference",
        "parsing",
        "saving",
        "done",
    ]
    assert enums["job_type"] == ["video_process", "evaluation", "fusion", "export"]
    assert enums["scene_label"] == ["听讲", "小组讨论", "独立学习", "其他", "未分类"]


def test_json_responses_declare_utf8_charset(client):
    """An explicit charset stops legacy clients decoding Chinese as Latin-1.

    The mimetype itself must stay ``application/json`` for compatibility with
    the standard and with normal JSON parsers.
    """
    for path in ("/health", "/api/v1/info", "/no-such-page"):
        response = client.get(path)
        assert response.mimetype == "application/json"
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"


# --------------------------------------------------------------------------- #
# Unified error responses
# --------------------------------------------------------------------------- #
def test_unknown_route_returns_unified_404(client):
    response = client.get("/api/v1/does-not-exist")
    error = assert_unified_error(response, status=404, code="NOT_FOUND")

    assert error["retryable"] is False
    assert error["details"]["path"] == "/api/v1/does-not-exist"


def test_404_is_json_and_not_html(client):
    response = client.get("/no-such-page")

    assert response.status_code == 404
    assert response.mimetype == "application/json"
    assert "<!doctype html>" not in response.get_data(as_text=True).lower()


def test_near_miss_health_path_is_404(client):
    response = client.get("/healthz")
    assert_unified_error(response, status=404, code="NOT_FOUND")


def test_method_not_allowed_is_unified(client):
    response = client.post("/health")
    error = assert_unified_error(response, status=405, code="METHOD_NOT_ALLOWED")

    assert "GET" in response.headers.get("Allow", "")
    assert "GET" in error["details"]["allowed_methods"]


def test_api_error_fields_are_preserved(app: Flask):
    @app.route("/_test/api-error")
    def _raise_api_error():
        raise ApiError(
            "VIDEO_NOT_FOUND",
            "视频不存在",
            status=404,
            details={"resource": "video", "video_id": "sav_test"},
            retryable=False,
        )

    response = app.test_client().get("/_test/api-error")
    error = assert_unified_error(response, status=404, code="VIDEO_NOT_FOUND")

    assert error["message"] == "视频不存在"
    assert error["details"] == {"resource": "video", "video_id": "sav_test"}
    assert error["retryable"] is False


def test_api_error_rejects_invalid_code():
    with pytest.raises(ValueError):
        ApiError("invalid code", "错误的错误码")


def test_unexpected_exception_is_unified_and_does_not_leak(app: Flask):
    @app.route("/_test/boom")
    def _boom():
        raise RuntimeError("secret detail C:\\Users\\someone")

    response = app.test_client().get("/_test/boom")
    error = assert_unified_error(response, status=500, code="INTERNAL_ERROR")

    assert error["retryable"] is True
    raw = response.get_data(as_text=True)
    assert "secret detail" not in raw


# --------------------------------------------------------------------------- #
# Request id correlation
# --------------------------------------------------------------------------- #
def test_generated_request_id_is_returned(client):
    response = client.get("/health")
    request_id = response.headers["X-Request-Id"]

    assert GENERATED_REQUEST_ID_RE.match(request_id)
    assert response.get_json()["request_id"] == request_id


def test_caller_request_id_is_echoed(client):
    request_id = "abcdef123456"
    response = client.get("/health", headers={"X-Request-Id": request_id})

    assert response.headers["X-Request-Id"] == request_id
    assert response.get_json()["request_id"] == request_id


def test_malformed_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-Id": "../etc/passwd"})
    request_id = response.headers["X-Request-Id"]

    assert request_id != "../etc/passwd"
    assert GENERATED_REQUEST_ID_RE.match(request_id)


def test_error_response_carries_request_id(client):
    request_id = "trace0001ab"
    response = client.get("/missing-resource", headers={"X-Request-Id": request_id})
    error = assert_unified_error(response, status=404, code="NOT_FOUND")

    assert error["request_id"] == request_id
    assert response.headers["X-Request-Id"] == request_id


# --------------------------------------------------------------------------- #
# Prediction source / evaluation eligibility (standard section 2.2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source", ["model"])
def test_model_prediction_is_evaluation_eligible(source):
    assert is_evaluation_eligible(source) is True


@pytest.mark.parametrize(
    "source", ["oracle", "mock", "manual", "none", "minicpm_v", "", None]
)
def test_non_model_predictions_are_not_evaluation_eligible(source):
    assert is_evaluation_eligible(source) is False


def test_eligibility_set_matches_standard():
    assert EVALUATION_ELIGIBLE_SOURCES == frozenset({PredictionSource.MODEL})


def test_provider_is_not_a_prediction_source():
    # ``minicpm_v`` is a provider, never a prediction_source value.
    assert "minicpm_v" not in enum_values(PredictionSource)
