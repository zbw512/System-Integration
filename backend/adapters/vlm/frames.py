"""Frame sampling with real timestamps (PyAV backend).

Why PyAV
--------
The environment ships ``torchcodec`` built against a different PyTorch: it
cannot load its core DLLs (no system FFmpeg either). PyAV wheels bundle FFmpeg,
so decoding works without touching PyTorch / Transformers / CUDA — and it is the
fallback the repository's own ``inference/minicpm-v4_6_video_understanding.md``
recommends for exactly this situation.

Sampling strategy
-----------------
A **single sequential decode pass**. Seeking was measured to be unreliable on
short clips (``container.seek(1.0s)`` and ``(2.0s)`` both returned the first
keyframe), and a 3 s / 54-frame clip decodes in ~0.17 s anyway. The decoder
walks frames in order and captures the first frame whose ``pts`` reaches each
target time, so every sample keeps its **real** timestamp.

Nothing here invents timestamps: a missing/invalid/non-monotonic PTS aborts the
job with an explicit error instead of producing a plausible-looking timeline.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image

from services.errors import VideoDecodeError, VideoNoFramesError

_EPSILON = 1e-6


@dataclass(frozen=True)
class SampledFrame:
    """One decoded frame together with its position on the video timeline."""

    timestamp_s: float
    image: Any  # PIL.Image.Image (typed Any to keep this module torch/PIL-free at import)


@dataclass(frozen=True)
class FrameSamplingResult:
    duration_s: float | None
    frames: tuple[SampledFrame, ...]
    fps: float | None = None
    width: int | None = None
    height: int | None = None

    @property
    def count(self) -> int:
        return len(self.frames)


def plan_targets(
    *,
    interval_s: float,
    max_frames: int,
    max_duration_s: float,
    duration_s: float | None,
) -> list[float]:
    """Target sample times (seconds) honouring the frame and duration caps."""
    limit = max_duration_s
    if duration_s is not None:
        limit = min(limit, duration_s)

    targets: list[float] = []
    current = 0.0
    while len(targets) < max_frames and current <= limit + _EPSILON:
        targets.append(round(current, 6))
        current += interval_s

    return targets or [0.0]


def _to_image(frame) -> Image.Image:
    array = frame.to_ndarray(format="rgb24")
    return Image.fromarray(array).convert("RGB")


def _stream_fps(stream) -> float | None:
    rate = getattr(stream, "average_rate", None)
    if rate is None:
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    return round(value, 3) if value > 0 else None


def _validate_timestamp(timestamp: float | None, last_timestamp: float) -> float:
    """Reject missing/negative/non-monotonic PTS instead of guessing.

    Exposed (underscore-prefixed) so the guard itself is unit-testable without
    crafting a corrupt video file.
    """
    if timestamp is None:
        raise VideoDecodeError(details={"reason": "missing_pts"})
    if not math.isfinite(timestamp) or timestamp < 0:
        raise VideoDecodeError(details={"reason": "invalid_timestamp"})
    if timestamp + _EPSILON < last_timestamp:
        raise VideoDecodeError(details={"reason": "non_monotonic_timestamp"})
    return timestamp


def sample_frames(
    path: str,
    *,
    interval_s: float,
    max_frames: int,
    max_duration_s: float,
) -> FrameSamplingResult:
    """Decode ``path`` and return sampled frames with their timestamps.

    Raises
    ------
    VideoDecodeError
        Missing dependency, unreadable container, no video stream, or an
        invalid/non-monotonic timestamp.
    VideoNoFramesError
        Decoding succeeded but produced no usable frame.
    """
    if not os.path.isfile(path):
        raise VideoDecodeError(details={"reason": "file_missing"})

    try:
        import av
    except ImportError as exc:
        raise VideoDecodeError(
            "缺少视频解码依赖 PyAV（请安装 av）",
            details={"dependency": "av", "reason": "dependency_missing"},
        ) from exc

    try:
        container = av.open(path)
    except Exception as exc:
        raise VideoDecodeError(details={"reason": "open_failed"}) from exc

    frames: list[SampledFrame] = []
    duration_s: float | None = None
    fps: float | None = None
    width = height = None

    try:
        try:
            stream = container.streams.video[0]
        except (IndexError, AttributeError) as exc:
            raise VideoDecodeError(details={"reason": "no_video_stream"}) from exc

        time_base = float(stream.time_base) if stream.time_base else 0.0
        if time_base <= 0:
            raise VideoDecodeError(details={"reason": "invalid_time_base"})

        if getattr(stream, "duration", None):
            duration_s = round(float(stream.duration * time_base), 3)
        elif container.duration:
            duration_s = round(container.duration / 1_000_000, 3)

        fps = _stream_fps(stream)
        width = getattr(stream, "width", None)
        height = getattr(stream, "height", None)

        targets = plan_targets(
            interval_s=interval_s,
            max_frames=max_frames,
            max_duration_s=max_duration_s,
            duration_s=duration_s,
        )

        target_index = 0
        last_timestamp = -1.0

        try:
            for frame in container.decode(stream):
                timestamp = _validate_timestamp(
                    None if frame.pts is None else float(frame.pts * time_base),
                    last_timestamp,
                )
                last_timestamp = timestamp

                if timestamp > max_duration_s + _EPSILON:
                    break

                while (
                    target_index < len(targets)
                    and timestamp + _EPSILON >= targets[target_index]
                ):
                    frames.append(
                        SampledFrame(timestamp_s=round(timestamp, 3), image=_to_image(frame))
                    )
                    target_index += 1

                if target_index >= len(targets):
                    break
        except VideoDecodeError:
            raise
        except Exception as exc:
            raise VideoDecodeError(details={"reason": "decode_failed"}) from exc
    finally:
        container.close()

    if not frames:
        raise VideoNoFramesError(details={"duration_s": duration_s})

    return FrameSamplingResult(
        duration_s=duration_s,
        frames=tuple(frames),
        fps=fps,
        width=width,
        height=height,
    )
