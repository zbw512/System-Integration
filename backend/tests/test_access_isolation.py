"""Cross-user and cross-anonymous resource isolation tests."""

from __future__ import annotations

import io
import sqlite3

from assertions import assert_unified_error
from media_fixtures import make_minimal_mp4
from services.guest_session_service import GUEST_COOKIE_NAME


def register(client, username: str):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "isolation-pass",
            "display_name": username,
        },
    )
    assert response.status_code == 201
    return response


def upload(client, name: str = "classroom.mp4") -> str:
    response = client.post(
        "/api/v1/videos/upload",
        data={"file": (io.BytesIO(make_minimal_mp4(3.0)), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()["video_id"]


def process(client, video_id: str) -> str:
    response = client.post(f"/api/v1/videos/{video_id}/process")
    assert response.status_code == 202
    return response.get_json()["job_id"]


def test_user_can_access_own_video_job_and_result(client, drain):
    register(client, "owner_a")
    video_id = upload(client)
    job_id = process(client, video_id)
    drain()

    assert client.get(f"/api/v1/videos/{video_id}").status_code == 200
    file_response = client.get(f"/api/v1/videos/{video_id}/file")
    assert file_response.status_code == 200
    assert "no-store" in file_response.headers["Cache-Control"]
    assert "Cookie" in file_response.headers["Vary"]
    assert client.get(f"/api/v1/videos/{video_id}/results").status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200


def test_user_cannot_read_another_users_video_job_or_result(app, drain):
    owner = app.test_client()
    attacker = app.test_client()
    register(owner, "owner_a")
    register(attacker, "attacker_b")

    video_id = upload(owner)
    job_id = process(owner, video_id)
    drain()

    for path in (
        f"/api/v1/videos/{video_id}",
        f"/api/v1/videos/{video_id}/file",
        f"/api/v1/videos/{video_id}/results",
        f"/api/v1/jobs/{job_id}",
    ):
        error = assert_unified_error(
            attacker.get(path),
            status=404,
        )
        assert error["details"]["resource"] in {"video", "job"}

    assert attacker.get(
        f"/api/v1/videos/{video_id}/results?format=csv"
    ).status_code == 404


def test_user_lists_are_scoped_and_foreign_filters_reveal_nothing(app):
    owner = app.test_client()
    other = app.test_client()
    register(owner, "owner_a")
    register(other, "owner_b")

    owner_video = upload(owner, "owner.mp4")
    other_video = upload(other, "other.mp4")
    owner_job = process(owner, owner_video)
    other_job = process(other, other_video)

    owner_videos = owner.get("/api/v1/videos").get_json()
    owner_jobs = owner.get("/api/v1/jobs").get_json()
    foreign_video_filter = owner.get(
        f"/api/v1/jobs?video_id={other_video}"
    ).get_json()

    assert [item["video_id"] for item in owner_videos["items"]] == [owner_video]
    assert owner_videos["pagination"]["total"] == 1
    assert [item["job_id"] for item in owner_jobs["items"]] == [owner_job]
    assert owner_jobs["pagination"]["total"] == 1
    assert foreign_video_filter["items"] == []
    assert foreign_video_filter["pagination"]["total"] == 0
    assert other_job not in owner_jobs["items"]


def test_user_cannot_process_another_users_video(app, drain):
    owner = app.test_client()
    attacker = app.test_client()
    register(owner, "owner_a")
    register(attacker, "attacker_b")
    video_id = upload(owner)

    before = owner.get(f"/api/v1/videos/{video_id}").get_json()
    assert_unified_error(
        attacker.post(f"/api/v1/videos/{video_id}/process"),
        status=404,
        code="VIDEO_NOT_FOUND",
    )
    after = owner.get(f"/api/v1/videos/{video_id}").get_json()

    assert after["status"] == before["status"] == "registered"
    assert after["segments"] == before["segments"] == []
    assert owner.get("/api/v1/jobs").get_json()["pagination"]["total"] == 0


def test_anonymous_can_complete_the_normal_analysis_flow(client, drain):
    upload_response = client.post(
        "/api/v1/videos/upload",
        data={"file": (io.BytesIO(make_minimal_mp4(3.0)), "anonymous.mp4")},
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 201
    cookie = upload_response.headers["Set-Cookie"]
    assert f"{GUEST_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "gst_" not in upload_response.get_data(as_text=True)

    video_id = upload_response.get_json()["video_id"]
    job_id = process(client, video_id)
    drain()

    assert client.get(f"/api/v1/videos/{video_id}").status_code == 200
    assert client.get(f"/api/v1/videos/{video_id}/file").status_code == 200
    assert client.get(f"/api/v1/videos/{video_id}/results").status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200


def test_anonymous_sessions_are_isolated(app):
    first = app.test_client()
    second = app.test_client()

    first_video = upload(first, "first-anonymous.mp4")
    second_video = upload(second, "second-anonymous.mp4")
    first_job = process(first, first_video)

    assert_unified_error(
        second.get(f"/api/v1/videos/{first_video}"),
        status=404,
        code="VIDEO_NOT_FOUND",
    )
    assert second.get(f"/api/v1/videos/{first_video}/file").status_code == 404
    assert second.get(f"/api/v1/videos/{first_video}/results").status_code == 404
    assert_unified_error(
        second.get(f"/api/v1/jobs/{first_job}"),
        status=404,
        code="JOB_NOT_FOUND",
    )
    assert_unified_error(
        second.post(f"/api/v1/videos/{first_video}/process"),
        status=404,
        code="VIDEO_NOT_FOUND",
    )

    assert first.get("/api/v1/videos").get_json()["pagination"]["total"] == 1
    assert second.get("/api/v1/videos").get_json()["pagination"]["total"] == 1
    assert first_video not in str(second.get("/api/v1/videos").get_json())
    assert second_video not in str(first.get("/api/v1/videos").get_json())


def test_user_and_anonymous_namespaces_do_not_cross(app):
    anonymous = app.test_client()
    user = app.test_client()

    anonymous_video = upload(anonymous, "anonymous.mp4")
    register(user, "signed_in_user")
    user_video = upload(user, "signed-in.mp4")

    assert user.get(f"/api/v1/videos/{anonymous_video}").status_code == 404
    assert anonymous.get(f"/api/v1/videos/{user_video}").status_code == 404


def test_request_without_guest_cookie_cannot_use_guessed_ids(app):
    owner = app.test_client()
    no_cookie = app.test_client()
    video_id = upload(owner)
    job_id = process(owner, video_id)

    assert no_cookie.get(f"/api/v1/videos/{video_id}").status_code == 404
    assert no_cookie.get(f"/api/v1/videos/{video_id}/file").status_code == 404
    assert no_cookie.get(f"/api/v1/videos/{video_id}/results").status_code == 404
    assert no_cookie.get(f"/api/v1/jobs/{job_id}").status_code == 404
    assert no_cookie.get("/api/v1/videos").get_json()["items"] == []
    assert no_cookie.get("/api/v1/jobs").get_json()["items"] == []


def test_unauthorized_file_range_returns_no_media_bytes(app):
    owner = app.test_client()
    other = app.test_client()
    register(owner, "owner_a")
    register(other, "other_b")
    video_id = upload(owner)

    response = other.get(
        f"/api/v1/videos/{video_id}/file",
        headers={"Range": "bytes=0-9"},
    )

    assert response.status_code == 404
    assert response.mimetype == "application/json"
    assert response.data != b"\x00" * 10
    assert "no-store" in response.headers["Cache-Control"]
    assert "Cookie" in response.headers["Vary"]


def test_revoked_anonymous_session_loses_access(app):
    client = app.test_client()
    video_id = upload(client)
    guest_cookie = client.get_cookie(GUEST_COOKIE_NAME)
    assert guest_cookie is not None
    assert client.get(f"/api/v1/videos/{video_id}").status_code == 200

    app.extensions["guest_session_service"].revoke(guest_cookie.value)

    assert client.get(f"/api/v1/videos/{video_id}").status_code == 404
    assert client.get(f"/api/v1/jobs").get_json()["items"] == []


def test_anonymous_token_is_not_stored_in_plaintext(app):
    client = app.test_client()
    upload(client)
    token = client.get_cookie(GUEST_COOKIE_NAME).value

    connection = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    stored = connection.execute(
        "SELECT token_hash FROM guest_sessions"
    ).fetchone()[0]
    connection.close()

    assert stored != token
    assert len(stored) == 64
    assert token not in stored


def test_register_requires_login(client, import_root):
    source = import_root / "local.mp4"
    source.write_bytes(make_minimal_mp4(3.0))

    assert_unified_error(
        client.post(
            "/api/v1/videos/register",
            json={"source": "local_path", "path": str(source)},
        ),
        status=401,
        code="AUTHENTICATION_REQUIRED",
    )
