"""Decode once and split a complete video into fixed, non-overlapping windows.

The current policy is deliberately explicit:

* 3-second windows;
* 3-second stride;
* no overlap;
* retain a short tail window when the video does not end on a boundary;
* choose at most 8 frames inside each window with the owner's first/last
  uniform index formula.

There is no supplied full-video training preprocessor. This policy is therefore
identified as provisional in adapter metadata and must not be described as an
exact reproduction of training-time loading.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Sequence

from PIL import Image

from services.errors import VideoDecodeError, VideoNoFramesError

_EPSILON = 1e-6


@dataclass(frozen=True)
class WindowFrame:
    timestamp_s: float
    image: Image.Image


@dataclass(frozen=True)
class DecodedWindow:
    index: int
    start_s: float
    end_s: float
    frames: tuple[WindowFrame, ...]


@dataclass(frozen=True)
class WindowDecodeResult:
    windows: tuple[DecodedWindow, ...]
    duration_s: float | None
    fps: float | None
    width: int | None
    height: int | None
    policy_id: str


def plan_window_bounds(
    *,
    duration_s: float | None,
    max_duration_s: float,
    window_seconds: float,
    stride_seconds: float,
) -> list[tuple[float, float]]:
    """Return half-open window bounds, capped by duration and max duration."""
    if window_seconds <= 0 or stride_seconds <= 0:
        raise ValueError("window_seconds 和 stride_seconds 必须大于 0")
    if stride_seconds < window_seconds - _EPSILON:
        raise ValueError("初版不支持重叠窗口：stride_seconds 不能小于 window_seconds")
    if max_duration_s <= 0:
        raise ValueError("max_duration_s 必须大于 0")

    cap = max_duration_s
    if duration_s is not None and duration_s > 0:
        cap = min(cap, duration_s)

    bounds: list[tuple[float, float]] = []
    index = 0
    while True:
        start = round(index * stride_seconds, 6)
        if start >= cap - _EPSILON:
            break
        end = round(min(start + window_seconds, cap), 6)
        if end <= start:
            break
        bounds.append((start, end))
        index += 1
    return bounds


def select_uniform_frame_indices(frame_count: int, max_frames: int) -> list[int]:
    """Use exactly the owner's uniform index formula."""
    if frame_count <= 0:
        return []
    if max_frames <= 0:
        raise ValueError("max_frames 必须大于 0")
    if frame_count <= max_frames:
        return list(range(frame_count))
    if max_frames == 1:
        return [0]
    return [
        round(index * (frame_count - 1) / (max_frames - 1))
        for index in range(max_frames)
    ]


def _select_window_frames(
    frames: Sequence[WindowFrame],
    *,
    max_frames: int,
) -> tuple[WindowFrame, ...]:
    indices = select_uniform_frame_indices(len(frames), max_frames)
    return tuple(frames[index] for index in indices)


def _to_image(frame: Any) -> Image.Image:
    return frame.to_image().convert("RGB")


def _stream_fps(stream: Any) -> float | None:
    rate = getattr(stream, "average_rate", None)
    if rate is None:
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return None
    return round(value, 3) if value > 0 else None


