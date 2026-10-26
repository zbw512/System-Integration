"""Real (decodable) MP4 fixtures generated on the fly with PyAV.

No external assets and no ffmpeg CLI: PyAV encodes a short MPEG-4 clip straight
into the test's temporary directory, so frame sampling and the real adapter can
be exercised on an actual container instead of a synthetic header.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _solid_frame(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def write_test_video(
    path: Path,
    *,
    seconds: float = 3.0,
    fps: int = 10,
    size: tuple[int, int] = (320, 180),
    color: tuple[int, int, int] = (40, 90, 160),
) -> Path:
    """Encode a short, decodable MPEG-4 clip and return its path."""
    import av  # imported lazily so this module loads even without av

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"

        total = max(1, int(round(seconds * fps)))
        for index in range(total):
            frame = av.VideoFrame.from_ndarray(
                _solid_frame(size[0], size[1], color), format="rgb24"
            )
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()

    return path
