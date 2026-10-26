"""Job endpoints — interface standard sections 3.3 and 4.1.

Routes (registered under ``/api/v1/jobs``):

* ``GET ""``             list with ``items`` + ``pagination``, ``200``
* ``GET /<job_id>``      detail, ``200``

Creating a job happens on the video resource: ``POST /api/v1/videos/{id}/process``.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from api.params import parse_int_arg
from services.job_service import JobService

jobs_bp = Blueprint("jobs", __name__)


def _service() -> JobService:
    return current_app.extensions["job_service"]


@jobs_bp.get("", strict_slashes=False)
def list_jobs():
    """Paginated job list, newest first, optionally filtered."""
    config = current_app.config["APP_CONFIG"]
    limit = parse_int_arg(
        "limit",
        config.list_default_limit,
        minimum=1,
        maximum=config.list_max_limit,
    )
    offset = parse_int_arg("offset", 0, minimum=0, maximum=None)

    payload = _service().list_jobs(
        limit=limit,
        offset=offset,
        status=request.args.get("status") or None,
        video_id=request.args.get("video_id") or None,
        job_type=request.args.get("job_type") or None,
    )
    return jsonify(payload), 200


@jobs_bp.get("/<job_id>")
def get_job(job_id: str):
    return jsonify(_service().get_job(job_id).to_dict()), 200
