"""Authentication and per-user analysis history integration tests."""

from __future__ import annotations

import io

from assertions import assert_unified_error
from media_fixtures import make_minimal_mp4


def register(client, username: str = "student_a", password: str = "analysis-pass"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "display_name": "学生 A",
        },
    )


def upload_video(client, name: str = "classroom.mp4") -> str:
    response = client.post(
        "/api/v1/videos/upload",
        data={"file": (io.BytesIO(make_minimal_mp4(3.0)), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def create_completed_job(client, drain, name: str = "classroom.mp4") -> str:
    video_id = upload_video(client, name=name)
    response = client.post(f"/api/v1/videos/{video_id}/process")
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    drain()
    return job_id


def test_register_login_me_and_logout(app):
    client = app.test_client()
    response = register(client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["authenticated"] is True
    assert body["user"]["username"] == "student_a"
    assert "password" not in str(body).lower()
    session_cookie = response.headers["Set-Cookie"]
    assert "learning_state_session" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["display_name"] == "学生 A"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.get_json()["authenticated"] is False
    assert client.get("/api/v1/auth/me").get_json()["authenticated"] is False

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "analysis-pass"},
    )
    assert login.status_code == 200
    assert login.get_json()["authenticated"] is True


def test_duplicate_username_and_wrong_password_are_rejected(app):
    first = app.test_client()
    assert register(first, username="same_user").status_code == 201

    second = app.test_client()
    duplicate = register(second, username="SAME_USER")
    assert_unified_error(duplicate, status=409, code="USERNAME_TAKEN")

    wrong = second.post(
        "/api/v1/auth/login",
        json={"username": "same_user", "password": "wrong-password"},
    )
    assert_unified_error(wrong, status=401, code="INVALID_CREDENTIALS")


def test_history_requires_login_and_is_scoped_to_user(app, drain):
    first = app.test_client()
    register(first, username="first_user")
    first_job = create_completed_job(first, drain, name="first.mp4")

    anonymous = app.test_client()
    create_completed_job(anonymous, drain, name="anonymous.mp4")

    second = app.test_client()
    register(second, username="second_user")
    second_job = create_completed_job(second, drain, name="second.mp4")

    unauthorized = anonymous.get("/api/v1/history")
    assert_unified_error(
        unauthorized,
        status=401,
        code="AUTHENTICATION_REQUIRED",
    )

    first_history = first.get("/api/v1/history").get_json()
    second_history = second.get("/api/v1/history").get_json()

    assert first_history["pagination"]["total"] == 1
    assert first_history["items"][0]["job_id"] == first_job
    assert first_history["items"][0]["video_name"] == "first.mp4"
    assert first_history["items"][0]["segment_count"] == 3
    assert "result" not in first_history["items"][0]

    assert second_history["pagination"]["total"] == 1
    assert second_history["items"][0]["job_id"] == second_job
    assert second_history["items"][0]["video_name"] == "second.mp4"


def test_history_rejects_invalid_pagination_and_does_not_leak_password(client):
    register(client)
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert_unified_error(
            client.get(f"/api/v1/history?{query}"),
            status=400,
            code="VALIDATION_ERROR",
        )

    body = client.get("/api/v1/auth/me").get_data(as_text=True).lower()
    assert "password" not in body
    assert "hash" not in body
