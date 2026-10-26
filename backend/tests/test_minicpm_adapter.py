"""Adapter selection, failure handling and end-to-end job integration.

**No model is loaded here.** The frame sampler and the generation call are
replaced by doubles, so the full path (config → sampling → parse → segments →
job → video → export) is verified deterministically and fast.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

import adapters.vlm.minicpm as minicpm_module
from adapters.vlm import (
    AnalysisRequest,
    MiniCPMV46Adapter,
    MockVlmAdapter,
    build_vlm_adapter,
)
from adapters.vlm.frames import FrameSamplingResult, SampledFrame
from app import create_app
from config import Config
from media_fixtures import make_minimal_mp4
from services.errors import (
    VideoDecodeError,
    VideoNoFramesError,
    VlmAnalysisError,
    VlmLoadFailedError,
    VlmModelNotFoundError,
)

MODEL_FILES = ("config.json", "model.safetensors")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def build_model_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"\0" * 16)
    return model_dir


def make_config(tmp_path: Path, *, model_dir: Path | None = None, **overrides) -> Config:
    params = dict(
        testing=True,
        log_level="CRITICAL",
        vlm_adapter="minicpm",
        vlm_model_path=str(model_dir if model_dir is not None else build_model_dir(tmp_path)),
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
        vlm_max_frames=3,
        vlm_frame_interval_s=1.0,
        vlm_max_duration_s=60.0,
    )
    params.update(overrides)
    return Config(**params)


def fake_sampling(
    timestamps: tuple[float, ...] = (0.0, 1.0, 2.0), duration_s: float | None = 3.0
) -> FrameSamplingResult:
    return FrameSamplingResult(
        duration_s=duration_s,
        frames=tuple(SampledFrame(timestamp_s=t, image=object()) for t in timestamps),
        fps=18.0,
        width=1280,
        height=720,
    )


def patch_adapter(
    monkeypatch,
    adapter: MiniCPMV46Adapter,
    answers: list[str],
    *,
    timestamps: tuple[float, ...] = (0.0, 1.0, 2.0),
    duration_s: float | None = 3.0,
) -> dict:
    """Replace frame sampling, model loading and generation with doubles."""
    state = {"calls": 0}

    monkeypatch.setattr(
        minicpm_module, "sample_frames", lambda *a, **k: fake_sampling(timestamps, duration_s)
    )
    monkeypatch.setattr(adapter, "_ensure_loaded", lambda: (object(), object(), "cuda"))

    def fake_generate(processor, model, device, image) -> str:
        index = min(state["calls"], len(answers) - 1)
        state["calls"] += 1
        return answers[index]

    monkeypatch.setattr(adapter, "_generate", fake_generate)
    return state


def upload_video(client, *, name: str = "clip.mp4", duration: float = 3.0) -> str:
    data = {"file": (io.BytesIO(make_minimal_mp4(duration)), name)}
    response = client.post(
        "/api/v1/videos/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


# --------------------------------------------------------------------------- #
# Selection & configuration
# --------------------------------------------------------------------------- #
def test_build_adapter_selects_minicpm(tmp_path):
    adapter = build_vlm_adapter(make_config(tmp_path))

    assert isinstance(adapter, MiniCPMV46Adapter)
    assert adapter.name == "minicpm_v"
    assert adapter.provider == "minicpm_v"
    assert adapter.uses_frame_sampling is True


def test_mock_adapter_is_still_available_and_does_not_sample_frames():
    adapter = build_vlm_adapter(Config(vlm_adapter="mock"))

    assert isinstance(adapter, MockVlmAdapter)
    assert adapter.uses_frame_sampling is False


def test_describe_reports_configuration_without_leaking_paths(tmp_path):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))

    description = adapter.describe()

    assert description["status"] == "configured"
    assert description["prediction_source"] == "model"
    assert description["model"]["name"] == "MiniCPM-V"
    assert description["model"]["version"] == "4.6"
    assert description["model"]["prompt_version"].startswith("scene-zh-")
    assert description["loaded"] is False
    assert description["model_path_present"] is True
    assert description["sampling"]["max_frames"] == 3

    dumped = json.dumps(description, ensure_ascii=False)
    assert str(tmp_path) not in dumped
    assert "model.safetensors" not in dumped


def test_describe_reports_unavailable_when_model_dir_missing(tmp_path):
    config = make_config(tmp_path, model_dir=tmp_path / "does-not-exist")
    adapter = MiniCPMV46Adapter(config)

    description = adapter.describe()

    assert description["status"] == "unavailable"
    assert description["model_path_present"] is False


def test_analyze_without_model_dir_raises_model_not_found(tmp_path):
    config = make_config(tmp_path, model_dir=tmp_path / "nope")
    adapter = MiniCPMV46Adapter(config)

    with pytest.raises(VlmModelNotFoundError) as excinfo:
        adapter.analyze(_request())

    assert excinfo.value.code == "VLM_MODEL_NOT_FOUND"


def _request(duration_s: float | None = 3.0):
    from adapters.vlm.base import AnalysisRequest

    return AnalysisRequest(
        job_id="job_unit",
        video_id="vid_unit",
        video_path="unused.mp4",
        duration_s=duration_s,
    )


# --------------------------------------------------------------------------- #
# Successful analysis
# --------------------------------------------------------------------------- #
def test_analyze_returns_model_source_segments(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(
        monkeypatch,
        adapter,
        ["听讲|学生面向讲台", "听讲|", "小组讨论|学生围坐"],
    )

    output = adapter.analyze(_request())

    assert output.prediction_source == "model"
    assert output.provider == "minicpm_v"
    assert output.model["name"] == "MiniCPM-V"
    assert output.model["version"] == "4.6"
    assert output.model["prompt_version"] == "scene-zh-v1"
    assert output.metadata["is_mock"] is False
    assert output.metadata["frame_count"] == 3
    assert output.metadata["frame_timestamps_s"] == [0.0, 1.0, 2.0]
    assert output.metadata["label_counts"] == {"听讲": 2, "小组讨论": 1}

    assert len(output.segments) == 2
    assert output.segments[0]["scene_label"] == "听讲"
    assert (output.segments[0]["start_s"], output.segments[0]["end_s"]) == (0.0, 2.0)
    assert output.segments[1]["scene_label"] == "小组讨论"
    assert (output.segments[1]["start_s"], output.segments[1]["end_s"]) == (2.0, 3.0)


def test_adapter_reports_real_stages_and_monotonic_progress(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(
        monkeypatch, adapter, ["听讲|a", "小组讨论|b", "独立学习|c"]
    )

    events: list[tuple[str, float]] = []
    request = AnalysisRequest(
        job_id="job_unit",
        video_id="vid_unit",
        video_path="unused.mp4",
        duration_s=3.0,
        on_progress=lambda stage, progress: events.append((stage, progress)),
    )

    adapter.analyze(request)

    stages = [stage for stage, _ in events]
    assert stages[0] == "sampling_frames"
    assert stages.count("inference") == 3

    progresses = [progress for _, progress in events]
    assert progresses == sorted(progresses)
    assert all(0.0 <= progress <= 0.75 for progress in progresses)
    assert progresses[-1] == pytest.approx(0.75)


def test_analyze_never_fabricates_confidence(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(monkeypatch, adapter, ["听讲|a", "独立学习|b"])

    output = adapter.analyze(_request())

    assert all(segment["confidence"] is None for segment in output.segments)


def test_unparseable_model_answer_becomes_uncertain_unclassified(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(monkeypatch, adapter, ["无法判断", "???"])

    output = adapter.analyze(_request())

    assert len(output.segments) == 1
    assert output.segments[0]["scene_label"] == "未分类"
    assert output.segments[0]["is_uncertain"] is True


def test_segments_fall_back_to_the_video_duration_from_request(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(
        monkeypatch, adapter, ["听讲|a", "独立学习|b"], duration_s=None
    )

    output = adapter.analyze(_request(duration_s=3.0))

    assert output.segments[-1]["end_s"] == 3.0


# --------------------------------------------------------------------------- #
# Failure paths — never fall back to mock
# --------------------------------------------------------------------------- #
def test_decode_failure_propagates(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))

    def boom(*args, **kwargs):
        raise VideoDecodeError(details={"reason": "decode_failed"})

    monkeypatch.setattr(minicpm_module, "sample_frames", boom)

    with pytest.raises(VideoDecodeError) as excinfo:
        adapter.analyze(_request())

    assert excinfo.value.code == "VIDEO_DECODE_FAILED"


def test_no_frames_error_propagates(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))

    def boom(*args, **kwargs):
        raise VideoNoFramesError(details={})

    monkeypatch.setattr(minicpm_module, "sample_frames", boom)

    with pytest.raises(VideoNoFramesError):
        adapter.analyze(_request())


def test_model_load_failure_propagates(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    monkeypatch.setattr(
        minicpm_module, "sample_frames", lambda *a, **k: fake_sampling()
    )

    def boom():
        raise VlmLoadFailedError(details={"reason": "load_failed"})

    monkeypatch.setattr(adapter, "_ensure_loaded", boom)

    with pytest.raises(VlmLoadFailedError) as excinfo:
        adapter.analyze(_request())

    assert excinfo.value.code == "VLM_LOAD_FAILED"


def test_generation_failure_raises_vlm_error(tmp_path, monkeypatch):
    adapter = MiniCPMV46Adapter(make_config(tmp_path))
    patch_adapter(monkeypatch, adapter, ["听讲|a"])

    def boom(*args, **kwargs):
        raise VlmAnalysisError(details={"reason": "generation_failed"})

    monkeypatch.setattr(adapter, "_generate", boom)

    with pytest.raises(VlmAnalysisError):
        adapter.analyze(_request())


# --------------------------------------------------------------------------- #
# Job integration
# --------------------------------------------------------------------------- #
def test_real_adapter_job_marks_model_source(tmp_path, monkeypatch):
    app = create_app(make_config(tmp_path))
    adapter = app.extensions["vlm_adapter"]
    assert isinstance(adapter, MiniCPMV46Adapter)
    patch_adapter(monkeypatch, adapter, ["听讲|学生面向讲台", "听讲|", "独立学习|学生在看书"])

    client = app.test_client()
    video_id = upload_video(client)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    app.extensions["job_runner"].run_until_idle()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "completed"
    assert job["stage"] == "done"
    assert job["result"]["prediction_source"] == "model"
    assert job["result"]["is_mock"] is False
    assert job["provider"] == "minicpm_v"
    assert job["model"]["name"] == "MiniCPM-V"

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "processed"
    assert video["prediction_source"] == "model"
    assert video["provider"] == "minicpm_v"
    # Eligibility still follows the existing rule (real model prediction ⇒ True);
    # it does NOT mean the result has been scored against ground truth.
    assert video["evaluation_eligible"] is True

    exported = client.get(f"/api/v1/videos/{video_id}/results?format=json").get_json()
    assert exported["prediction_source"] == "model"
    assert exported["is_mock"] is False
    assert exported["model"]["version"] == "4.6"
    assert exported["segments"][0]["scene_label"] == "听讲"

    csv_text = client.get(f"/api/v1/videos/{video_id}/results?format=csv").data.decode(
        "utf-8-sig"
    )
    assert "minicpm_v" in csv_text
    assert "mock" not in csv_text
    assert "听讲" in csv_text


def test_real_adapter_failure_does_not_fall_back_to_mock(tmp_path, monkeypatch):
    app = create_app(make_config(tmp_path))
    adapter = app.extensions["vlm_adapter"]
    monkeypatch.setattr(
        minicpm_module, "sample_frames", lambda *a, **k: fake_sampling()
    )
    monkeypatch.setattr(adapter, "_ensure_loaded", lambda: (object(), object(), "cuda"))

    def boom(*args, **kwargs):
        raise VlmAnalysisError("模型输出失败")

    monkeypatch.setattr(adapter, "_generate", boom)

    client = app.test_client()
    video_id = upload_video(client)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    app.extensions["job_runner"].run_until_idle()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VLM_UPSTREAM_ERROR"
    assert job["result"] is None

    video = client.get(f"/api/v1/videos/{video_id}").get_json()
    assert video["status"] == "failed"
    assert video["segments"] == []
    assert video["prediction_source"] == "none"
    assert video["evaluation_eligible"] is False

    # The failed job must not have produced any mock-marked payload.
    raw = json.dumps(job, ensure_ascii=False)
    assert "mock" not in raw.lower()


def test_missing_model_marks_job_failed_with_model_not_found(tmp_path):
    config = make_config(tmp_path, model_dir=tmp_path / "missing-model")
    app = create_app(config)
    client = app.test_client()
    video_id = upload_video(client)
    job_id = client.post(f"/api/v1/videos/{video_id}/process").get_json()["job_id"]
    app.extensions["job_runner"].run_until_idle()

    job = client.get(f"/api/v1/jobs/{job_id}").get_json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "VLM_MODEL_NOT_FOUND"
    assert job["result"] is None


# --------------------------------------------------------------------------- #
# Environment configuration
# --------------------------------------------------------------------------- #
def _clear_backend_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("BACKEND_"):
            monkeypatch.delenv(key, raising=False)


def test_from_env_accepts_minicpm_and_sampling_settings(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_VLM_ADAPTER", "MiniCPM")
    monkeypatch.setenv("BACKEND_VLM_MAX_FRAMES", "4")
    monkeypatch.setenv("BACKEND_VLM_FRAME_INTERVAL_S", "0.5")
    monkeypatch.setenv("BACKEND_VLM_MAX_DURATION_S", "30")
    monkeypatch.setenv("BACKEND_VLM_MAX_NEW_TOKENS", "32")

    config = Config.from_env()

    assert config.vlm_adapter == "minicpm"
    assert config.vlm_max_frames == 4
    assert config.vlm_frame_interval_s == 0.5
    assert config.vlm_max_duration_s == 30.0
    assert config.vlm_max_new_tokens == 32
    assert config.vlm_model_path.endswith(os.path.join("models", "MiniCPM-V-4.6"))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BACKEND_VLM_ADAPTER", "openai"),
        ("BACKEND_VLM_MAX_FRAMES", "0"),
        ("BACKEND_VLM_MAX_FRAMES", "65"),
        ("BACKEND_VLM_FRAME_INTERVAL_S", "0"),
        ("BACKEND_VLM_MAX_DURATION_S", "-1"),
        ("BACKEND_VLM_MAX_NEW_TOKENS", "0"),
    ],
)
def test_from_env_rejects_invalid_vlm_settings(monkeypatch, name, value):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Config.from_env()


def test_default_adapter_is_still_mock(monkeypatch):
    _clear_backend_env(monkeypatch)

    config = Config.from_env()

    assert config.vlm_adapter == "mock"
    assert config.vlm_device == "cuda"


def test_api_info_reports_real_adapter(tmp_path):
    app = create_app(make_config(tmp_path))
    body = app.test_client().get("/api/v1/info").get_json()

    assert body["capabilities"]["video_analysis"] is True
    assert body["adapters"]["vlm"]["name"] == "minicpm_v"
    assert body["adapters"]["vlm"]["status"] == "configured"
    assert body["adapters"]["vlm"]["prediction_source"] == "model"
    assert body["adapters"]["vlm"]["model_path_present"] is True


def test_api_info_reports_mock_adapter_by_default(client):
    body = client.get("/api/v1/info").get_json()

    assert body["capabilities"]["video_analysis"] is False
    assert body["adapters"]["vlm"]["name"] == "mock"
