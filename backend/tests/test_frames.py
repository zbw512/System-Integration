"""Frame sampling tests (real decoding via PyAV on generated clips)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.vlm.frames import (
    _validate_timestamp,
    plan_targets,
    sample_frames,
)
from services.errors import VideoDecodeError, VideoNoFramesError
from video_fixtures import write_test_video


# --------------------------------------------------------------------------- #
# Target planning
# --------------------------------------------------------------------------- #
def test_plan_targets_respects_interval_and_cap():
    targets = plan_targets(
        interval_s=1.0, max_frames=3, max_duration_s=60.0, duration_s=3.0
    )

    assert targets == [0.0, 1.0, 2.0]


def test_plan_targets_stops_at_max_duration():
    targets = plan_targets(
        interval_s=1.0, max_frames=10, max_duration_s=2.0, duration_s=10.0
    )

    assert targets == [0.0, 1.0, 2.0]


def test_plan_targets_always_yields_one_sample():
    targets = plan_targets(
        interval_s=5.0, max_frames=8, max_duration_s=60.0, duration_s=1.0
    )

    assert targets == [0.0]


def test_plan_targets_uses_duration_when_shorter():
    targets = plan_targets(
        interval_s=2.0, max_frames=4, max_duration_s=60.0, duration_s=5.0
    )

    assert targets == [0.0, 2.0, 4.0]


# --------------------------------------------------------------------------- #
# Timestamp guards
# --------------------------------------------------------------------------- #
def test_missing_pts_is_rejected():
    with pytest.raises(VideoDecodeError) as excinfo:
        _validate_timestamp(None, 0.0)

    assert excinfo.value.details["reason"] == "missing_pts"


@pytest.mark.parametrize("timestamp", [-0.5, float("nan"), float("inf")])
def test_invalid_timestamp_is_rejected(timestamp):
    with pytest.raises(VideoDecodeError) as excinfo:
        _validate_timestamp(timestamp, 0.0)

    assert excinfo.value.details["reason"] == "invalid_timestamp"


def test_non_monotonic_timestamp_is_rejected():
    with pytest.raises(VideoDecodeError) as excinfo:
        _validate_timestamp(0.5, 1.0)

    assert excinfo.value.details["reason"] == "non_monotonic_timestamp"


def test_valid_timestamp_passes_through():
    assert _validate_timestamp(1.5, 1.0) == 1.5


# --------------------------------------------------------------------------- #
# Real decoding
# --------------------------------------------------------------------------- #
def test_samples_a_real_clip_with_timestamps(tmp_path: Path):
    video = write_test_video(tmp_path / "clip.mp4", seconds=3.0, fps=10)

    result = sample_frames(
        str(video), interval_s=1.0, max_frames=8, max_duration_s=60.0
    )

    assert result.count == 3
    assert [frame.timestamp_s for frame in result.frames] == [0.0, 1.0, 2.0]
    assert result.duration_s == pytest.approx(3.0, abs=0.2)
    assert result.width == 320 and result.height == 180
    assert result.frames[0].image.size == (320, 180)


def test_max_frames_caps_the_sample_count(tmp_path: Path):
    video = write_test_video(tmp_path / "clip.mp4", seconds=5.0, fps=10)

    result = sample_frames(
        str(video), interval_s=1.0, max_frames=2, max_duration_s=60.0
    )

    assert result.count == 2


def test_max_duration_caps_the_sample_times(tmp_path: Path):
    video = write_test_video(tmp_path / "clip.mp4", seconds=5.0, fps=10)

    result = sample_frames(
        str(video), interval_s=1.0, max_frames=10, max_duration_s=2.0
    )

    assert [frame.timestamp_s for frame in result.frames] == [0.0, 1.0, 2.0]


def test_missing_file_is_rejected(tmp_path: Path):
    with pytest.raises(VideoDecodeError) as excinfo:
        sample_frames(
            str(tmp_path / "nope.mp4"),
            interval_s=1.0,
            max_frames=4,
            max_duration_s=60.0,
        )

    assert excinfo.value.details["reason"] == "file_missing"


def test_non_video_file_is_rejected(tmp_path: Path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is definitely not a video container")

    with pytest.raises(VideoDecodeError):
        sample_frames(str(broken), interval_s=1.0, max_frames=4, max_duration_s=60.0)


def test_no_frames_error_type_is_exposed():
    # Guards the error class the adapter relies on when decoding yields nothing.
    error = VideoNoFramesError(details={"duration_s": 0.0})
    assert error.code == "VIDEO_NO_FRAMES"
    assert error.status == 422
