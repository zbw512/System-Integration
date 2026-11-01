"""Compatibility tests for records created before anonymous ownership existed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import create_app
from config import Config


OLD_SCHEMA = (
    """
    CREATE TABLE videos (
        video_id            TEXT PRIMARY KEY,
        name                TEXT NOT NULL,
        source              TEXT NOT NULL,
        status              TEXT NOT NULL,
        duration_s          REAL,
        size_bytes          INTEGER NOT NULL,
        created_at          TEXT NOT NULL,
        file_url            TEXT,
        prediction_source   TEXT NOT NULL DEFAULT 'none',
        provider            TEXT,
        evaluation_eligible INTEGER NOT NULL DEFAULT 0,
        model_json          TEXT,
        segments_json       TEXT NOT NULL DEFAULT '[]',
        metadata_json       TEXT NOT NULL DEFAULT '{}',
        storage_path        TEXT,
        user_id             TEXT
    )
    """,
    """
    CREATE TABLE jobs (
        job_id        TEXT PRIMARY KEY,
        job_type      TEXT NOT NULL,
        status        TEXT NOT NULL,
        stage         TEXT NOT NULL,
        progress      REAL NOT NULL,
        video_id      TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        started_at    TEXT,
        finished_at   TEXT,
        result_json   TEXT,
        error_json    TEXT,
        provider      TEXT,
        model_json    TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        user_id       TEXT
    )
    """,
)


def test_old_rows_survive_migration_and_remain_unassigned(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    connection = sqlite3.connect(db_path)
    for statement in OLD_SCHEMA:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO videos "
        "(video_id, name, source, status, size_bytes, created_at, storage_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "vid_legacy001",
            "legacy.mp4",
            "upload",
            "processed",
            148,
            "2026-10-01T00:00:00Z",
            "videos/vid_legacy001.mp4",
        ),
    )
    connection.execute(
        "INSERT INTO jobs "
        "(job_id, job_type, status, stage, progress, video_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "job_legacy001",
            "video_process",
            "completed",
            "done",
            1.0,
            "vid_legacy001",
            "2026-10-01T00:00:00Z",
        ),
    )
    connection.commit()
    connection.close()

    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(data_dir),
        job_worker_enabled=False,
    )
    app = create_app(config)
    client = app.test_client()

    assert client.get("/api/v1/videos/vid_legacy001").status_code == 404
    assert client.get("/api/v1/videos/vid_legacy001/file").status_code == 404
    assert client.get("/api/v1/videos/vid_legacy001/results").status_code == 404
    assert client.get("/api/v1/jobs/job_legacy001").status_code == 404
    assert client.get("/api/v1/videos").get_json()["items"] == []
    assert client.get("/api/v1/jobs").get_json()["items"] == []

    check = sqlite3.connect(db_path)
    video_columns = {
        row[1] for row in check.execute("PRAGMA table_info(videos)")
    }
    job_columns = {
        row[1] for row in check.execute("PRAGMA table_info(jobs)")
    }
    assert "guest_id" in video_columns
    assert "guest_id" in job_columns
    assert check.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert check.execute(
        "SELECT user_id, guest_id FROM videos WHERE video_id = 'vid_legacy001'"
    ).fetchone() == (None, None)
    assert check.execute(
        "SELECT user_id, guest_id FROM jobs WHERE job_id = 'job_legacy001'"
    ).fetchone() == (None, None)
    migration = check.execute(
        "SELECT version FROM schema_migrations "
        "WHERE version = '0002_resource_ownership'"
    ).fetchone()
    assert migration == ("0002_resource_ownership",)
    check.close()

    # A second startup is idempotent and does not assign the legacy records.
    second_client = create_app(config).test_client()
    assert second_client.get("/api/v1/videos/vid_legacy001").status_code == 404
