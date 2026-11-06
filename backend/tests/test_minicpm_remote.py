"""MiniCPM-V 4.5 AutoDL adapter tests without a GPU or network."""

from __future__ import annotations

import pytest
from PIL import Image

import adapters.vlm.minicpm_remote as remote_module
from adapters.vlm.base import AnalysisRequest
from adapters.vlm.minicpm_remote import MiniCPMV45RemoteAdapter
from adapters.vlm.remote_client import RemotePrediction
from adapters.vlm.window_frames import DecodedWindow, WindowDecodeResult, WindowFrame
from config import Config
from services.errors import VlmRemoteUnavailableError

TOKEN = "remote-adapter-token-0123456789abcdef"


def make_config(**overrides) -> Config:
    values = {
        "vlm_adapter": "minicpm_remote",
        "vlm_remote_url": "http://127.0.0.1:18080",
        "vlm_remote_token": TOKEN,
        "vlm_max_frames": 8,
        "vlm_window_seconds": 3.0,
        "vlm_window_stride_seconds": 3.0,
        "vlm_max_duration_s": 60.0,
    }
    values.update(overrides)
    return Config(**values)


class FakeClient:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls: list[dict] = []

    def predict_window(self, **kwargs) -> RemotePrediction:
        self.calls.append(kwargs)
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        return RemotePrediction(
            raw_prediction=answer,
            remote_predicted_label=answer if answer in {
                "听讲",
                "小组讨论",
                "独立学习",
                "其他",
            } else "未分类",
            parse_status="parsed",
            model=MiniCPMV45RemoteAdapter(make_config()).model_info,
            frame_count=len(kwargs["frames"]),
            inference_ms=10.0,
            request_id=kwargs["request_id"],
            window_id=kwargs["window_id"],
        )


def decoded_two_windows() -> WindowDecodeResult:
    def frames(start: float) -> tuple[WindowFrame, ...]:
        return tuple(
            WindowFrame(
                timestamp_s=start + index * 0.3,
                image=Image.new("RGB", (8, 6), (index, 20, 30)),
            )
            for index in range(8)
        )

    return WindowDecodeResult(
        windows=(
            DecodedWindow(index=0, start_s=0.0, end_s=3.0, frames=frames(0.0)),
            DecodedWindow(index=1, start_s=3.0, end_s=6.0, frames=frames(3.0)),
        ),
        duration_s=6.0,
        fps=20.0,
        width=8,
        height=6,
        policy_id="provisional-3s-window-3s-stride-tail-v1",
    )


def request() -> AnalysisRequest:
    return AnalysisRequest(
        job_id="job1",
        video_id="vid1",
        video_path="unused.mp4",
        duration_s=6.0,
    )


def test_remote_adapter_keeps_one_segment_per_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        remote_module,
        "decode_video_windows",
        lambda *args, **kwargs: decoded_two_windows(),
    )
    client = FakeClient(["听讲", "听讲"])
    adapter = MiniCPMV45RemoteAdapter(make_config(), client=client)

    output = adapter.analyze(request())

    assert output.prediction_source == "model"
    assert output.provider == "minicpm_v"
    assert output.model["version"] == "4.5"
    assert output.model["checkpoint"] == "checkpoint-600"
    assert output.metadata["is_mock"] is False
    assert output.metadata["window_count"] == 2
    assert len(output.segments) == 2
    assert [(item["start_s"], item["end_s"]) for item in output.segments] == [
        (0.0, 3.0),
        (3.0, 6.0),
    ]
    assert len(client.calls) == 2
    assert all(len(call["frames"]) == 8 for call in client.calls)
    assert all(
        frame["mime_type"] == "image/png" for call in client.calls for frame in call["frames"]
    )


def test_unparseable_output_is_normal_unclassified_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        remote_module,
        "decode_video_windows",
        lambda *args, **kwargs: decoded_two_windows(),
    )
    adapter = MiniCPMV45RemoteAdapter(
        make_config(),
        client=FakeClient(["模型无法判断", "???"]),
    )

    output = adapter.analyze(request())

    assert len(output.segments) == 2
    assert all(item["scene_label"] == "未分类" for item in output.segments)
    assert all(item["is_uncertain"] is True for item in output.segments)
    assert all(item["confidence"] is None for item in output.segments)


def test_infrastructure_failure_aborts_job_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        remote_module,
        "decode_video_windows",
        lambda *args, **kwargs: decoded_two_windows(),
    )

    class BrokenClient:
        def predict_window(self, **kwargs):
            raise VlmRemoteUnavailableError(details={"reason": "tunnel_closed"})

    adapter = MiniCPMV45RemoteAdapter(make_config(), client=BrokenClient())
    with pytest.raises(VlmRemoteUnavailableError):
        adapter.analyze(request())


def test_progress_is_monotonic_for_multiple_windows(monkeypatch) -> None:
    monkeypatch.setattr(
        remote_module,
        "decode_video_windows",
        lambda *args, **kwargs: decoded_two_windows(),
    )
    adapter = MiniCPMV45RemoteAdapter(
        make_config(),
        client=FakeClient(["听讲", "独立学习"]),
    )
    events: list[tuple[str, float]] = []
    req = AnalysisRequest(
        job_id="job1",
        video_id="vid1",
        video_path="unused.mp4",
        duration_s=6.0,
        on_progress=lambda stage, progress: events.append((stage, progress)),
    )

    adapter.analyze(req)

    assert events[0] == ("sampling_frames", 0.2)
    progress = [value for _, value in events]
    assert progress == sorted(progress)
    assert progress[-1] == pytest.approx(0.75)


def test_describe_reports_remote_model_and_provisional_policy() -> None:
    adapter = MiniCPMV45RemoteAdapter(make_config(), client=FakeClient(["听讲"]))
    description = adapter.describe()

    assert description["status"] == "configured"
    assert description["remote"] is True
    assert description["model"]["version"] == "4.5"
    assert description["model"]["checkpoint"] == "checkpoint-600"
    assert description["sampling"]["provisional"] is True
    assert TOKEN not in str(description)
