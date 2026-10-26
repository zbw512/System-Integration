"""Shared query-parameter parsing for the HTTP layer.

Kept in one module so ``/videos`` and ``/jobs`` validate pagination identically
and the limits published by ``GET /api/v1/info`` are the ones enforced.
"""

from __future__ import annotations

from flask import request

from api.errors import ApiError


def parse_int_arg(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None,
) -> int:
    """Parse a positive/negative-bounded integer query parameter.

    Raises ``400 VALIDATION_ERROR`` (standard error object) on non-integers and
    out-of-range values instead of silently clamping them.
    """
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "VALIDATION_ERROR",
            f"{name} 必须是整数",
            status=400,
            details={"field": name, "value": raw},
        ) from exc

    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError(
            "VALIDATION_ERROR",
            f"{name} 超出允许范围",
            status=400,
            details={"field": name, "value": value, "min": minimum, "max": maximum},
        )

    return value
