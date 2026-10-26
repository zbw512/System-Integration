"""Unified error model — interface standard v1, section 6.

Every non-2xx response produced by this backend has exactly this shape::

    {
      "error": {
        "code": "VIDEO_NOT_FOUND",
        "message": "视频不存在",
        "details": {"resource": "video", "video_id": "sav_xxx"},
        "request_id": "a1b2c3d4e5",
        "retryable": false,
        "timestamp": "2026-10-19T12:00:00Z"
      }
    }

Rules enforced here:

* ``code`` is stable, machine readable and matches ``^[A-Z][A-Z0-9_]*$``;
* ``message`` is a short user-facing Chinese sentence;
* ``details`` is always a JSON object — never a stack trace, a filesystem path
  or a secret;
* ``request_id`` lets the frontend correlate a failure with server logs;
* ``retryable`` is decided by the backend, never guessed by the client.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Mapping

from flask import Flask, Response, g, has_app_context, jsonify, request
from werkzeug.exceptions import HTTPException

from common.timeutil import utc_timestamp
from services.errors import ServiceError

logger = logging.getLogger(__name__)

__all__ = [
    "ApiError",
    "ERROR_CODE_PATTERN",
    "REQUEST_ID_PATTERN",
    "error_response",
    "get_request_id",
    "new_request_id",
    "register_error_handlers",
    "utc_timestamp",
]

#: Stable machine-readable error codes (standard section 6.1).
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: Accept a caller-supplied correlation id only if it looks safe.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: ``(code, message, retryable)`` per HTTP status (standard section 6.2).
_HTTP_ERROR_MAP: dict[int, tuple[str, str, bool]] = {
    400: ("VALIDATION_ERROR", "请求参数不合法", False),
    401: ("UNAUTHORIZED", "未授权访问", False),
    403: ("FORBIDDEN", "没有访问该资源的权限", False),
    404: ("NOT_FOUND", "请求的资源不存在", False),
    405: ("METHOD_NOT_ALLOWED", "请求方法不被允许", False),
    409: ("CONFLICT", "资源当前状态冲突", False),
    413: ("PAYLOAD_TOO_LARGE", "上传内容超过大小限制", False),
    415: ("UNSUPPORTED_MEDIA_TYPE", "不支持的内容类型", False),
    422: ("UNPROCESSABLE_ENTITY", "内容不合法，无法处理", False),
    429: ("RATE_LIMITED", "请求过于频繁，请稍后重试", True),
    500: ("INTERNAL_ERROR", "服务器内部错误", True),
    501: ("ADAPTER_NOT_IMPLEMENTED", "该适配器尚未实现", False),
    502: ("UPSTREAM_MODEL_ERROR", "模型服务异常", True),
    503: ("SERVICE_UNAVAILABLE", "服务暂不可用", True),
    504: ("UPSTREAM_TIMEOUT", "模型服务响应超时", True),
}


def new_request_id() -> str:
    """Generate a short opaque correlation id (not a security token)."""
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    """Current request's correlation id, or a fresh one outside a request."""
    if has_app_context():
        request_id = getattr(g, "request_id", None)
        if request_id:
            return str(request_id)
    return new_request_id()


class ApiError(Exception):
    """Business error carrying every field of the standard error object."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not ERROR_CODE_PATTERN.match(code):
            raise ValueError(
                f"非法错误码 {code!r}：必须匹配 {ERROR_CODE_PATTERN.pattern}"
            )
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = int(status)
        self.details: dict[str, Any] = dict(details or {})
        self.retryable = bool(retryable)
        self.headers: dict[str, str] = dict(headers or {})

    def to_error_dict(self, request_id: str | None = None) -> dict[str, Any]:
        """Serialize to the ``error`` object defined by the standard."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "request_id": request_id or get_request_id(),
            "retryable": self.retryable,
            "timestamp": utc_timestamp(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"ApiError(code={self.code!r}, status={self.status})"


def error_response(
    error: ApiError,
    *,
    request_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Build the uniform ``{"error": {...}}`` response."""
    rid = request_id or get_request_id()
    body = {"error": error.to_error_dict(rid)}

    response = jsonify(body)
    response.status_code = error.status
    response.headers["X-Request-Id"] = rid

    for key, value in error.headers.items():
        response.headers[key] = value
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _api_error_from_http_exception(exc: HTTPException) -> ApiError:
    """Translate a Werkzeug HTTP exception into the standard error shape."""
    status = exc.code if isinstance(exc.code, int) else 500
    code, message, retryable = _HTTP_ERROR_MAP.get(
        status,
        (f"HTTP_{status}", "请求处理失败", status >= 500),
    )

    details: dict[str, Any] = {}
    if status == 404:
        # Only the request path — never a filesystem path.
        details = {"method": request.method, "path": request.path}
    elif status == 405:
        allowed = getattr(exc, "valid_methods", None)
        if allowed:
            details = {"allowed_methods": sorted(allowed), "method": request.method}

    headers: dict[str, str] = {}
    if status == 405:
        allowed = getattr(exc, "valid_methods", None)
        if allowed:
            headers["Allow"] = ", ".join(sorted(allowed))

    return ApiError(
        code,
        message,
        status=status,
        details=details,
        retryable=retryable,
        headers=headers,
    )


def register_error_handlers(app: Flask) -> None:
    """Attach the unified error handlers to ``app``.

    Four layers are covered:

    1. :class:`~services.errors.ServiceError` — domain failures raised by the
       service/storage layer (video not found, duplicate id, unsupported
       container, ...), translated into the standard error object;
    2. :class:`ApiError` — errors raised directly by the HTTP layer;
    3. :class:`~werkzeug.exceptions.HTTPException` — 404/405/413 produced by
       Flask/Werkzeug itself;
    4. :class:`Exception` — unexpected failures, reported as ``500
       INTERNAL_ERROR`` without leaking the exception text or a stack trace.
    """

    @app.errorhandler(ServiceError)
    def _handle_service_error(exc: ServiceError) -> Response:
        log = logger.warning if exc.status < 500 else logger.error
        log("service_error code=%s status=%s", exc.code, exc.status)
        return error_response(
            ApiError(
                exc.code,
                exc.message,
                status=exc.status,
                details=exc.details,
                retryable=exc.retryable,
            )
        )

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError) -> Response:
        # Log code/status only: ``details`` may contain user-supplied data.
        log = logger.warning if exc.status < 500 else logger.error
        log("api_error code=%s status=%s retryable=%s", exc.code, exc.status, exc.retryable)
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException) -> Response:
        error = _api_error_from_http_exception(exc)
        logger.info("http_error status=%s code=%s", error.status, error.code)
        return error_response(error)

    @app.errorhandler(Exception)
    def _handle_unexpected_exception(exc: Exception) -> Response:
        # The traceback stays in the server log; the client only gets a code.
        logger.exception("unhandled_exception type=%s", type(exc).__name__)
        code, message, retryable = _HTTP_ERROR_MAP[500]
        return error_response(ApiError(code, message, status=500, retryable=retryable))
