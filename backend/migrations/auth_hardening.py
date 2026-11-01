"""Persistence for authentication throttling."""

from __future__ import annotations

import sqlite3

from common.timeutil import utc_timestamp

MIGRATION_VERSION = "0003_auth_hardening"


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_rate_limits (
            key_hash         TEXT PRIMARY KEY,
            attempts         INTEGER NOT NULL DEFAULT 0,
            window_started_at TEXT NOT NULL,
            blocked_until    TEXT,
            updated_at       TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_rate_limits_updated "
        "ON auth_rate_limits(updated_at)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, utc_timestamp()),
    )
