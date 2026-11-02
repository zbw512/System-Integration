"""Track anonymous sessions that have been merged into user accounts."""

from __future__ import annotations

import sqlite3

from common.timeutil import utc_timestamp

MIGRATION_VERSION = "0004_guest_claim"


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
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def apply(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "guest_sessions", "claimed_by_user_id", "TEXT")
    _ensure_column(connection, "guest_sessions", "claimed_at", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_guest_sessions_claimed_by "
        "ON guest_sessions(claimed_by_user_id, claimed_at)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, utc_timestamp()),
    )
