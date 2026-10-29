"""Local account endpoints used by the desktop-style web interface."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from api.errors import ApiError
from schemas.user import User
from services.auth_service import AuthService, SESSION_COOKIE_NAME
from services.errors import AuthenticationRequiredError

auth_bp = Blueprint("auth", __name__)


def _service() -> AuthService:
    return current_app.extensions["auth_service"]


def _request_json() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            "VALIDATION_ERROR",
            "请求体必须是 JSON 对象",
            status=400,
            details={"content_type": request.content_type},
        )
    return payload


def _set_session_cookie(response, token: str):
    config = current_app.config["APP_CONFIG"]
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=_service().session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=config.environment.lower() in {"production", "prod"},
        samesite="Lax",
        path="/",
    )
    return response


def _clear_session_cookie(response):
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="Lax",
    )
    return response


def get_optional_user() -> User | None:
    """Resolve the current cookie session once per request."""

    if "auth_user" in g:
        return g.auth_user
    user = _service().get_user_for_session(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    g.auth_user = user
    return user


def require_user() -> User:
    user = get_optional_user()
    if user is None:
        raise AuthenticationRequiredError()
    return user


@auth_bp.post("/register")
def register():
    payload = _request_json()
    user = _service().register(
        username=payload.get("username"),
        password=payload.get("password"),
        display_name=payload.get("display_name"),
    )
    token = _service().create_session(user.user_id)
    response = jsonify({"authenticated": True, "user": user.to_dict()})
    response.status_code = 201
    return _set_session_cookie(response, token)


@auth_bp.post("/login")
def login():
    payload = _request_json()
    user = _service().authenticate(
        username=payload.get("username"),
        password=payload.get("password"),
    )
    token = _service().create_session(user.user_id)
    response = jsonify({"authenticated": True, "user": user.to_dict()})
    return _set_session_cookie(response, token)


@auth_bp.post("/logout")
def logout():
    _service().revoke_session(request.cookies.get(SESSION_COOKIE_NAME))
    g.auth_user = None
    return _clear_session_cookie(
        jsonify({"authenticated": False, "user": None})
    )


@auth_bp.get("/me")
def me():
    user = get_optional_user()
    return jsonify(
        {
            "authenticated": user is not None,
            "user": None if user is None else user.to_dict(),
        }
    )