def decode_video_windows(
    path: str,
    *,
    duration_hint_s: float | None,
    window_seconds: float,
    stride_seconds: float,
    max_frames: int,
    max_duration_s: float,
    policy_id: str,
) -> WindowDecodeResult:
    """Decode a video once while buffering and selecting one window at a time."""
    if not isinstance(max_frames, int) or not 1 <= max_frames <= 8:
        raise ValueError("max_frames 必须在 1-8 之间")
    if not os.path.isfile(path):
        raise VideoDecodeError(details={"reason": "file_missing"})

    try:
        import av
    except ImportError as exc:
        raise VideoDecodeError(
            details={"device": "unavailable", "reason": "av_missing"}
        ) from exc

    try:
        container = av.open(path)
    except Exception as exc:
        raise VideoDecodeError(details={"reason": "open_failed"}) from exc

    windows: list[DecodedWindow] = []
    duration_s: float | None = None
    fps: float | None = None
    width = height = None

    current_index = 0
    current_start = 0.0
    current_end = window_seconds
    pending: list[WindowFrame] = []
    last_timestamp: float | None = None

    def finish_current(end_override: float | None = None) -> bool:
        nonlocal pending
        end = current_end if end_override is None else end_override
        if not pending:
            return False
        selected = _select_window_frames(pending, max_frames=max_frames)
        windows.append(
            DecodedWindow(
                index=len(windows),
                start_s=round(current_start, 6),
                end_s=round(end, 6),
                frames=selected,
            )
        )
        pending = []
        return True

    try:
        try:
            stream = container.streams.video[0]
        except (IndexError, AttributeError) as exc:
            raise VideoDecodeError(details={"reason": "no_video_stream"}) from exc

        time_base = float(stream.time_base) if stream.time_base else 0.0
        if time_base <= 0:
            raise VideoDecodeError(details={"reason": "invalid_time_base"})

        if getattr(stream, "duration", None):
            duration_s = round(float(stream.duration * time_base), 6)
        elif container.duration:
            duration_s = round(float(container.duration / 1_000_000), 6)
        elif duration_hint_s is not None and duration_hint_s > 0:
            duration_s = float(duration_hint_s)

        if duration_hint_s is not None and duration_hint_s > 0:
            duration_s = min(duration_s, duration_hint_s) if duration_s else float(
                duration_hint_s
            )

        fps = _stream_fps(stream)
        width = getattr(stream, "width", None)
        height = getattr(stream, "height", None)

        planned_bounds = plan_window_bounds(
            duration_s=duration_s,
            max_duration_s=max_duration_s,
            window_seconds=window_seconds,
            stride_seconds=stride_seconds,
        )
        if not planned_bounds:
            raise VideoNoFramesError(details={"reason": "empty_window_plan"})
        current_start, current_end = planned_bounds[0]

        try:
            for frame in container.decode(stream):
                pts = getattr(frame, "pts", None)
                if pts is None:
                    raise VideoDecodeError(details={"reason": "missing_pts"})
                timestamp = float(pts * time_base)
                if not math.isfinite(timestamp) or timestamp < 0:
                    raise VideoDecodeError(
                        details={"reason": "invalid_timestamp"}
                    )
                if (
                    last_timestamp is not None
                    and timestamp + _EPSILON < last_timestamp
                ):
                    raise VideoDecodeError(
                        details={"reason": "non_monotonic_timestamp"}
                    )
                last_timestamp = timestamp

                if timestamp > max_duration_s + _EPSILON:
                    break

                while (
                    current_index < len(planned_bounds)
                    and timestamp + _EPSILON >= current_end
                ):
                    if not finish_current():
                        raise VideoNoFramesError(
                            details={
                                "reason": "window_without_frames",
                                "window_index": current_index,
                            }
                        )
                    current_index += 1
                    if current_index >= len(planned_bounds):
                        break
                    current_start, current_end = planned_bounds[current_index]

                if current_index >= len(planned_bounds):
                    break
                if timestamp + _EPSILON < current_start:
                    continue
                if timestamp + _EPSILON >= current_end:
                    continue

                pending.append(
                    WindowFrame(
                        timestamp_s=round(timestamp, 6),
                        image=_to_image(frame),
                    )
                )

            while current_index < len(planned_bounds):
                if pending:
                    end_override = None
                    if duration_s is None:
                        end_override = min(
                            current_end,
                            max(current_start + _EPSILON, last_timestamp),
                        )
                    finish_current(end_override=end_override)
                elif duration_s is None:
                    # With unknown duration the plan may extend beyond the last
                    # decoded frame; trailing empty windows are not real video.
                    break
                else:
                    raise VideoNoFramesError(
                        details={
                            "reason": "window_without_frames",
                            "window_index": current_index,
                        }
                    )
                current_index += 1
                if current_index < len(planned_bounds):
                    current_start, current_end = planned_bounds[current_index]
        except VideoDecodeError:
            raise
        except VideoNoFramesError:
            raise
        except Exception as exc:
            raise VideoDecodeError(details={"reason": "decode_failed"}) from exc
    finally:
        container.close()

    if not windows:
        raise VideoNoFramesError(details={"duration_s": duration_s})

    for previous, current in zip(windows, windows[1:]):
        if current.start_s < previous.end_s - _EPSILON:
            raise VideoDecodeError(details={"reason": "overlapping_windows"})

    return WindowDecodeResult(
        windows=tuple(windows),
        duration_s=duration_s,
        fps=fps,
        width=width,
        height=height,
        policy_id=policy_id,
    )
