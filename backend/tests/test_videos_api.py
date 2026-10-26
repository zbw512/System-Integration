"""API tests for the P0-2 video endpoints.

Covers upload, registration, listing/pagination, detail, controlled file access
and the error cases required by the acceptance criteria (empty file, wrong
format, oversized file, duplicate id, unknown id, path traversal).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import create_app
from assertions import TIMESTAMP_RE, assert_unified_error
from config import Config
from media_fixtures import make_minimal_mp4, write_minimal_mp4

VIDEO_FIELDS = {
    "schema_version",
    "video_id",
    "name",
    "source",
    "status",
    "duration_s",
    "size_bytes",
    "created_at",
    "file_url",
    "prediction_source",
    "provider",
    "evaluation_eligible",
    "model",
    "segments",
    "metadata",
}


def upload(client, *, name: str = "lesson_clip.mp4", payload: bytes | None = None, field: str = "file"):
    data = {
        field: (
            io.BytesIO(make_minimal_mp4(3.0) if payload is None else payload),
            name,
        )
    }
    return client.post("/api/v1/videos/upload", data=data, content_type="multipart/form-data")


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
def test_upload_returns_registered_video(client):
    response = upload(client)

    assert response.status_code == 201
    body = response.get_json()

    assert set(body) == VIDEO_FIELDS, f"字段与标准不一致：{sorted(body)}"
    assert body["schema_version"] == "1.0"
    assert body["name"] == "lesson_clip.mp4"
    assert body["source"] == "upload"
    assert body["status"] == "registered"
    assert body["video_id"].startswith("vid_")
    assert body["file_url"] == f"/api/v1/videos/{body['video_id']}/file"
    assert TIMESTAMP_RE.match(body["created_at"])
    assert response.headers["Location"] == f"/api/v1/videos/{body['video_id']}"


def test_upload_records_real_size_and_duration(client):
    payload = make_minimal_mp4(3.0)
    body = upload(client, payload=payload).get_json()

    assert body["size_bytes"] == len(payload)
    assert body["duration_s"] == 3.0
    assert body["metadata"]["sha256"]
    assert body["metadata"]["original_filename"] == "lesson_clip.mp4"


def test_upload_does_not_fabricate_analysis(client):
    body = upload(client).get_json()

    # Nothing is analysed yet: no label, no model, no provider, no eligibility.
    assert body["prediction_source"] == "none"
    assert body["provider"] is None
    assert body["model"] is None
    assert body["segments"] == []
    assert body["evaluation_eligible"] is False


def test_uploaded_video_is_listed_and_fetchable(client):
    video_id = upload(client).get_json()["video_id"]

    listing = client.get("/api/v1/videos")
    assert listing.status_code == 200
    items = listing.get_json()["items"]
    assert [item["video_id"] for item in items] == [video_id]

    detail = client.get(f"/api/v1/videos/{video_id}")
    assert detail.status_code == 200
    assert detail.get_json()["video_id"] == video_id


def test_list_exposes_items_and_pagination_with_transition_alias(client):
    upload(client)
    body = client.get("/api/v1/videos").get_json()

    assert set(body) == {"items", "pagination", "videos"}
    assert body["videos"] == body["items"]
    assert body["pagination"] == {
        "limit": 50,
        "offset": 0,
        "total": 1,
        "has_next": False,
    }


def test_upload_without_file_returns_validation_error(client):
    response = client.post(
        "/api/v1/videos/upload",
        data={"other": (io.BytesIO(b"x"), "x.mp4")},
        content_type="multipart/form-data",
    )
    error = assert_unified_error(response, status=400, code="VALIDATION_ERROR")
    assert error["details"]["field"] == "file"


def test_upload_with_unsupported_extension_is_rejected(client):
    response = upload(client, name="clip.avi")

    error = assert_unified_error(response, status=415, code="UNSUPPORTED_VIDEO_FORMAT")
    assert error["details"]["extension"] == ".avi"


def test_upload_with_non_video_content_is_rejected(client):
    response = upload(client, name="clip.mp4", payload=b"this is not a video at all")

    error = assert_unified_error(response, status=415, code="UNSUPPORTED_VIDEO_FORMAT")
    assert error["details"]["reason"] == "not_iso_bmff"


def test_upload_with_empty_file_is_rejected(client):
    response = upload(client, name="empty.mp4", payload=b"")

    error = assert_unified_error(response, status=400, code="VALIDATION_ERROR")
    assert "空" in error["message"]


def test_upload_rejects_oversized_file(tmp_path: Path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        max_upload_bytes=1024,
    )
    client = create_app(config).test_client()

    response = upload(client, name="big.mp4", payload=make_minimal_mp4(3.0) + b"\x00" * 4096)

    assert response.status_code == 413
    assert_unified_error(response, code="PAYLOAD_TOO_LARGE")


def test_rejected_upload_leaves_no_file_behind(client, config):
    videos_dir = Path(config.videos_dir)

    upload(client, name="clip.avi")
    upload(client, name="clip.mp4", payload=b"not a video")
    upload(client, name="empty.mp4", payload=b"")

    leftovers = [path for path in videos_dir.rglob("*") if path.is_file()]
    assert leftovers == []


# --------------------------------------------------------------------------- #
# Register (local_path / sav_clip)
# --------------------------------------------------------------------------- #
def test_register_sav_clip_uses_sav_naming(client, import_root):
    source = write_minimal_mp4(import_root / "20181016_05_1064.mp4", 3.0)

    response = client.post(
        "/api/v1/videos/register",
        json={"source": "sav_clip", "path": str(source)},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["video_id"] == "sav_20181016_05_1064"
    assert body["source"] == "sav_clip"
    assert body["status"] == "registered"
    assert body["name"] == "20181016_05_1064.mp4"
    assert body["duration_s"] == 3.0
    assert body["prediction_source"] == "none"


def test_register_copies_file_into_data_dir(client, import_root, config):
    source = write_minimal_mp4(import_root / "clip_a.mp4")

    body = client.post(
        "/api/v1/videos/register",
        json={"source": "local_path", "path": str(source)},
    ).get_json()

    stored = Path(config.data_dir) / "videos" / f"{body['video_id']}.mp4"
    assert stored.is_file()
    assert source.is_file(), "登记不应删除原始文件"
    assert stored.read_bytes() == source.read_bytes()


def test_register_accepts_explicit_video_id(client, import_root):
    source = write_minimal_mp4(import_root / "clip_b.mp4")

    body = client.post(
        "/api/v1/videos/register",
        json={"source": "local_path", "path": str(source), "video_id": "my_clip_001"},
    ).get_json()

    assert body["video_id"] == "my_clip_001"


def test_register_duplicate_returns_conflict(client, import_root):
    source = write_minimal_mp4(import_root / "20181016_05_1064.mp4")
    payload = {"source": "sav_clip", "path": str(source)}

    assert client.post("/api/v1/videos/register", json=payload).status_code == 201
    response = client.post("/api/v1/videos/register", json=payload)

    error = assert_unified_error(response, status=409, code="VIDEO_ALREADY_EXISTS")
    assert error["details"]["video_id"] == "sav_20181016_05_1064"


def test_register_path_outside_allowed_roots_is_rejected(client, tmp_path):
    outside = write_minimal_mp4(tmp_path / "outside" / "secret.mp4")

    response = client.post(
        "/api/v1/videos/register",
        json={"source": "local_path", "path": str(outside)},
    )

    error = assert_unified_error(response, status=400, code="LOCAL_PATH_NOT_ALLOWED")
    assert error["details"]["field"] == "path"
    # The host path must not be echoed back.
    assert str(outside) not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "payload",
    [
        {"path": "x.mp4"},
        {"source": "upload", "path": "x.mp4"},
        {"source": "local_path"},
        {"source": "local_path", "path": ""},
        {"source": "local_path", "path": "x.mp4", "metadata": []},
    ],
)
def test_register_rejects_invalid_payloads(client, payload):
    response = client.post("/api/v1/videos/register", json=payload)

    # All of these are client errors; the exact code depends on which field is
    # wrong (e.g. a relative path outside the import roots is rejected as
    # LOCAL_PATH_NOT_ALLOWED rather than a generic validation error).
    assert response.status_code == 400
    assert_unified_error(response)


def test_register_rejects_invalid_video_id(client, import_root):
    source = write_minimal_mp4(import_root / "clip_c.mp4")

    response = client.post(
        "/api/v1/videos/register",
        json={"source": "local_path", "path": str(source), "video_id": "../evil"},
    )

    error = assert_unified_error(response, status=400, code="VALIDATION_ERROR")
    assert error["details"]["field"] == "video_id"


def test_register_metadata_does_not_expose_host_paths(client, import_root):
    source = write_minimal_mp4(import_root / "clip_d.mp4")

    response = client.post(
        "/api/v1/videos/register",
        json={"source": "local_path", "path": str(source), "metadata": {"note": "unit-test"}},
    )
    body = response.get_json()

    assert body["metadata"]["note"] == "unit-test"
    assert body["metadata"]["import_source"] == "local_path"
    assert str(import_root) not in response.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Detail / list errors and pagination
# --------------------------------------------------------------------------- #
def test_unknown_video_id_returns_unified_404(client):
    response = client.get("/api/v1/videos/vid_does_not_exist")

    error = assert_unified_error(response, status=404, code="VIDEO_NOT_FOUND")
    assert error["details"] == {
        "resource": "video",
        "video_id": "vid_does_not_exist",
    }


def test_list_paginates_without_duplicates(client):
    ids = [upload(client, name=f"clip_{index}.mp4").get_json()["video_id"] for index in range(3)]

    first = client.get("/api/v1/videos?limit=2&offset=0").get_json()
    second = client.get("/api/v1/videos?limit=2&offset=2").get_json()

    assert first["pagination"] == {"limit": 2, "offset": 0, "total": 3, "has_next": True}
    assert second["pagination"] == {"limit": 2, "offset": 2, "total": 3, "has_next": False}
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1

    seen = [item["video_id"] for item in first["items"] + second["items"]]
    assert sorted(seen) == sorted(ids)


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "limit=abc", "offset=-1", "offset=x"])
def test_list_rejects_invalid_pagination(client, query):
    response = client.get(f"/api/v1/videos?{query}")

    assert_unified_error(response, status=400, code="VALIDATION_ERROR")


def test_list_rejects_invalid_enum_filters(client):
    assert_unified_error(
        client.get("/api/v1/videos?status=unknown"), status=400, code="VALIDATION_ERROR"
    )
    assert_unified_error(
        client.get("/api/v1/videos?source=unknown"), status=400, code="VALIDATION_ERROR"
    )


def test_list_filters_by_source(client, import_root):
    upload(client)
    write_minimal_mp4(import_root / "sav_one.mp4")
    client.post(
        "/api/v1/videos/register",
        json={"source": "sav_clip", "path": str(import_root / "sav_one.mp4")},
    )

    uploads = client.get("/api/v1/videos?source=upload").get_json()
    sav = client.get("/api/v1/videos?source=sav_clip").get_json()

    assert uploads["pagination"]["total"] == 1
    assert uploads["items"][0]["source"] == "upload"
    assert sav["pagination"]["total"] == 1
    assert sav["items"][0]["source"] == "sav_clip"


def test_list_filter_by_status_excludes_unprocessed(client):
    upload(client)

    body = client.get("/api/v1/videos?status=processed").get_json()

    assert body["pagination"]["total"] == 0
    assert body["items"] == []


# --------------------------------------------------------------------------- #
# Controlled file access
# --------------------------------------------------------------------------- #
def test_file_endpoint_serves_exact_bytes(client):
    payload = make_minimal_mp4(3.0)
    video_id = upload(client, payload=payload).get_json()["video_id"]

    response = client.get(f"/api/v1/videos/{video_id}/file")

    assert response.status_code == 200
    assert response.data == payload
    assert response.mimetype == "video/mp4"
    assert "no-store" not in response.headers.get("Cache-Control", "")


def test_file_endpoint_supports_range_requests(client):
    payload = make_minimal_mp4(3.0)
    video_id = upload(client, payload=payload).get_json()["video_id"]

    response = client.get(
        f"/api/v1/videos/{video_id}/file", headers={"Range": "bytes=0-9"}
    )

    assert response.status_code == 206
    assert response.data == payload[:10]


def test_file_endpoint_unknown_video_returns_404(client):
    assert_unified_error(
        client.get("/api/v1/videos/vid_missing/file"),
        status=404,
        code="VIDEO_NOT_FOUND",
    )


def test_file_endpoint_reports_missing_stored_file(client, config):
    video_id = upload(client).get_json()["video_id"]
    stored = Path(config.videos_dir) / f"{video_id}.mp4"
    stored.unlink()

    error = assert_unified_error(
        client.get(f"/api/v1/videos/{video_id}/file"),
        status=404,
        code="VIDEO_FILE_MISSING",
    )
    assert error["details"]["video_id"] == video_id


@pytest.mark.parametrize(
    "bad_id", ["..", "a%2Fb", "..%2F..%2Fetc%2Fpasswd", "%2e%2e"]
)
def test_path_traversal_attempts_never_serve_files(client, bad_id):
    response = client.get(f"/api/v1/videos/{bad_id}/file")

    assert response.status_code == 404
    assert response.mimetype == "application/json"


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_video_survives_application_restart(tmp_path: Path):
    config = Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
    )

    first_app = create_app(config)
    uploaded = upload(first_app.test_client()).get_json()

    # A brand-new application over the same data directory == a restart.
    second_app = create_app(config)
    second_client = second_app.test_client()

    detail = second_client.get(f"/api/v1/videos/{uploaded['video_id']}")
    assert detail.status_code == 200
    assert detail.get_json()["video_id"] == uploaded["video_id"]
    assert detail.get_json()["size_bytes"] == uploaded["size_bytes"]

    listing = second_client.get("/api/v1/videos").get_json()
    assert listing["pagination"]["total"] == 1

    file_response = second_client.get(f"/api/v1/videos/{uploaded['video_id']}/file")
    assert file_response.status_code == 200
