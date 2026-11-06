"""Real loopback HTTP tests against the deterministic Mock AutoDL server."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.vlm.remote_client import RemoteVlmClient
from adapters.vlm.scene4 import parse_scene4_prediction
from cloud_vlm_service.mock_server import create_server, run_server
from config import Config
from services.errors import (
    VlmRemoteAuthFailedError,
    VlmRemoteUnavailableError,
)

TOKEN = "mock-service-token-0123456789abcdef"


@pytest.fixture()
def server_factory():
    servers = []

    def make(**kwargs):
        server = create_server(
            host="127.0.0.1",
            port=0,
            token=TOKEN,
            **kwargs,
        )
        ready = threading.Event()
        thread = run_server(server, ready_event=ready)
        assert ready.wait(2)
        servers.append((server, thread))
        return server

    yield make
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def client_for(server, **overrides) -> RemoteVlmClient:
    values = {
        "vlm_adapter": "minicpm_remote",
        "vlm_remote_url": f"http://127.0.0.1:{server.server_port}",
        "vlm_remote_token": TOKEN,
        "vlm_remote_timeout_s": 2.0,
        "vlm_remote_retries": 0,
    }
    values.update(overrides)
    return RemoteVlmClient(Config(**values))


def predict(client: RemoteVlmClient):
    return client.predict_window(
        request_id="job-mock-w0000",
        window_id="video-mock-w0000",
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


def test_mock_service_returns_expected_contract(server_factory) -> None:
    server = server_factory(label="独立学习")
    prediction = predict(client_for(server))
    assert prediction.raw_prediction == "独立学习"
    assert prediction.frame_count == 1
    assert prediction.model["checkpoint"] == "checkpoint-600"


def test_mock_service_token_error(server_factory) -> None:
    server = server_factory()
    client = client_for(
        server,
        vlm_remote_token="x" * 32,
    )
    with pytest.raises(VlmRemoteAuthFailedError):
        predict(client)


def test_mock_service_unparseable_output(server_factory) -> None:
    server = server_factory(failure_mode="unparseable")
    prediction = predict(client_for(server))
    parsed = parse_scene4_prediction(prediction.raw_prediction)
    assert parsed.label == "未分类"
    assert parsed.is_uncertain is True


def test_mock_service_delay_causes_timeout(server_factory) -> None:
    server = server_factory(delay_s=0.5)
    client = client_for(server, vlm_remote_timeout_s=0.05)
    with pytest.raises(VlmRemoteUnavailableError):
        predict(client)
