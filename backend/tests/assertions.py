"""Shared assertions for API tests.

Keeping the unified-error check in one place guarantees every endpoint test
verifies the same contract (six fields, code format, timestamp format, no
leaked paths or stack traces).
"""

from __future__ import annotations

import re

ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GENERATED_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{12}$")

ERROR_FIELDS = {"code", "message", "details", "request_id", "retryable", "timestamp"}

#: Substrings that must never appear in a client-facing error response.
LEAK_MARKERS = ("Traceback", "site-packages", "minicpm_env", "C:\\", "/home/", "RuntimeError")


def assert_unified_error(response, *, status: int | None = None, code: str | None = None) -> dict:
    """Assert ``response`` matches the standard's error object exactly."""
    if status is not None:
        assert response.status_code == status
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert isinstance(body, dict)
    assert set(body) == {"error"}, f"顶层必须只有 error 字段，实际：{sorted(body)}"

    error = body["error"]
    assert set(error) == ERROR_FIELDS, f"error 字段不完整：{sorted(error)}"
    assert ERROR_CODE_RE.match(error["code"]), error["code"]
    if code is not None:
        assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"].strip()
    assert isinstance(error["details"], dict)
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert isinstance(error["retryable"], bool)
    assert TIMESTAMP_RE.match(error["timestamp"]), error["timestamp"]

    raw = response.get_data(as_text=True)
    for marker in LEAK_MARKERS:
        assert marker not in raw, f"错误响应泄露了敏感信息：{marker!r}"
    return error
