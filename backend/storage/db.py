"""SQLite connection helpers and schema management (stdlib only).

SQLite is chosen deliberately: it needs no extra dependency, survives a service
restart (plain file), supports the pagination/filter queries the API needs, and
is more than adequate for a dataset of a few thousand clips.

Each operation opens its own short-lived connection, which keeps the service
free of cross-request connection state and is safe with the threaded Flask
development server.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS videos (
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
        storage_path        TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at DESC, video_id)",
    "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)",
    "CREATE INDEX IF NOT EXISTS idx_videos_source ON videos(source)",
    """
    CREATE TABLE IF NOT EXISTS jobs (
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
        FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC, job_id)",
)


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success and roll back on failure."""
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    connection = sqlite3.connect(db_path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(db_path: str) -> None:
    """Create tables and indexes if they do not exist yet."""
    with connect(db_path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)


def ping(db_path: str) -> bool:
    """Cheap readiness probe used by ``GET /health``."""
    try:
        with connect(db_path) as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except Exception:  # pragma: no cover - defensive
        return False
