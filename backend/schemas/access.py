"""Internal access identity used for resource authorization.

An empty context represents a request with neither a valid user session nor a
valid anonymous session. Newly created resources must have exactly one owner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessContext:
    user_id: str | None = None
    guest_id: str | None = None

    def __post_init__(self) -> None:
        if self.user_id is not None and self.guest_id is not None:
            raise ValueError("访问主体不能同时是登录用户和匿名会话")

    @property
    def is_identified(self) -> bool:
        return self.user_id is not None or self.guest_id is not None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


ANONYMOUS_ACCESS = AccessContext()
