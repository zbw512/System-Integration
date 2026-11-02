"""Authentication, session and credential-safety tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app import create_app
from assertions import assert_unified_error
from config import Config
from services.auth_service import SESSION_COOKIE_NAME


def register(
    client,
    username: str = "secure_user",
    password: str = "correct-horse-battery",
):
    return client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "display_name": username,
        },
    )


def login(client, username: str = "secure_user", password: str = "correct-horse-battery"):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_password_salt_iterations_and_no_plaintext_storage(app):
    client = app.test_client()
    password = "unique-password-123"
    assert register(client, "salt_user_a", password).status_code == 201
    assert register(client, "salt_user_b", password).status_code == 201

    connection = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    rows = connection.execute(
        "SELECT password_hash FROM users ORDER BY username_key"
    ).fetchall()
    connection.close()

    first_hash, second_hash = (row[0] for row in rows)
    assert first_hash.startswith("pbkdf2_sha256$600000$")
    assert second_hash.startswith("pbkdf2_sha256$600000$")
    assert first_hash != second_hash
    assert password not in first_hash
    assert password not in second_hash


def test_wrong_password_returns_generic_error_without_secrets(client):
    assert register(client).status_code == 201
    response = login(client, password="wrong-password")
    unknown_response = login(client, username="no_such_user")

    error = assert_unified_error(
        response,
        status=401,
        code="INVALID_CREDENTIALS",
    )
    unknown_error = assert_unified_error(
        unknown_response,
        status=401,
        code="INVALID_CREDENTIALS",
    )
    raw = response.get_data(as_text=True).lower()
    assert error["message"] == "用户名或密码不正确"
    assert unknown_error["message"] == error["message"]
    assert "wrong-password" not in raw
    assert "pbkdf2" not in raw
    assert SESSION_COOKIE_NAME not in raw


def test_logout_revokes_the_current_server_side_session(client):
    assert register(client).status_code == 201
    session_cookie = client.get_cookie(SESSION_COOKIE_NAME)
    assert session_cookie is not None

    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").get_json()["authenticated"] is False

    stale_client = client.application.test_client()
    stale_client.set_cookie(SESSION_COOKIE_NAME, session_cookie.value)
    assert stale_client.get("/api/v1/auth/me").get_json()["authenticated"] is False
    assert_unified_error(
        stale_client.get("/api/v1/history"),
        status=401,
        code="AUTHENTICATION_REQUIRED",
    )


def test_session_token_is_stored_only_as_a_hash(app):
    client = app.test_client()
    assert register(client).status_code == 201
    token = client.get_cookie(SESSION_COOKIE_NAME).value

    connection = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    stored = connection.execute(
        "SELECT token_hash FROM sessions"
    ).fetchone()[0]
    connection.close()

    assert stored != token
    assert len(stored) == 64
    assert token not in stored


def test_expired_session_cannot_access_protected_endpoints(app):
    client = app.test_client()
    assert register(client).status_code == 201

    connection = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    connection.execute("UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00Z",))
    connection.commit()
    connection.close()

    assert client.get("/api/v1/auth/me").get_json()["authenticated"] is False
    assert_unified_error(
        client.get("/api/v1/history"),
        status=401,
        code="AUTHENTICATION_REQUIRED",
    )


def test_production_cookie_attributes(tmp_path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        environment="production",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
    )
    client = create_app(config).test_client()
    response = register(client)

    cookie = response.headers["Set-Cookie"]
    assert SESSION_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie


def test_development_cookie_does_not_force_secure_on_local_http(client):
    response = register(client)
    cookie = response.headers["Set-Cookie"]

    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_login_rotates_current_session_and_revokes_previous_token(app):
    client = app.test_client()
    assert register(client).status_code == 201
    old_cookie = client.get_cookie(SESSION_COOKIE_NAME)
    assert old_cookie is not None

    response = login(client)
    assert response.status_code == 200
    new_cookie = client.get_cookie(SESSION_COOKIE_NAME)
    assert new_cookie is not None
    assert new_cookie.value != old_cookie.value

    stale_client = app.test_client()
    stale_client.set_cookie(SESSION_COOKIE_NAME, old_cookie.value)
    assert stale_client.get("/api/v1/auth/me").get_json()["authenticated"] is False


def test_multiple_device_sessions_are_independent(app):
    first = app.test_client()
    second = app.test_client()
    assert register(first).status_code == 201
    assert login(second).status_code == 200

    first_token = first.get_cookie(SESSION_COOKIE_NAME).value
    second_token = second.get_cookie(SESSION_COOKIE_NAME).value
    assert first_token != second_token
    assert first.get("/api/v1/auth/me").get_json()["authenticated"] is True
    assert second.get("/api/v1/auth/me").get_json()["authenticated"] is True

    assert first.post("/api/v1/auth/logout").status_code == 200
    assert first.get("/api/v1/auth/me").get_json()["authenticated"] is False
    assert second.get("/api/v1/auth/me").get_json()["authenticated"] is True


def test_login_rate_limit_blocks_repeated_failures(app):
    config = app.config["APP_CONFIG"]
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=config.data_dir,
        job_worker_enabled=False,
        login_max_failures=3,
        login_window_seconds=900,
        login_block_seconds=900,
    )
    limited_app = create_app(config)
    client = limited_app.test_client()
    assert register(client).status_code == 201

    for _ in range(3):
        assert login(client, password="wrong-password").status_code == 401
    assert_unified_error(
        login(client),
        status=429,
        code="AUTH_RATE_LIMITED",
    )

    connection = sqlite3.connect(limited_app.config["APP_CONFIG"].database_path)
    expired = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    connection.execute(
        "UPDATE auth_rate_limits SET blocked_until = ? "
        "WHERE blocked_until IS NOT NULL",
        (expired,),
    )
    connection.commit()
    connection.close()

    assert login(client).status_code == 200


def test_registration_rate_limit_and_optional_registration_token(tmp_path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        job_worker_enabled=False,
        registration_max_attempts=3,
        registration_token="local-admin-token",
    )
    client = create_app(config).test_client()

    assert_unified_error(
        register(client, "first_user"),
        status=403,
        code="REGISTRATION_DENIED",
    )

    first = client.post(
        "/api/v1/auth/register",
        headers={"X-Registration-Token": "local-admin-token"},
        json={
            "username": "first_user",
            "password": "correct-horse-battery",
        },
    )
    second = client.post(
        "/api/v1/auth/register",
        headers={"X-Registration-Token": "local-admin-token"},
        json={
            "username": "second_user",
            "password": "correct-horse-battery",
        },
    )
    third = client.post(
        "/api/v1/auth/register",
        headers={"X-Registration-Token": "local-admin-token"},
        json={
            "username": "third_user",
            "password": "correct-horse-battery",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert_unified_error(
        third,
        status=429,
        code="AUTH_RATE_LIMITED",
    )


def test_cross_site_state_change_is_rejected(client):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Sec-Fetch-Site": "cross-site"},
        json={
            "username": "does-not-matter",
            "password": "does-not-matter",
        },
    )

    assert_unified_error(
        response,
        status=403,
        code="CROSS_SITE_REQUEST_BLOCKED",
    )
