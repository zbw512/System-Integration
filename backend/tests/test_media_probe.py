"""Unit tests for the dependency-free media probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_fixtures import make_ftyp_only_mp4, write_minimal_mp4
from services.errors import InvalidVideoRequestError, UnsupportedVideoFormatError
from services.media_probe import looks_like_iso_bmff, probe_duration_s, probe_video

ALLOWED = (".mp4", ".m4v", ".mov")


def test_looks_like_iso_bmff_detects_ftyp():
    assert looks_like_iso_bmff(b"\x00\x00\x00\x20ftypisom") is True
    assert looks_like_iso_bmff(b"RIFF....AVI ") is False
    assert looks_like_iso_bmff(b"short") is False


def test_probe_duration_reads_mvhd(tmp_path: Path):
    path = write_minimal_mp4(tmp_path / "clip.mp4", 3.0)

    assert probe_duration_s(str(path)) == 3.0


def test_probe_duration_supports_fractional_values(tmp_path: Path):
    path = write_minimal_mp4(tmp_path / "clip.mp4", 2.5)

    assert probe_duration_s(str(path)) == 2.5


def test_probe_duration_without_moov_returns_none(tmp_path: Path):
    path = tmp_path / "no_moov.mp4"
    path.write_bytes(make_ftyp_only_mp4())

    assert probe_duration_s(str(path)) is None


def test_probe_video_returns_duration(tmp_path: Path):
    path = write_minimal_mp4(tmp_path / "clip.mp4", 3.0)

    assert probe_video(str(path), display_name="clip.mp4", allowed_extensions=ALLOWED) == 3.0


def test_probe_video_rejects_unsupported_extension(tmp_path: Path):
    path = write_minimal_mp4(tmp_path / "clip.avi")

    with pytest.raises(UnsupportedVideoFormatError) as excinfo:
        probe_video(str(path), display_name="clip.avi", allowed_extensions=ALLOWED)

    assert excinfo.value.details["extension"] == ".avi"


def test_probe_video_rejects_non_container_content(tmp_path: Path):
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"just some text, definitely not a video")

    with pytest.raises(UnsupportedVideoFormatError) as excinfo:
        probe_video(str(path), display_name="fake.mp4", allowed_extensions=ALLOWED)

    assert excinfo.value.details["reason"] == "not_iso_bmff"


def test_probe_video_rejects_empty_file(tmp_path: Path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")

    with pytest.raises(InvalidVideoRequestError):
        probe_video(str(path), display_name="empty.mp4", allowed_extensions=ALLOWED)


def test_probe_video_accepts_container_without_duration(tmp_path: Path):
    path = tmp_path / "nodur.mp4"
    path.write_bytes(make_ftyp_only_mp4())

    # ``duration_s`` may legitimately be null (standard 3.1).
    assert probe_video(str(path), display_name="nodur.mp4", allowed_extensions=ALLOWED) is None
