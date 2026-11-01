"""Opaque anonymous browser sessions.

Only a hash of the browser token is persisted. Anonymous resources are linked
to the generated ``guest_id`` and are inaccessible without the matching
HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from common.timeutil import utc_timestamp
from config import Config
from services.errors import StorageError
from storage.db import connect

GUEST_COOKIE_NAME = "learning_state_guest"


@dataclass(frozen=True)
class GuestSession:
    guest_id: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class GuestClaimResult:
    videos: int = 0
    jobs: int = 0


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_guest_session(row: sqlite3.Row) -> GuestSession:
    return GuestSession(
        guest_id=row["guest_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


class GuestSessionService:
    def __init__(self, config: Config) -> None:
        self._db_path = config.database_path
        self._ttl_hours = config.guest_session_ttl_hours

    @property
    def ttl_hours(self) -> int:
        return self._ttl_hours

    def create(self) -> tuple[GuestSession, str]:
        token = secrets.token_urlsafe(32)
        created = datetime.now(timezone.utc)
        expires = created + timedelta(hours=self._ttl_hours)
        created_at = created.isoformat(timespec="seconds").replace("+00:00", "Z")
        expires_at = expires.isoformat(timespec="seconds").replace("+00:00", "Z")
        guest_id = f"gst_{uuid.uuid4().hex[:20]}"

        try:
            with connect(self._db_path) as connection:
                connection.execute(
                    "DELETE FROM guest_sessions WHERE expires_at <= ?",
                    (utc_timestamp(),),
                )
                connection.execute(
                    "INSERT INTO guest_sessions "
                    "(guest_id, token_hash, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (guest_id, _hash_token(token), created_at, expires_at),
                )
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "guest_session_write_failed"}) from exc

        return (
            GuestSession(
                guest_id=guest_id,
                created_at=created_at,
                expires_at=expires_at,
            ),
            token,
        )

    def resolve(self, token: str | None) -> GuestSession | None:
        if not token:
            return None
        try:
            with connect(self._db_path) as connection:
                row = connection.execute(
                    "SELECT guest_id, created_at, expires_at "
                    "FROM guest_sessions "
                    "WHERE token_hash = ? AND expires_at > ? "
                    "AND revoked_at IS NULL",
                    (_hash_token(token), utc_timestamp()),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "guest_session_read_failed"}) from exc
        return _row_to_guest_session(row) if row is not None else None

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        try:
            with connect(self._db_path) as connection:
                connection.execute(
                    "UPDATE guest_sessions SET revoked_at = ? "
                    "WHERE token_hash = ? AND revoked_at IS NULL",
                    (utc_timestamp(), _hash_token(token)),
                )
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "guest_session_revoke_failed"}) from exc

    def claim_for_user(
        self,
        token: str | None,
        user_id: str,
    ) -> GuestClaimResult:
        """Atomically transfer one anonymous session's resources to a user."""

        if not token:
            return GuestClaimResult()

        now = utc_timestamp()
        try:
            with connect(self._db_path) as connection:
                guest = connection.execute(
                    "SELECT guest_id FROM guest_sessions "
                    "WHERE token_hash = ? AND expires_at > ? "
                    "AND revoked_at IS NULL AND claimed_by_user_id IS NULL",
                    (_hash_token(token), now),
                ).fetchone()
                if guest is None:
                    return GuestClaimResult()

                guest_id = guest["guest_id"]
                # Reserve the session first. A concurrent duplicate claim will
                # update zero rows and therefore cannot transfer resources.
                reserved = connection.execute(
                    "UPDATE guest_sessions "
                    "SET claimed_by_user_id = ?, claimed_at = ?, revoked_at = ? "
                    "WHERE guest_id = ? AND revoked_at IS NULL "
                    "AND claimed_by_user_id IS NULL",
                    (user_id, now, now, guest_id),
                )
                if reserved.rowcount != 1:
                    return GuestClaimResult()

                video_ids = [
                    row["video_id"]
                    for row in connection.execute(
                        "SELECT video_id FROM videos "
                        "WHERE guest_id = ? AND user_id IS NULL",
                        (guest_id,),
                    )
                ]
                if not video_ids:
                    return GuestClaimResult()

                placeholders = ", ".join("?" for _ in video_ids)
                inconsistent_job = connection.execute(
                    f"SELECT 1 FROM jobs j "
                    f"WHERE j.guest_id = ? AND ("
                    f"j.user_id IS NOT NULL OR j.video_id NOT IN ({placeholders})"
                    f") LIMIT 1",
                    (guest_id, *video_ids),
                ).fetchone()
                if inconsistent_job is not None:
                    raise StorageError(
                        details={"reason": "guest_owner_mismatch"}
                    )

                job_params = [user_id, guest_id, *video_ids]
                claimed_jobs = connection.execute(
                    f"UPDATE jobs SET user_id = ?, guest_id = NULL "
                    f"WHERE guest_id = ? AND user_id IS NULL "
                    f"AND video_id IN ({placeholders})",
                    job_params,
                ).rowcount
                claimed_videos = connection.execute(
                    f"UPDATE videos SET user_id = ?, guest_id = NULL "
                    f"WHERE video_id IN ({placeholders}) "
                    f"AND guest_id = ? AND user_id IS NULL",
                    [user_id, *video_ids, guest_id],
                ).rowcount
        except StorageError:
            raise
        except sqlite3.Error as exc:
            raise StorageError(details={"reason": "guest_claim_failed"}) from exc

        return GuestClaimResult(
            videos=int(claimed_videos),
            jobs=int(claimed_jobs),
        )
