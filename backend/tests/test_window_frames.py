"""Golden tests for full-video windowing and owner-compatible frame sampling."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.vlm.window_frames import (
    decode_video_windows,
    plan_window_bounds,
    select_uniform_frame_indices,
)
from video_fixtures import write_test_video


POLICY_ID = "provisional-3s-window-3s-stride-tail-v1"


def test_plan_uses_three_second_non_overlapping_windows() -> None:
    assert plan_window_bounds(
        duration_s=9.0,
        max_duration_s=60.0,
        window_seconds=3.0,
        stride_seconds=3.0,
    ) == [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)]


def test_plan_retains_short_tail() -> None:
    assert plan_window_bounds(
        duration_s=6.4,
        max_duration_s=60.0,
        window_seconds=3.0,
        stride_seconds=3.0,
    ) == [(0.0, 3.0), (3.0, 6.0), (6.0, 6.4)]


def test_plan_caps_video_duration() -> None:
    assert plan_window_bounds(
        duration_s=90.0,
        max_duration_s=7.0,
        window_seconds=3.0,
        stride_seconds=3.0,
    ) == [(0.0, 3.0), (3.0, 6.0), (6.0, 7.0)]


def test_overlapping_stride_is_rejected() -> None:
    with pytest.raises(ValueError):
        plan_window_bounds(
            duration_s=6.0,
            max_duration_s=60.0,
            window_seconds=3.0,
            stride_seconds=1.5,
        )


def test_uniform_indices_match_owner_formula() -> None:
    assert select_uniform_frame_indices(20, 8) == [0, 3, 5, 8, 11, 14, 16, 19]


def test_fewer_than_eight_frames_are_all_used() -> None:
    assert select_uniform_frame_indices(5, 8) == [0, 1, 2, 3, 4]


def test_decodes_three_second_video_as_one_window(tmp_path: Path) -> None:
    video = write_test_video(tmp_path / "three.mp4", seconds=3.0, fps=2)
    result = decode_video_windows(
        str(video),
        duration_hint_s=3.0,
        window_seconds=3.0,
        stride_seconds=3.0,
        max_frames=8,
        max_duration_s=60.0,
        policy_id=POLICY_ID,
    )

    assert len(result.windows) == 1
    assert result.windows[0].start_s == 0.0
    assert result.windows[0].end_s == pytest.approx(3.0, abs=0.01)
    assert [frame.timestamp_s for frame in result.windows[0].frames] == [
        0.0,
        0.5,
        1.0,
        1.5,
        2.0,
        2.5,
    ]


def test_decodes_six_seconds_as_two_windows(tmp_path: Path) -> None:
    video = write_test_video(tmp_path / "six.mp4", seconds=6.0, fps=2)
    result = decode_video_windows(
        str(video),
        duration_hint_s=6.0,
        window_seconds=3.0,
        stride_seconds=3.0,
        max_frames=8,
        max_duration_s=60.0,
        policy_id=POLICY_ID,
    )

    assert len(result.windows) == 2
    assert [(window.start_s, window.end_s) for window in result.windows] == [
        (0.0, 3.0),
        (3.0, 6.0),
    ]
    assert all(len(window.frames) <= 8 for window in result.windows)
    assert result.windows[0].frames[-1].timestamp_s < 3.0
    assert result.windows[1].frames[0].timestamp_s >= 3.0


def test_decodes_short_tail_window(tmp_path: Path) -> None:
    video = write_test_video(tmp_path / "tail.mp4", seconds=6.5, fps=2)
    result = decode_video_windows(
        str(video),
        duration_hint_s=6.5,
        window_seconds=3.0,
        stride_seconds=3.0,
        max_frames=8,
        max_duration_s=60.0,
        policy_id=POLICY_ID,
    )

    assert len(result.windows) == 3
    assert result.windows[-1].start_s == 6.0
    assert result.windows[-1].end_s == pytest.approx(6.5, abs=0.01)
    assert len(result.windows[-1].frames) >= 1
