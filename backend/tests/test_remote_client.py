from __future__ import annotations

import io
import json
import urllib.error

import pytest

import adapters.vlm.remote_client as client_module
from adapters.vlm.remote_client import RemoteVlmClient
from config import Config
from services.errors import (
    VlmRemoteAuthFailedError,
    VlmRemoteConfigurationError,
    VlmRemoteUnavailableError,
    VlmResultInvalidError,
)

TOKEN = "remote-test-token-0123456789abcdef"


def make_config(**overrides) -> Config:
    values = {
        "vlm_adapter": "minicpm_remote",
        "vlm_remote_url": "http://127.0.0.1:18080",
        "vlm_remote_token": TOKEN,
        "vlm_remote_timeout_s": 3.0,
        "vlm_remote_retries": 2,
    }
    values.update(overrides)
    return Config(**values)


def response_payload(request) -> dict:
    payload = json.loads(request.data.decode("utf-8"))
    return {
        "request_id": payload["request_id"],
        "window_id": payload["window_id"],
        "raw_prediction": "听讲",
        "predicted_label": "听讲",
        "is_uncertain": False,
        "parse_status": "parsed",
        "model": {
            "name": "MiniCPM-V",
            "version": "4.5",
            "finetune": "scene4",
            "checkpoint": "checkpoint-600",
            "prompt_version": "scene4-label-v1",
        },
        "frame_count": len(payload["frames"]),
        "inference_ms": 12.5,
    }


class FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self._body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )

    def read(self, size: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def call_client(client: RemoteVlmClient):
    return client.predict_window(
        request_id="job1-w0000",
        window_id="vid1-w0000",
        window_start_s=0.0,
        window_end_s=3.0,
        frames=[
            {
                "timestamp_s": 0.0,
                "mime_type": "image/png",
                "image_base64": "iVBORw0KGgo=",
            }
        ],
    )


def test_successful_response_is_validated(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["auth"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["timeout"] = timeout
        return FakeResponse(response_payload(request))

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)
    prediction = call_client(RemoteVlmClient(make_config()))

    assert prediction.raw_prediction == "听讲"
    assert prediction.frame_count == 1
    assert captured["auth"] == f"Bearer {TOKEN}"
    assert captured["content_type"] == "application/json; charset=utf-8"
    assert captured["timeout"] == 3.0


def test_missing_token_is_a_configuration_failure() -> None:
    with pytest.raises(VlmRemoteConfigurationError):
        call_client(
            RemoteVlmClient(
                make_config(vlm_remote_token=None)
            )
        )


def test_retryable_503_then_success(monkeypatch) -> None:
    calls = {"count": 0}
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"error":{"code":"VLM_MODEL_LOAD_FAILED"}}'),
            )
        return FakeResponse(response_payload(request))

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)
    prediction = call_client(RemoteVlmClient(make_config()))
    assert prediction.raw_prediction == "听讲"
    assert calls["count"] == 2


def test_unauthorized_is_not_retried(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"code":"VLM_UNAUTHORIZED"}}'),
        )

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(VlmRemoteAuthFailedError) as excinfo:
        call_client(RemoteVlmClient(make_config()))

    assert calls["count"] == 1
    assert excinfo.value.details["service_code"] == "VLM_UNAUTHORIZED"


def test_network_failure_retries_then_reports_unavailable(monkeypatch) -> None:
    calls = {"count": 0}
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.URLError("tunnel closed")

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(VlmRemoteUnavailableError) as excinfo:
        call_client(RemoteVlmClient(make_config()))

    assert calls["count"] == 3
    assert excinfo.value.details["attempts"] == 3
    assert "Bearer" not in str(excinfo.value.details)
    assert TOKEN not in json.dumps(excinfo.value.details, ensure_ascii=False)


def test_wrong_remote_model_version_is_rejected(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        body = response_payload(request)
        body["model"]["version"] = "4.6"
        return FakeResponse(body)

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(VlmResultInvalidError) as excinfo:
        call_client(RemoteVlmClient(make_config()))
    assert excinfo.value.details["reason"] == "unexpected_model_version"
