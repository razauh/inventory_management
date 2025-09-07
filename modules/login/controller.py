# inventory_management/modules/login/controller.py
from __future__ import annotations

import sqlite3
from typing import Optional

from ...utils.auth import verify_password
from ...database.repositories.login_repo import LoginRepo


class LoginController:
    """
    Login flow using LoginRepo for all DB I/O.

    Public attrs (set after each prompt()):
      - last_error_code: str | None
      - last_error_message: str | None
      - last_username: str | None
    """

    # You can tweak these without changing the repo
    MAX_FAILED_ATTEMPTS = 5          # lock after N consecutive failures
    LOCKOUT_MINUTES = 15             # lock duration

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        self.conn = conn
        self.parent = parent
        self.repo = LoginRepo(conn)

        self.last_error_code: Optional[str] = None
        self.last_error_message: Optional[str] = None
        self.last_username: Optional[str] = None

    # ----------------------------- Public API -----------------------------

    def prompt(self) -> Optional[dict]:
        """
        Show the dialog and attempt login.
        Returns a user dict on success, or None on failure/cancel.
        On failure, last_error_code / last_error_message / last_username are set.
        """
        self._reset_last_error()

        from .form import LoginForm  # lazy import to keep UI deps local
        dlg = LoginForm(self.parent)
        if not dlg.exec():
            self._fail("cancelled", "Login cancelled by user.", username=None, log=True)
            return None

        username, password = dlg.get_values()
        self.last_username = (username or "").strip()

        if not username or not password:
            self._fail("empty_fields", "Please enter both username and password.", log=False)
            return None

        # Lookup user (case-insensitive)
        u = self.repo.get_user_by_username(username)
        if not u:
            self._fail("user_not_found", f"No account exists for username “{self.last_username}”.", log=True)
            return None

        # Check active flag
        if not u["is_active"]:
            self._fail("user_inactive", f"Account “{self.last_username}” is inactive. Contact an administrator.", log=True)
            return None

        # Check lockout (locked_until > now)
        if self._is_currently_locked(u):
            until = u["locked_until"] or ""
            self._fail("locked_out", f"Account is locked due to repeated failures. Try again after {until}.", log=True)
            return None

        # Verify password
        if not verify_password(password, u["password_hash"]):
            # Count failure and possibly lock
            try:
                self.repo.increment_failed_attempts(
                    user_id=int(u["user_id"]),
                    max_attempts=self.MAX_FAILED_ATTEMPTS,
                    lock_minutes=self.LOCKOUT_MINUTES,
                )
            finally:
                self._fail("wrong_password", f"Incorrect password for “{self.last_username}”.", log=True)
            return None

        # Success path: reset counters, touch login times
        self.repo.reset_failed_attempts_and_touch_login(int(u["user_id"]))
        self.repo.insert_auth_log(self.last_username or "", True, "ok", client=None)

        # Return only what the app needs downstream
        return {
            "user_id": u["user_id"],
            "username": u["username"],
            "full_name": u.get("full_name"),
            "email": u.get("email"),
            "role": u.get("role"),
            # Useful for the app to decide on prompting password change
            "require_password_change": u.get("require_password_change"),
            "prev_login": u.get("prev_login"),
            "last_login": u.get("last_login"),
        }

    # ----------------------------- Internals -----------------------------

    def _reset_last_error(self) -> None:
        self.last_error_code = None
        self.last_error_message = None
        self.last_username = None

    def _fail(self, code: str, message: str, username: Optional[str] = None, log: bool = False) -> None:
        self.last_error_code = code
        self.last_error_message = message
        if username is not None:
            self.last_username = username
        if log:
            # Log failures with the username text as entered
            self.repo.insert_auth_log(self.last_username or "", False, code, client=None)

    def _is_currently_locked(self, user_row: sqlite3.Row) -> bool:
        """
        Return True if locked_until is set in the future relative to CURRENT_TIMESTAMP.
        Use SQLite to compare timestamps to avoid client TZ parsing assumptions.
        """
        locked_until = user_row.get("locked_until")
        if not locked_until:
            return False
        row = self.conn.execute(
            "SELECT CASE WHEN DATETIME(?) > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS is_locked",
            (locked_until,),
        ).fetchone()
        return bool(row and row["is_locked"])
