# inventory_management/modules/login/model.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class UserSession:
    """
    App-facing user object (no secrets).

    Fields mirror what the controller returns on successful login.
    """
    user_id: int
    username: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    last_login: Optional[str] = None
    prev_login: Optional[str] = None

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> "UserSession":
        """
        Build from any dict/mapping with the expected keys.
        Safe to use with sqlite3.Row or a plain dict.
        """
        return cls(
            user_id=int(m["user_id"]),
            username=str(m["username"]),
            full_name=m.get("full_name"),
            email=m.get("email"),
            role=m.get("role"),
            last_login=m.get("last_login"),
            prev_login=m.get("prev_login"),
        )
