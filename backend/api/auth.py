"""Local account endpoints used by the desktop-style web interface."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from api.errors import ApiError
from schemas.access import ANONYMOUS_ACCESS, AccessContext
from schemas.user import User
from services.auth_service import AuthService, SESSION_COOKIE_NAME
from services.guest_session_service import (
    GUEST_COOKIE_NAME,
    GuestSessionService,
)
from services.errors import AuthenticationRequiredError, StorageError

auth_bp = Blueprint("auth", __name__)


def _service() -> AuthService:
    return current_app.extensions["auth_service"]


def _guest_service() -> GuestSessionService:
    return current_app.extensions["guest_session_service"]


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
    config = current_app.config["APP_CONFIG"]
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=config.environment.lower() in {"production", "prod"},
        samesite="Lax",
    )
    return response


def set_guest_cookie(response, token: str):
    config = current_app.config["APP_CONFIG"]
    response.set_cookie(
        GUEST_COOKIE_NAME,
        token,
        max_age=_guest_service().ttl_hours * 60 * 60,
        httponly=True,
        secure=config.environment.lower() in {"production", "prod"},
        samesite="Lax",
        path="/",
    )
    return response


def _clear_guest_cookie(response):
    config = current_app.config["APP_CONFIG"]
    response.delete_cookie(
        GUEST_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=config.environment.lower() in {"production", "prod"},
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


def get_access_context() -> AccessContext:
    """Resolve a user first, otherwise the current anonymous browser."""

    if "access_context" in g:
        return g.access_context

    user = get_optional_user()
    if user is not None:
        context = AccessContext(user_id=user.user_id)
    else:
        guest = _guest_service().resolve(
            request.cookies.get(GUEST_COOKIE_NAME)
        )
        context = (
            AccessContext(guest_id=guest.guest_id)
            if guest is not None
            else ANONYMOUS_ACCESS
        )
    g.access_context = context
    return context


def get_or_create_upload_access() -> tuple[AccessContext, str | None]:
    """Return the upload owner and a new guest token when one was minted."""

    context = get_access_context()
    if context.is_identified:
        return context, None

    guest, token = _guest_service().create()
    context = AccessContext(guest_id=guest.guest_id)
    g.access_context = context
    return context, token


def _claim_guest_resources(user: User) -> tuple[dict[str, int], bool]:
    token = request.cookies.get(GUEST_COOKIE_NAME)
    if not token:
        return ({"videos": 0, "jobs": 0}, False)
    try:
        result = _guest_service().claim_for_user(token, user.user_id)
    except StorageError:
        return ({"videos": 0, "jobs": 0}, False)
    return ({"videos": result.videos, "jobs": result.jobs}, True)


def require_user() -> User:
    user = get_optional_user()
    if user is None:
        raise AuthenticationRequiredError()
    return user


@auth_bp.post("/register")
def register():
    payload = _request_json()
    previous_session = request.cookies.get(SESSION_COOKIE_NAME)
    user = _service().register(
        username=payload.get("username"),
        password=payload.get("password"),
        display_name=payload.get("display_name"),
        registration_token=request.headers.get("X-Registration-Token"),
        client_id=request.remote_addr,
    )
    claim, clear_guest = _claim_guest_resources(user)
    token = _service().create_session(user.user_id)
    if previous_session:
        _service().revoke_session(previous_session)
    response = jsonify(
        {
            "authenticated": True,
            "user": user.to_dict(),
            "guest_claim": claim,
        }
    )
    response.status_code = 201
    if clear_guest:
        _clear_guest_cookie(response)
    return _set_session_cookie(response, token)


@auth_bp.post("/login")
def login():
    payload = _request_json()
    previous_session = request.cookies.get(SESSION_COOKIE_NAME)
    user = _service().authenticate(
        username=payload.get("username"),
        password=payload.get("password"),
        client_id=request.remote_addr,
    )
    claim, clear_guest = _claim_guest_resources(user)
    token = _service().create_session(user.user_id)
    if previous_session:
        _service().revoke_session(previous_session)
    response = jsonify(
        {
            "authenticated": True,
            "user": user.to_dict(),
            "guest_claim": claim,
        }
    )
    if clear_guest:
        _clear_guest_cookie(response)
    return _set_session_cookie(response, token)


@auth_bp.post("/claim-anonymous")
def claim_anonymous():
    user = require_user()
    claim, clear_guest = _claim_guest_resources(user)
    response = jsonify(
        {
            "authenticated": True,
            "user": user.to_dict(),
            "guest_claim": claim,
        }
    )
    if clear_guest:
        _clear_guest_cookie(response)
    return response


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
