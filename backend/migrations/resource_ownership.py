"""Add user/anonymous ownership support without reassigning legacy rows."""

from __future__ import annotations

import sqlite3

from common.timeutil import utc_timestamp

MIGRATION_VERSION = "0002_resource_ownership"


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def apply(connection: sqlite3.Connection) -> None:
    """Apply the ownership schema.

    Existing rows intentionally remain ``user_id=NULL, guest_id=NULL``. They
    are legacy-unassigned records and are denied by all normal API queries.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_sessions (
            guest_id   TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_guest_sessions_expires "
        "ON guest_sessions(expires_at)"
    )

    _ensure_column(connection, "videos", "guest_id", "TEXT")
    _ensure_column(connection, "jobs", "guest_id", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_videos_user_created "
        "ON videos(user_id, created_at DESC, video_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_videos_guest_created "
        "ON videos(guest_id, created_at DESC, video_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_guest_created "
        "ON jobs(guest_id, created_at DESC, job_id)"
    )

    # A resource can never be assigned to both a user and a guest. Existing
    # NULL/NULL legacy rows are deliberately accepted so they remain intact.
    for table in ("videos", "jobs"):
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_owner_not_both_insert
            BEFORE INSERT ON {table}
            WHEN NEW.user_id IS NOT NULL AND NEW.guest_id IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{table}: user_id and guest_id are mutually exclusive');
            END
            """
        )
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_owner_not_both_update
            BEFORE UPDATE OF user_id, guest_id ON {table}
            WHEN NEW.user_id IS NOT NULL AND NEW.guest_id IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{table}: user_id and guest_id are mutually exclusive');
            END
            """
        )

    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, utc_timestamp()),
    )
