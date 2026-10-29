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
    CREATE TABLE IF NOT EXISTS users (
        user_id       TEXT PRIMARY KEY,
        username      TEXT NOT NULL,
        username_key  TEXT NOT NULL UNIQUE,
        display_name  TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """,
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
        storage_path        TEXT,
        user_id             TEXT
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
        user_id       TEXT,
        FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC, job_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
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

        # ``CREATE TABLE IF NOT EXISTS`` does not add columns to databases
        # created by an earlier release. Keep the migration intentionally tiny
        # and nullable so existing anonymous videos/jobs remain readable.
        for table in ("videos", "jobs"):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "user_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_created "
            "ON jobs(user_id, created_at DESC, job_id)"
        )


def ping(db_path: str) -> bool:
    """Cheap readiness probe used by ``GET /health``."""
    try:
        with connect(db_path) as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except Exception:  # pragma: no cover - defensive
        return False
