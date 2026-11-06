"""Opt-in acceptance against a real AutoDL GPU service.

Enable after the SSH tunnel and cloud model service are healthy:

    $env:BACKEND_REAL_REMOTE_TEST = "1"
    $env:BACKEND_VLM_REMOTE_TOKEN = "<token>"
    $env:BACKEND_REAL_REMOTE_VIDEO = "<local 3-second mp4>"
    python -m pytest tests/test_real_remote_optional.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BACKEND_REAL_REMOTE_TEST") != "1",
    reason="需要 SSH 隧道、AutoDL GPU 和真实模型",
)

from adapters.vlm.base import AnalysisRequest
from adapters.vlm.minicpm_remote import MiniCPMV45RemoteAdapter
from config import Config


def test_real_autodl_model_analyzes_one_window() -> None:
    video_value = os.environ.get("BACKEND_REAL_REMOTE_VIDEO", "")
    if not video_value:
        pytest.skip("未设置 BACKEND_REAL_REMOTE_VIDEO")
    video = Path(video_value)
    if not video.is_file():
        pytest.skip(f"测试视频不存在：{video}")

    token = os.environ.get("BACKEND_VLM_REMOTE_TOKEN", "")
    if len(token) < 32:
        pytest.skip("BACKEND_VLM_REMOTE_TOKEN 未设置或短于 32 字符")

    config = Config(
        vlm_adapter="minicpm_remote",
        vlm_remote_url=os.environ.get(
            "BACKEND_VLM_REMOTE_URL", "http://127.0.0.1:18080"
        ),
        vlm_remote_token=token,
        vlm_remote_timeout_s=300.0,
        vlm_remote_retries=0,
        vlm_max_frames=8,
        vlm_window_seconds=3.0,
        vlm_window_stride_seconds=3.0,
        vlm_max_duration_s=3.0,
    )
    output = MiniCPMV45RemoteAdapter(config).analyze(
        AnalysisRequest(
            job_id="job-real-remote",
            video_id="video-real-remote",
            video_path=str(video),
            duration_s=3.0,
        )
    )

    assert output.prediction_source == "model"
    assert output.provider == "minicpm_v"
    assert output.model["version"] == "4.5"
    assert output.model["checkpoint"] == "checkpoint-600"
    assert output.segments
    assert all(item["start_s"] < item["end_s"] <= 3.01 for item in output.segments)
