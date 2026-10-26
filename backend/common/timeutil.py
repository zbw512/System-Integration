"""Time helpers.

Every timestamp returned by the API is RFC 3339 in UTC with a ``Z`` suffix
(interface standard section 1.2) — never a local-timezone string.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_timestamp() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> datetime:
    """Timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)
