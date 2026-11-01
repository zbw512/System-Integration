"""Anonymous-session claim and ownership-transfer tests."""

from __future__ import annotations

import io
import sqlite3

from media_fixtures import make_minimal_mp4
from services.auth_service import SESSION_COOKIE_NAME
from services.guest_session_service import GUEST_COOKIE_NAME


def register(client, username: str):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "claim-test-password",
            "display_name": username,
        },
    )
    assert response.status_code == 201
    return response


def login(client, username: str):
    return client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "claim-test-password",
        },
    )


def create_anonymous_job(client, drain, name: str):
    upload = client.post(
        "/api/v1/videos/upload",
        data={"file": (io.BytesIO(make_minimal_mp4(3.0)), name)},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    video_id = upload.get_json()["video_id"]
    job = client.post(f"/api/v1/videos/{video_id}/process")
    assert job.status_code == 202
    drain()
    return video_id, job.get_json()["job_id"]


def test_login_claims_only_the_current_browser_guest_resources(app, drain):
    account_client = app.test_client()
    register(account_client, "claim_owner")

    anonymous = app.test_client()
    video_id, job_id = create_anonymous_job(
        anonymous,
        drain,
        "anonymous-claim.mp4",
    )
    guest_cookie = anonymous.get_cookie(GUEST_COOKIE_NAME)
    assert guest_cookie is not None

    login_response = login(anonymous, "claim_owner")
    assert login_response.status_code == 200
    assert login_response.get_json()["guest_claim"] == {
        "videos": 1,
        "jobs": 1,
    }

    history = anonymous.get("/api/v1/history").get_json()
    assert history["pagination"]["total"] == 1
    assert history["items"][0]["video_id"] == video_id
    assert history["items"][0]["job_id"] == job_id
    assert anonymous.get(f"/api/v1/videos/{video_id}").status_code == 200
    assert anonymous.get(f"/api/v1/jobs/{job_id}").status_code == 200

    connection = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    owner = connection.execute(
        "SELECT user_id FROM users WHERE username_key = 'claim_owner'"
    ).fetchone()[0]
    assert connection.execute(
        "SELECT user_id, guest_id FROM videos WHERE video_id = ?",
        (video_id,),
    ).fetchone() == (owner, None)
    assert connection.execute(
        "SELECT user_id, guest_id FROM jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone() == (owner, None)
    claimed_session = connection.execute(
        "SELECT claimed_by_user_id, revoked_at FROM guest_sessions "
        "WHERE claimed_by_user_id = ?",
        (owner,),
    ).fetchone()
    connection.close()
    assert claimed_session is not None
    assert claimed_session[0] == owner
    assert claimed_session[1] is not None

    stale_guest = app.test_client()
    stale_guest.set_cookie(GUEST_COOKIE_NAME, guest_cookie.value)
    assert stale_guest.get(f"/api/v1/videos/{video_id}").status_code == 404

    # Reusing the old anonymous token cannot transfer the same data again.
    session_cookie = anonymous.get_cookie(SESSION_COOKIE_NAME)
    assert session_cookie is not None
    replay = app.test_client()
    replay.set_cookie(SESSION_COOKIE_NAME, session_cookie.value)
    replay.set_cookie(GUEST_COOKIE_NAME, guest_cookie.value)
    replay_claim = replay.post("/api/v1/auth/claim-anonymous")
    assert replay_claim.status_code == 200
    assert replay_claim.get_json()["guest_claim"] == {
        "videos": 0,
        "jobs": 0,
    }
    assert replay.get("/api/v1/history").get_json()["pagination"]["total"] == 1


def test_claim_cannot_take_another_anonymous_browsers_resources(app, drain):
    first_account = app.test_client()
    second_account = app.test_client()
    register(first_account, "first_claim_user")
    register(second_account, "second_claim_user")

    first_anonymous = app.test_client()
    second_anonymous = app.test_client()
    first_video, first_job = create_anonymous_job(
        first_anonymous,
        drain,
        "first-anonymous.mp4",
    )
    second_video, second_job = create_anonymous_job(
        second_anonymous,
        drain,
        "second-anonymous.mp4",
    )

    first_login = login(first_anonymous, "first_claim_user")
    second_login = login(second_anonymous, "second_claim_user")
    assert first_login.get_json()["guest_claim"]["jobs"] == 1
    assert second_login.get_json()["guest_claim"]["jobs"] == 1

    first_history = first_anonymous.get("/api/v1/history").get_json()["items"]
    second_history = second_anonymous.get("/api/v1/history").get_json()["items"]
    assert [item["video_id"] for item in first_history] == [first_video]
    assert [item["video_id"] for item in second_history] == [second_video]
    assert first_anonymous.get(f"/api/v1/jobs/{second_job}").status_code == 404
    assert second_anonymous.get(f"/api/v1/jobs/{first_job}").status_code == 404


def test_claim_moves_all_resources_from_one_guest_session(app, drain):
    account_client = app.test_client()
    register(account_client, "multi_claim_user")
    anonymous = app.test_client()

    first_video, first_job = create_anonymous_job(
        anonymous,
        drain,
        "multi-first.mp4",
    )
    second_video, second_job = create_anonymous_job(
        anonymous,
        drain,
        "multi-second.mp4",
    )

    response = login(anonymous, "multi_claim_user")
    assert response.get_json()["guest_claim"] == {
        "videos": 2,
        "jobs": 2,
    }
    history = anonymous.get("/api/v1/history").get_json()
    assert {
        item["video_id"] for item in history["items"]
    } == {first_video, second_video}
    assert {
        item["job_id"] for item in history["items"]
    } == {first_job, second_job}


def test_login_without_guest_cookie_claims_nothing(client):
    register(client, "no_guest_user")
    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200

    response = login(client, "no_guest_user")
    assert response.status_code == 200
    assert response.get_json()["guest_claim"] == {
        "videos": 0,
        "jobs": 0,
    }
