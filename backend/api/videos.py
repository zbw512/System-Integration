"""Video endpoints — interface standard sections 3.1, 4.1 and 4.3.

Routes (registered under ``/api/v1/videos``):

* ``POST /upload``            multipart upload, ``201``
* ``POST /register``          register a file inside an allowed import root, ``201``
* ``GET  ""``                list with ``items`` + ``pagination``, ``200``
* ``GET  /<video_id>``        detail, ``200``
* ``GET  /<video_id>/file``   controlled file access, ``200``

The layer only parses/validates HTTP input and delegates to
:class:`services.video_service.VideoService`.
"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, request, send_file

from api.errors import ApiError
from api.params import parse_int_arg
from schemas.enums import VideoSource
from services.video_service import VideoService

videos_bp = Blueprint("videos", __name__)

_RESULT_FORMATS = ("json", "csv")

_MIME_BY_EXTENSION = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
}


def _service() -> VideoService:
    return current_app.extensions["video_service"]


def _created_response(video) -> object:
    response = jsonify(video.to_dict())
    response.status_code = 201
    response.headers["Location"] = f"{current_app.config['APP_CONFIG'].api_prefix}/videos/{video.video_id}"
    return response


@videos_bp.post("/upload")
def upload_video():
    """Accept a ``multipart/form-data`` upload and register it."""
    upload = request.files.get("file")
    if upload is None:
        raise ApiError(
            "VALIDATION_ERROR",
            "缺少上传文件字段 file",
            status=400,
            details={"field": "file", "content_type": request.content_type},
        )
    return _created_response(_service().create_from_upload(upload))


@videos_bp.post("/register")
def register_video():
    """Register an existing file that lives inside an allowed import root."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            "VALIDATION_ERROR",
            "请求体必须是 JSON 对象",
            status=400,
            details={"content_type": request.content_type},
        )

    source_raw = payload.get("source")
    allowed_sources = [VideoSource.LOCAL_PATH.value, VideoSource.SAV_CLIP.value]
    if source_raw not in allowed_sources:
        raise ApiError(
            "VALIDATION_ERROR",
            "source 必须是 local_path 或 sav_clip",
            status=400,
            details={"field": "source", "allowed": allowed_sources},
        )

    metadata = payload.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ApiError(
            "VALIDATION_ERROR",
            "metadata 必须是对象",
            status=400,
            details={"field": "metadata"},
        )

    video = _service().create_from_path(
        payload.get("path"),
        source=VideoSource(source_raw),
        name=payload.get("name"),
        video_id=payload.get("video_id"),
        metadata=metadata,
    )
    return _created_response(video)


@videos_bp.get("", strict_slashes=False)
def list_videos():
    """Paginated list, newest first."""
    config = current_app.config["APP_CONFIG"]
    limit = parse_int_arg(
        "limit",
        config.list_default_limit,
        minimum=1,
        maximum=config.list_max_limit,
    )
    offset = parse_int_arg("offset", 0, minimum=0, maximum=None)

    payload = _service().list_videos(
        limit=limit,
        offset=offset,
        status=request.args.get("status") or None,
        source=request.args.get("source") or None,
    )
    return jsonify(payload), 200


@videos_bp.get("/<video_id>")
def get_video(video_id: str):
    return jsonify(_service().get_video(video_id).to_dict()), 200


@videos_bp.get("/<video_id>/results")
def get_video_results(video_id: str):
    """Return the **persisted** analysis result as JSON (default) or CSV.

    Both formats read the same ``videos`` row, so an export can never disagree
    with what ``GET /videos/{id}`` shows. Exporting never triggers analysis and
    never creates a job.
    """
    raw_format = request.args.get("format")
    result_format = (raw_format or "json").strip().lower()
    if result_format not in _RESULT_FORMATS:
        raise ApiError(
            "VALIDATION_ERROR",
            "format 只能是 json 或 csv",
            status=400,
            details={
                "field": "format",
                "allowed": list(_RESULT_FORMATS),
                "value": raw_format,
            },
        )

    # Unknown video -> 404 VIDEO_NOT_FOUND (handled by VideoService).
    video = _service().get_video(video_id)
    exporter = current_app.extensions["export_service"]

    if result_format == "json":
        return jsonify(exporter.build_json_result(video)), 200

    # Unanalysed/running/failed video -> 409 VIDEO_NOT_PROCESSED.
    csv_text = exporter.build_csv(video)
    response = current_app.response_class(csv_text, mimetype="text/csv")
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="results_{video.video_id}.csv"'
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@videos_bp.get("/<video_id>/file")
def get_video_file(video_id: str):
    """Serve the stored file from inside the data directory only.

    ``send_file`` with ``conditional=True`` adds ``Range`` / ``ETag`` support so
    the HTML5 ``<video>`` element can seek without downloading the whole file.
    """
    video, absolute_path = _service().get_stored_file(video_id)
    extension = os.path.splitext(absolute_path)[1].lower()

    response = send_file(
        absolute_path,
        mimetype=_MIME_BY_EXTENSION.get(extension, "application/octet-stream"),
        as_attachment=False,
        download_name=video.name,
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


@videos_bp.post("/<video_id>/process")
def create_process_job(video_id: str):
    """Queue a ``video_process`` job and answer immediately with ``202``.

    The request only creates the persistent job record and enqueues it; the
    analysis itself runs in the single background worker, so the client is never
    blocked by model latency.
    """
    job = current_app.extensions["job_service"].create_video_process_job(video_id)
    response = jsonify(job.to_dict())
    response.status_code = 202
    response.headers["Location"] = (
        f"{current_app.config['APP_CONFIG'].api_prefix}/jobs/{job.job_id}"
    )
    return response
