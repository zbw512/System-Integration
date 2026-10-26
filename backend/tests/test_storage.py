"""Unit tests for the storage layer (SQLite repository + file helpers).

These are deliberately HTTP-free: they pin down the persistence contract that
the API tests rely on.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from schemas.video import Video
from services.errors import DuplicateVideoError, PayloadTooLargeError
from storage import db as storage_db
from storage import files as storage_files
from storage.repositories import VideoRepository

DB_FILENAME = "app.db"


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = tmp_path / DB_FILENAME
    storage_db.init_db(str(path))
    return str(path)


@pytest.fixture()
def repository(db_path: str) -> VideoRepository:
    return VideoRepository(db_path)


def make_video(video_id: str = "vid_test000001", **overrides) -> Video:
    payload = {
        "video_id": video_id,
        "name": "clip.mp4",
        "source": "upload",
        "status": "registered",
        "size_bytes": 148,
        "created_at": "2026-10-22T00:00:00Z",
        "duration_s": 3.0,
        "file_url": f"/api/v1/videos/{video_id}/file",
        "metadata": {"sha256": "deadbeef"},
        "storage_path": f"videos/{video_id}.mp4",
    }
    payload.update(overrides)
    return Video(**payload)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def test_init_db_is_idempotent(db_path: str):
    storage_db.init_db(db_path)
    storage_db.init_db(db_path)
    assert storage_db.ping(db_path) is True


def test_ping_returns_false_for_unusable_path(tmp_path: Path):
    # A directory where the database file should be cannot be opened.
    broken = tmp_path / "dir.db"
    broken.mkdir()
    assert storage_db.ping(str(broken)) is False


# --------------------------------------------------------------------------- #
# Repository
# --------------------------------------------------------------------------- #
def test_create_and_get_roundtrip(repository: VideoRepository):
    video = make_video()

    repository.create(video)
    loaded = repository.get(video.video_id)

    assert loaded is not None
    assert loaded.video_id == video.video_id
    assert loaded.name == "clip.mp4"
    assert loaded.source.value == "upload"
    assert loaded.status.value == "registered"
    assert loaded.duration_s == 3.0
    assert loaded.size_bytes == 148
    assert loaded.metadata["sha256"] == "deadbeef"
    assert loaded.prediction_source.value == "none"
    assert loaded.evaluation_eligible is False
    assert loaded.segments == []
    assert loaded.model is None


def test_get_missing_returns_none(repository: VideoRepository):
    assert repository.get("vid_missing") is None


def test_exists(repository: VideoRepository):
    assert repository.exists("vid_test000001") is False
    repository.create(make_video())
    assert repository.exists("vid_test000001") is True


def test_duplicate_id_is_rejected(repository: VideoRepository):
    repository.create(make_video())

    with pytest.raises(DuplicateVideoError):
        repository.create(make_video())


def test_list_orders_and_paginates(repository: VideoRepository):
    repository.create(make_video("vid_a", created_at="2026-10-22T00:00:01Z"))
    repository.create(make_video("vid_b", created_at="2026-10-22T00:00:03Z"))
    repository.create(make_video("vid_c", created_at="2026-10-22T00:00:02Z"))

    first_page, total = repository.list(limit=2, offset=0)
    second_page, _ = repository.list(limit=2, offset=2)

    assert total == 3
    # Newest first.
    assert [item.video_id for item in first_page] == ["vid_b", "vid_c"]
    assert [item.video_id for item in second_page] == ["vid_a"]


def test_list_filters(repository: VideoRepository):
    repository.create(make_video("vid_a", status="registered"))
    repository.create(make_video("vid_b", status="processed", source="sav_clip"))

    registered, total_registered = repository.list(limit=10, offset=0, status="registered")
    sav, total_sav = repository.list(limit=10, offset=0, source="sav_clip")

    assert total_registered == 1
    assert [item.video_id for item in registered] == ["vid_a"]
    assert total_sav == 1
    assert [item.video_id for item in sav] == ["vid_b"]


def test_count(repository: VideoRepository):
    assert repository.count() == 0
    repository.create(make_video())
    assert repository.count() == 1


def test_evaluation_eligibility_is_derived_not_stored(repository: VideoRepository):
    # A caller cannot force eligibility: it is recomputed from the source.
    repository.create(
        make_video(
            "vid_oracle",
            prediction_source="oracle",
            provider="sav_label_lookup",
            evaluation_eligible=True,
        )
    )
    loaded = repository.get("vid_oracle")

    assert loaded is not None
    assert loaded.prediction_source.value == "oracle"
    assert loaded.evaluation_eligible is False


# --------------------------------------------------------------------------- #
# File helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lesson.mp4", "lesson.mp4"),
        ("../../etc/passwd.mp4", "passwd.mp4"),
        ("C:\\temp\\clip.mp4", "clip.mp4"),
        ("with\x00null.mp4", "withnull.mp4"),
        ("  spaced.mp4  ", "spaced.mp4"),
        ('bad:"name"*.mp4', "bad__name__.mp4"),
    ],
)
def test_sanitize_name_strips_paths_and_control_chars(raw, expected):
    assert storage_files.sanitize_name(raw) == expected


def test_sanitize_name_of_pure_path_returns_empty():
    assert storage_files.sanitize_name("../") == ""


@pytest.mark.parametrize(
    ("root", "candidate", "expected"),
    [
        ("data", "data/videos/a.mp4", True),
        ("data", "data", True),
        ("data", "data/../secret.mp4", False),
        ("data", "other/a.mp4", False),
    ],
)
def test_is_within(tmp_path: Path, root, candidate, expected):
    assert storage_files.is_within(str(tmp_path / root), str(tmp_path / candidate)) is expected


def test_resolve_stored_path_rejects_escape(tmp_path: Path):
    data_dir = str(tmp_path / "data")

    with pytest.raises(storage_files.PathEscapeError):
        storage_files.resolve_stored_path(data_dir, "../../etc/passwd")

    resolved = storage_files.resolve_stored_path(data_dir, "videos/a.mp4")
    assert resolved.endswith("a.mp4")


def test_resolve_stored_path_rejects_empty(tmp_path: Path):
    with pytest.raises(storage_files.PathEscapeError):
        storage_files.resolve_stored_path(str(tmp_path), "")


def test_save_stream_writes_file_and_hash(tmp_path: Path):
    destination = tmp_path / "videos" / "clip.mp4"

    size, digest = storage_files.save_stream(io.BytesIO(b"abcdef"), str(destination))

    assert size == 6
    assert destination.read_bytes() == b"abcdef"
    assert len(digest) == 64
    assert not Path(str(destination) + ".part").exists()


def test_save_stream_enforces_size_limit_and_cleans_up(tmp_path: Path):
    destination = tmp_path / "videos" / "clip.mp4"

    with pytest.raises(PayloadTooLargeError):
        storage_files.save_stream(io.BytesIO(b"x" * 2000), str(destination), max_bytes=1000)

    assert not destination.exists()
    assert not Path(str(destination) + ".part").exists()


def test_copy_into_store_preserves_source(tmp_path: Path):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"hello")
    destination = tmp_path / "store" / "dst.mp4"

    size, _ = storage_files.copy_into_store(str(source), str(destination))

    assert size == 5
    assert destination.read_bytes() == b"hello"
    assert source.read_bytes() == b"hello"


def test_ensure_storage_dirs_creates_both(tmp_path: Path):
    root, videos = storage_files.ensure_storage_dirs(str(tmp_path / "data"), "videos")

    assert Path(root).is_dir()
    assert Path(videos).is_dir()


def test_to_relative_uses_forward_slashes(tmp_path: Path):
    data_dir = str(tmp_path / "data")
    absolute = str(Path(data_dir) / "videos" / "a.mp4")

    assert storage_files.to_relative(data_dir, absolute) == "videos/a.mp4"
