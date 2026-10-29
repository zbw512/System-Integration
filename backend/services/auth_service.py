"""Minimal local account and session service.

This is intentionally a local-first identity layer: accounts and opaque
sessions are persisted in SQLite, passwords use PBKDF2-SHA256, and the browser
receives only a random HttpOnly session token. It is sufficient for personal
analysis history without introducing a new framework or external identity
provider.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from common.timeutil import utc_timestamp
from services.errors import (
    InvalidAccountRequestError,
    InvalidCredentialsError,
    UsernameTakenError,
)
from schemas.user import User
from storage.db import connect

SESSION_COOKIE_NAME = "learning_state_session"
SESSION_TTL_DAYS = 14

_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_USERNAME_PATTERN = re.compile(r"^[^\s\x00-\x1f\x7f]{2,32}$")


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _normalize_username(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidAccountRequestError(
            "请输入用户名",
            details={"field": "username"},
        )
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidAccountRequestError(
            "用户名需为 2-32 个字符且不能包含空白",
            details={"field": "username", "min_length": 2, "max_length": 32},
        )
    return normalized


def _validate_password(value: object) -> str:
    if not isinstance(value, str) or not (8 <= len(value) <= 128):
        raise InvalidAccountRequestError(
            "密码长度需为 8-128 个字符",
            details={"field": "password", "min_length": 8, "max_length": 128},
        )
    return value


def _normalize_display_name(value: object, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise InvalidAccountRequestError(
            "显示名称格式不正确",
            details={"field": "display_name"},
        )
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        return fallback
    if len(normalized) > 40:
        raise InvalidAccountRequestError(
            "显示名称不能超过 40 个字符",
            details={"field": "display_name", "max_length": 40},
        )
    return normalized


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_ITERATIONS,
    )
    return (
        f"{_PASSWORD_ALGORITHM}${_PASSWORD_ITERATIONS}$"
        f"{_base64url(salt)}${_base64url(digest)}"
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algorithm != _PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(
            salt_raw + "=" * (-len(salt_raw) % 4)
        )
        expected = base64.urlsafe_b64decode(
            digest_raw + "=" * (-len(digest_raw) % 4)
        )
    except (TypeError, ValueError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )


class AuthService:
    """Register users, verify credentials and manage opaque sessions."""

    session_ttl_days = SESSION_TTL_DAYS

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def register(
        self,
        *,
        username: object,
        password: object,
        display_name: object = None,
    ) -> User:
        normalized_username = _normalize_username(username)
        valid_password = _validate_password(password)
        normalized_display_name = _normalize_display_name(
            display_name,
            normalized_username,
        )
        user = User(
            user_id=f"usr_{uuid.uuid4().hex[:16]}",
            username=normalized_username,
            display_name=normalized_display_name,
            created_at=utc_timestamp(),
        )

        try:
            with connect(self._db_path) as connection:
                connection.execute(
                    "INSERT INTO users "
                    "(user_id, username, username_key, display_name, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        user.user_id,
                        user.username,
                        normalized_username.casefold(),
                        user.display_name,
                        _hash_password(valid_password),
                        user.created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise UsernameTakenError() from exc
        return user

    def authenticate(self, *, username: object, password: object) -> User:
        normalized_username = _normalize_username(username)
        if not isinstance(password, str) or not password:
            raise InvalidCredentialsError()

        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT user_id, username, display_name, created_at, password_hash "
                "FROM users WHERE username_key = ?",
                (normalized_username.casefold(),),
            ).fetchone()

        if row is None or not _verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError()
        return _row_to_user(row)

    def create_session(self, user_id: str) -> str:
        """Create a session and return the opaque token for an HttpOnly cookie."""

        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=self.session_ttl_days)
        with connect(self._db_path) as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (utc_timestamp(),),
            )
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    _token_hash(token),
                    user_id,
                    created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                ),
            )
        return token

    def get_user_for_session(self, token: str | None) -> User | None:
        if not token:
            return None
        with connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT u.user_id, u.username, u.display_name, u.created_at "
                "FROM sessions s JOIN users u ON u.user_id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (_token_hash(token), utc_timestamp()),
            ).fetchone()
        return _row_to_user(row) if row is not None else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with connect(self._db_path) as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (_token_hash(token),),
            )
