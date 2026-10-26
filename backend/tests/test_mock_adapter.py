"""Mock VLM adapter tests.

The mock is the only adapter in P0-3, so these tests pin down the two things
that must never regress: its output is standard-compliant, and it can never be
mistaken for a real model.
"""

from __future__ import annotations

import pytest

from adapters.vlm import build_vlm_adapter
from adapters.vlm.base import AnalysisRequest
from adapters.vlm.mock import MOCK_MODEL, MOCK_PROVIDER, MockVlmAdapter
from config import Config
from schemas.enums import SceneLabel
from services.errors import VlmAnalysisError


def make_request(duration_s: float | None = 3.0) -> AnalysisRequest:
    return AnalysisRequest(
        job_id="job_test000001",
        video_id="vid_test000001",
        video_path="/data/videos/vid_test000001.mp4",
        duration_s=duration_s,
    )


def test_describe_marks_the_adapter_as_mock():
    description = MockVlmAdapter().describe()

    assert description["status"] == "mock"
    assert description["prediction_source"] == "mock"
    assert description["provider"] == MOCK_PROVIDER
    assert description["model"]["name"] == MOCK_MODEL["name"]
    assert description["evaluation_eligible"] is False
    assert "mock" in description["provider"]
    assert "mock" in description["model"]["name"]


def test_analyze_returns_mock_marked_output():
    output = MockVlmAdapter().analyze(make_request(3.0))

    assert output.prediction_source == "mock"
    assert output.provider == MOCK_PROVIDER
    assert output.model["name"] == MOCK_MODEL["name"]
    assert output.metadata["is_mock"] is True
    assert output.is_mock is True


def test_analyze_splits_a_three_second_clip_into_three_legal_segments():
    output = MockVlmAdapter().analyze(make_request(3.0))
    segments = output.segments

    assert len(segments) == 3
    assert [segment["index"] for segment in segments] == [0, 1, 2]
    assert segments[0]["start_s"] == 0.0
    assert segments[-1]["end_s"] == 3.0

    # Contiguous coverage, no gap and no overlap.
    for previous, current in zip(segments, segments[1:]):
        assert previous["end_s"] == current["start_s"]


@pytest.mark.parametrize("duration", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 8.0, 60.0])
def test_segments_are_legal_for_any_duration(duration):
    segments = MockVlmAdapter().analyze(make_request(duration)).segments
    legal_labels = {label.value for label in SceneLabel}

    assert segments, "至少返回一个时间段"
    assert segments[0]["start_s"] == 0.0
    assert segments[-1]["end_s"] == pytest.approx(duration, abs=1e-3)

    for segment in segments:
        assert 0.0 <= segment["start_s"] < segment["end_s"] <= duration + 1e-6
        assert segment["scene_label"] in legal_labels
        assert 0.0 <= segment["confidence"] <= 1.0
        assert segment["is_uncertain"] is False
        assert len(segment["evidence"]) <= 500


def test_segment_count_is_capped_at_three():
    assert len(MockVlmAdapter().analyze(make_request(120.0)).segments) == 3


@pytest.mark.parametrize("duration", [None, 0.0, -1.0])
def test_unknown_duration_is_refused_instead_of_fabricated(duration):
    with pytest.raises(VlmAnalysisError) as excinfo:
        MockVlmAdapter().analyze(make_request(duration))

    assert excinfo.value.details["reason"] == "duration_unknown"
    assert excinfo.value.retryable is True


def test_build_vlm_adapter_returns_mock_for_default_config():
    adapter = build_vlm_adapter(Config())

    assert isinstance(adapter, MockVlmAdapter)


def test_build_vlm_adapter_rejects_unknown_name():
    # ``minicpm`` became a valid adapter in P0-5, so use a genuinely unknown one.
    with pytest.raises(ValueError):
        build_vlm_adapter(Config(vlm_adapter="openai"))
