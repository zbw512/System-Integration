"""Synthetic MP4 containers used by the tests.

These are *minimal* ISO-BMFF files (``ftyp`` + ``moov/mvhd`` only). They let the
container sniffer and the duration parser be tested without a real video, a
decoder or any network access.

They contain no media track, so they must never be used for inference tests or
mistaken for playable video.
"""

from __future__ import annotations

import struct
from pathlib import Path


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def make_minimal_mp4(duration_s: float = 3.0, timescale: int = 1000) -> bytes:
    """Return bytes of a minimal ``ftyp`` + ``moov/mvhd`` MP4 container."""
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2avc1mp41")

    mvhd_payload = (
        b"\x00\x00\x00\x00"  # version 0 + flags
        + struct.pack(">I", 0)  # creation_time
        + struct.pack(">I", 0)  # modification_time
        + struct.pack(">I", timescale)
        + struct.pack(">I", int(round(duration_s * timescale)))
        + struct.pack(">I", 0x00010000)  # rate 1.0
        + struct.pack(">H", 0x0100)  # volume 1.0
        + b"\x00" * 10  # reserved
        + b"\x00" * 36  # matrix
        + b"\x00" * 24  # pre_defined
        + struct.pack(">I", 2)  # next_track_id
    )
    moov = _box(b"moov", _box(b"mvhd", mvhd_payload))
    return ftyp + moov


def make_ftyp_only_mp4() -> bytes:
    """An MP4 container without ``moov`` — duration cannot be determined."""
    return _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2avc1mp41")


def write_minimal_mp4(path: Path, duration_s: float = 3.0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_minimal_mp4(duration_s))
    return path
