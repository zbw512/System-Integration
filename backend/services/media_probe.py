"""Dependency-free media probing.

Uploaded files are validated by container signature instead of trusting the
extension, and the duration is read from the ISO-BMFF ``moov/mvhd`` box.

Why not OpenCV/FFmpeg: the project environment does not ship a decoder that may
be safely installed here (installing extra media libraries would change the
PyTorch/CUDA-adjacent environment). Parsing ``mvhd`` needs no dependency and is
enough to report ``duration_s`` for the containers we accept. Frame extraction
for inference is a P0-6 concern and will use the model's own video processor.

Nothing here decodes video frames; it only sniffs headers.
"""

from __future__ import annotations

import os

from services.errors import InvalidVideoRequestError, UnsupportedVideoFormatError
from storage import files as storage_files

#: Guard against pathological headers: only read a bounded ``moov`` payload.
_MAX_MOOV_BYTES = 32 * 1024 * 1024
_MAX_TOP_LEVEL_BOXES = 64


def looks_like_iso_bmff(head: bytes) -> bool:
    """``ftyp`` at offset 4 identifies MP4 / M4V / QuickTime containers."""
    return len(head) >= 8 and head[4:8] == b"ftyp"


def _iter_top_level_boxes(handle, file_size: int, limit: int = _MAX_TOP_LEVEL_BOXES):
    """Yield ``(offset, type, size, header_size)`` for top-level boxes."""
    offset = 0
    count = 0
    while offset + 8 <= file_size and count < limit:
        handle.seek(offset)
        header = handle.read(8)
        if len(header) < 8:
            return
        size = int.from_bytes(header[0:4], "big")
        box_type = header[4:8]
        header_size = 8
        if size == 1:
            extended = handle.read(8)
            if len(extended) < 8:
                return
            size = int.from_bytes(extended, "big")
            header_size = 16
        elif size == 0:
            size = file_size - offset
        if size < header_size:
            return
        yield offset, box_type, size, header_size
        offset += size
        count += 1


def _duration_from_mvhd(payload: bytes) -> float | None:
    """Parse ``duration / timescale`` from an ``mvhd`` box inside ``payload``."""
    index = payload.find(b"mvhd")
    if index < 0 or index + 24 > len(payload):
        return None

    version = payload[index + 4]
    try:
        if version == 1:
            timescale = int.from_bytes(payload[index + 24 : index + 28], "big")
            duration = int.from_bytes(payload[index + 28 : index + 36], "big")
        else:
            timescale = int.from_bytes(payload[index + 16 : index + 20], "big")
            duration = int.from_bytes(payload[index + 20 : index + 24], "big")
    except ValueError:  # pragma: no cover - defensive
        return None

    if timescale <= 0 or duration <= 0:
        return None
    return round(duration / timescale, 3)


def probe_duration_s(path: str) -> float | None:
    """Return the container duration in seconds, or ``None`` if unknown."""
    file_size = os.path.getsize(path)
    moov_payload: bytes | None = None

    with open(path, "rb") as handle:
        for offset, box_type, size, header_size in _iter_top_level_boxes(handle, file_size):
            if box_type != b"moov":
                continue
            payload_size = size - header_size
            if payload_size > _MAX_MOOV_BYTES:
                return None
            handle.seek(offset + header_size)
            moov_payload = handle.read(payload_size)
            break

    if moov_payload is None:
        return None
    return _duration_from_mvhd(moov_payload)


def probe_video(
    path: str, *, display_name: str, allowed_extensions: tuple[str, ...]
) -> float | None:
    """Validate a stored file and return its duration.

    Raises
    ------
    UnsupportedVideoFormatError
        Extension not allowed, or the content is not an ISO-BMFF container.
    InvalidVideoRequestError
        The file is empty.
    """
    extension = storage_files.file_extension(display_name)
    if extension not in allowed_extensions:
        raise UnsupportedVideoFormatError(
            details={"extension": extension, "allowed": list(allowed_extensions)}
        )

    size = os.path.getsize(path)
    if size == 0:
        raise InvalidVideoRequestError("视频文件为空", details={"field": "file"})

    with open(path, "rb") as handle:
        head = handle.read(16)

    if not looks_like_iso_bmff(head):
        raise UnsupportedVideoFormatError(
            details={"reason": "not_iso_bmff", "allowed": list(allowed_extensions)}
        )

    return probe_duration_s(path)
