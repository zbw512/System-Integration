"""File storage confined to the configured data directory.

Security rules implemented here:

* the on-disk name is derived only from the server-generated ``video_id`` and
  the validated extension — a client filename is never used as a path;
* every read resolves through :func:`resolve_stored_path`, which rejects any
  path that escapes the data directory (path traversal, symlink tricks,
  ``..`` segments, absolute paths);
* writes go to a ``.part`` file first and are renamed into place, so a failed
  upload cannot leave a half-written video behind.
"""

from __future__ import annotations

import hashlib
import os
import re

from services.errors import PayloadTooLargeError

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_MAX_NAME_LENGTH = 200
_CHUNK_SIZE = 1024 * 1024


class PathEscapeError(ValueError):
    """A stored path resolved outside the configured data directory."""


def ensure_storage_dirs(data_dir: str, video_subdir: str) -> tuple[str, str]:
    """Create the data directory (and video sub-directory); return both."""
    root = os.path.abspath(data_dir)
    videos = os.path.abspath(os.path.join(root, video_subdir))
    os.makedirs(videos, exist_ok=True)
    return root, videos


def is_within(root: str, path: str) -> bool:
    """Whether ``path`` is inside ``root`` after resolving symlinks."""
    try:
        root_real = os.path.realpath(root)
        path_real = os.path.realpath(path)
        return os.path.commonpath([root_real, path_real]) == root_real
    except (ValueError, OSError):
        # Different drive, unparsable path, ...
        return False


def resolve_stored_path(data_dir: str, relative_path: str) -> str:
    """Resolve a stored relative path, refusing anything outside ``data_dir``."""
    if not relative_path:
        raise PathEscapeError("存储路径为空")

    candidate = os.path.abspath(os.path.join(os.path.abspath(data_dir), relative_path))
    if not is_within(data_dir, candidate):
        raise PathEscapeError("存储路径越界")
    return candidate


def to_relative(data_dir: str, absolute_path: str) -> str:
    """Portable (forward-slash) path relative to the data directory."""
    relative = os.path.relpath(os.path.abspath(absolute_path), os.path.abspath(data_dir))
    return relative.replace("\\", "/")


def sanitize_name(raw: str) -> str:
    """Turn a client-supplied filename into a safe *display* name.

    Only used for the ``name`` field and the download filename; it never becomes
    part of a filesystem path.
    """
    if not isinstance(raw, str):
        return ""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name)
    name = _FORBIDDEN_NAME_CHARS.sub("_", name)
    name = name.strip().strip(".")
    if len(name) > _MAX_NAME_LENGTH:
        stem, extension = os.path.splitext(name)
        name = stem[: _MAX_NAME_LENGTH - len(extension)] + extension
    return name


def file_extension(name: str) -> str:
    """Lower-cased extension including the dot (``""`` when absent)."""
    return os.path.splitext(name or "")[1].lower()


def remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _write_stream(stream, dest_path: str, max_bytes: int | None) -> tuple[int, str]:
    directory = os.path.dirname(os.path.abspath(dest_path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    part_path = dest_path + ".part"
    digest = hashlib.sha256()
    total = 0

    try:
        with open(part_path, "wb") as handle:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise PayloadTooLargeError(
                        details={"limit_bytes": max_bytes, "received_bytes": total}
                    )
                digest.update(chunk)
                handle.write(chunk)
        os.replace(part_path, dest_path)
    except BaseException:
        remove_quietly(part_path)
        raise

    return total, digest.hexdigest()


def save_stream(stream, dest_path: str, *, max_bytes: int | None = None) -> tuple[int, str]:
    """Persist an upload stream; returns ``(size_bytes, sha256_hex)``."""
    return _write_stream(stream, dest_path, max_bytes)


def copy_into_store(
    source_path: str, dest_path: str, *, max_bytes: int | None = None
) -> tuple[int, str]:
    """Copy a local file into the store; returns ``(size_bytes, sha256_hex)``."""
    with open(source_path, "rb") as handle:
        return _write_stream(handle, dest_path, max_bytes)
