"""Full Flask API/Job/SQLite/export integration with a fake AutoDL client."""

from __future__ import annotations

import io
from pathlib import Path

from app import create_app
from config import Config
from adapters.vlm.minicpm_remote import MiniCPMV45RemoteAdapter
from adapters.vlm.remote_client import RemotePrediction
from services.errors import VlmRemoteUnavailableError
from video_fixtures import write_test_video

TOKEN = "integration-remote-token-0123456789"


class FakeRemoteClient:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls = 0

    def predict_window(self, **kwargs) -> RemotePrediction:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return RemotePrediction(
            raw_prediction=answer,
            remote_predicted_label=(
                answer
                if answer in {"听讲", "小组讨论", "独立学习", "其他"}
                else "未分类"
            ),
            parse_status="parsed",
            model={
                "name": "MiniCPM-V",
                "version": "4.5",
                "finetune": "scene4",
                "checkpoint": "checkpoint-600",
                "prompt_version": "scene4-label-v1",
            },
            frame_count=len(kwargs["frames"]),
            inference_ms=10.0,
            request_id=kwargs["request_id"],
            window_id=kwargs["window_id"],
        )


class BrokenRemoteClient:
    def predict_window(self, **kwargs) -> RemotePrediction:
        raise VlmRemoteUnavailableError(details={"reason": "tunnel_closed"})


def make_config(tmp_path: Path) -> Config:
    return Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
        vlm_adapter="minicpm_remote",
        vlm_remote_url="http://127.0.0.1:18080",
        vlm_remote_token=TOKEN,
        vlm_remote_retries=0,
        vlm_max_frames=8,
        vlm_window_seconds=3.0,
        vlm_window_stride_seconds=3.0,
        vlm_max_duration_s=60.0,
    )


def upload_real_video(client, tmp_path: Path) -> str:
    video = write_test_video(tmp_path / "six.mp4", seconds=6.0, fps=2)
    video_bytes = video.read_bytes()
    response = client.post(
        "/api/v1/videos/upload",
        data={"file": (io.BytesIO(video_bytes), "six.mp4")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def test_full_job_uses_remote_model_and_preserves_exports(tmp_path: Path) -> None:
    app = create_app(make_config(tmp_path))
    adapter = app.extensions["vlm_adapter"]
    assert isinstance(adapter, MiniCPMV45RemoteAdapter)
    fake_client = FakeRemoteClient(["听讲", "小组讨论"])
    adapter._client = fake_client

    client = app.test_client()
    info = client.get("/api/v1/info").get_json()
    assert info["adapters"]["vlm"]["name"] == "minicpm_remote"
    assert info["adapters"]["vlm"]["model"]["version"] == "4.5"
    assert info["adapters"]["vlm"]["model"]["checkpoint"] == "checkpoint-600"
    assert (
        client.get("/health").get_json()["checks"]["vlm_adapter"]
        == "configured"
    )

    video_id = upload_real_video(client, tmp_path)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    app.extensions["job_runner"].run_until_idle()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "completed"
    assert job["provider"] == "minicpm_v"
    assert job["model"]["version"] == "4.5"
    assert job["model"]["checkpoint"] == "checkpoint-600"
    assert job["result"]["prediction_source"] == "model"
    assert job["result"]["is_mock"] is False
    assert job["result"]["segment_count"] == 2
    assert fake_client.calls == 2

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "processed"
    assert video["prediction_source"] == "model"
    assert video["evaluation_eligible"] is True
    assert [item["scene_label"] for item in video["segments"]] == [
        "听讲",
        "小组讨论",
    ]

    exported = client.get(
        f"/api/v1/videos/{video_id}/results?format=json"
    ).get_json()
    assert exported["model"]["version"] == "4.5"
    assert exported["is_mock"] is False

    csv_text = client.get(
        f"/api/v1/videos/{video_id}/results?format=csv"
    ).data.decode("utf-8-sig")
    assert "minicpm_v" in csv_text
    assert "mock" not in csv_text
    assert "听讲" in csv_text
    assert "小组讨论" in csv_text


def test_remote_failure_fails_job_without_mock_fallback(tmp_path: Path) -> None:
    app = create_app(make_config(tmp_path))
    adapter = app.extensions["vlm_adapter"]
    adapter._client = BrokenRemoteClient()

    client = app.test_client()
    video_id = upload_real_video(client, tmp_path)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    app.extensions["job_runner"].run_until_idle()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VLM_REMOTE_UNAVAILABLE"
    assert job["error"]["retryable"] is True
    assert job["result"] is None

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"
    assert video["segments"] == []
    assert video["prediction_source"] == "none"
    assert video["evaluation_eligible"] is False

    raw = str(job).lower()
    assert "mock" not in raw
