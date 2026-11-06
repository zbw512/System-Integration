from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cloud_vlm_service.app import create_app
from cloud_vlm_service.errors import InferenceError
from cloud_vlm_service.runtime import InferenceResult


class FakeRuntime:
    def __init__(self, raw_prediction: str = "小组讨论") -> None:
        self.raw_prediction = raw_prediction
        self.calls: list[list[object]] = []

    @property
    def model_info(self) -> dict[str, str]:
        return {
            "name": "MiniCPM-V",
            "version": "4.5",
            "finetune": "scene4",
            "checkpoint": "checkpoint-600",
            "prompt_version": "scene4-label-v1",
        }

    def load(self) -> None:
        return None

    def health_snapshot(self) -> dict:
        return {
            "status": "ok",
            "loaded": True,
            "model": self.model_info,
            "device": "cuda",
            "cuda_available": True,
            "gpu_name": "Fake GPU",
            "base_model_present": True,
            "adapter_present": True,
            "max_frames": 8,
            "load_error": None,
        }

    def predict_window(self, frames):
        self.calls.append(list(frames))
        return InferenceResult(
            raw_prediction=self.raw_prediction,
            frame_count=len(frames),
            inference_ms=12.5,
        )


@pytest.fixture()
def fake_runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture()
def client(settings, fake_runtime):
    app = create_app(settings, runtime=fake_runtime)
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_model_versions(client, auth_headers) -> None:
    response = client.get("/health", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["loaded"] is True
    assert body["model"]["version"] == "4.5"
    assert body["model"]["checkpoint"] == "checkpoint-600"
    assert body["model"]["prompt_version"] == "scene4-label-v1"


def test_health_requires_token(client) -> None:
    response = client.get("/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "VLM_UNAUTHORIZED"


def test_wrong_token_is_rejected(client) -> None:
    response = client.get(
        "/health",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_predict_window_returns_raw_and_parsed(
    client,
    auth_headers,
    valid_request,
    fake_runtime,
) -> None:
    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["raw_prediction"] == "小组讨论"
    assert body["predicted_label"] == "小组讨论"
    assert body["is_uncertain"] is False
    assert body["parse_status"] == "parsed"
    assert body["frame_count"] == 8
    assert body["model"]["version"] == "4.5"
    assert len(fake_runtime.calls) == 1
    assert len(fake_runtime.calls[0]) == 8


def test_unparseable_prediction_is_unclassified(
    client,
    auth_headers,
    valid_request,
) -> None:
    app = client.app
    app.state.runtime.raw_prediction = "unknown"

    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )

    assert response.status_code == 200
    assert response.json()["predicted_label"] == "未分类"
    assert response.json()["is_uncertain"] is True
    assert response.json()["parse_status"] == "unparseable"


def test_more_than_eight_frames_is_rejected(
    client,
    auth_headers,
    valid_request,
    png_base64,
) -> None:
    valid_request["frames"].append(
        {
            "timestamp_s": 3.2,
            "mime_type": "image/png",
            "image_base64": png_base64,
        }
    )
    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )
    assert response.status_code == 422


def test_wrong_prompt_version_is_rejected(
    client,
    auth_headers,
    valid_request,
) -> None:
    valid_request["prompt_version"] = "not-scene4"
    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VLM_PROMPT_VERSION_UNSUPPORTED"


def test_jpeg_is_rejected(
    client,
    auth_headers,
    valid_request,
) -> None:
    output = io.BytesIO()
    Image.new("RGB", (8, 8)).save(output, format="JPEG")
    valid_request["frames"][0]["image_base64"] = base64.b64encode(
        output.getvalue()
    ).decode("ascii")

    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VLM_INVALID_FRAME"


def test_inference_error_is_not_replaced_by_mock(
    client,
    auth_headers,
    valid_request,
) -> None:
    def fail(_frames):
        raise InferenceError("CUDA out of memory")

    client.app.state.runtime.predict_window = fail
    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "VLM_INFERENCE_FAILED"
    assert "听讲" not in response.text


def test_unknown_fields_are_rejected(
    client,
    auth_headers,
    valid_request,
) -> None:
    valid_request["temperature"] = 0
    response = client.post(
        "/predict_window",
        headers=auth_headers,
        json=valid_request,
    )
    assert response.status_code == 422
