"""Local user model for authenticated analysis history.

The project is a local research application, so this first account layer keeps
only the minimum identity needed to own analysis jobs. Passwords are never
stored in this object or serialized to the client.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    display_name: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }
