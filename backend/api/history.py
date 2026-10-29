"""Authenticated personal analysis history."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from api.auth import require_user
from api.params import parse_int_arg

history_bp = Blueprint("history", __name__)


@history_bp.get("", strict_slashes=False)
def list_history():
    user = require_user()
    config = current_app.config["APP_CONFIG"]
    limit = parse_int_arg(
        "limit",
        20,
        minimum=1,
        maximum=100,
    )
    offset = parse_int_arg("offset", 0, minimum=0, maximum=None)
    payload = current_app.extensions["job_service"].list_history(
        user_id=user.user_id,
        limit=limit,
        offset=offset,
    )
    return jsonify(payload), 200
