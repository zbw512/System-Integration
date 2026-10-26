"""Opt-in real-model acceptance test.

Skipped by default. It is the only test that loads the real weights, and it
requires:

* ``BACKEND_REAL_VLM_TEST=1``
* the local model at ``models/MiniCPM-V-4.6`` (or ``BACKEND_VLM_MODEL_PATH``)
* a CUDA device
* PyAV for decoding (generated clip)

Run it explicitly::

    $env:BACKEND_REAL_VLM_TEST = "1"
    python -m pytest tests/test_real_vlm_optional.py -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BACKEND_REAL_VLM_TEST") != "1",
    reason="需要真实模型与 GPU；设置 BACKEND_REAL_VLM_TEST=1 才会运行",
)

from adapters.vlm.base import AnalysisRequest  # noqa: E402
from adapters.vlm.minicpm import MiniCPMV46Adapter  # noqa: E402
from config import Config  # noqa: E402
from video_fixtures import write_test_video  # noqa: E402


def test_real_model_loads_and_analyses_a_short_clip(tmp_path):
    pytest.importorskip("av")
    import torch

    if not torch.cuda.is_available():
        pytest.skip("没有可用的 CUDA 设备")

    config = Config(
        vlm_adapter="minicpm",
        vlm_max_frames=2,
        vlm_frame_interval_s=1.0,
        vlm_max_duration_s=5.0,
        vlm_max_new_tokens=32,
        log_level="CRITICAL",
    )
    adapter = MiniCPMV46Adapter(config)

    if not adapter.describe()["model_path_present"]:
        pytest.skip("本地模型目录不存在")

    video = write_test_video(tmp_path / "clip.mp4", seconds=2.0, fps=10)

    output = adapter.analyze(
        AnalysisRequest(
            job_id="job_real_test",
            video_id="vid_real_test",
            video_path=str(video),
            duration_s=2.0,
        )
    )

    assert output.prediction_source == "model"
    assert output.provider == "minicpm_v"
    assert output.model["name"] == "MiniCPM-V"
    assert output.metadata["is_mock"] is False
    assert output.metadata["frame_count"] == 2
    assert output.segments, "至少应产生一个分段"
    for segment in output.segments:
        assert segment["start_s"] < segment["end_s"] <= 2.0 + 1e-6
        assert segment["confidence"] is None
        assert segment["scene_label"] in {
            "听讲",
            "小组讨论",
            "独立学习",
            "其他",
            "未分类",
        }
