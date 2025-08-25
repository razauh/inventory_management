import sqlite3
from ...utils.auth import verify_password


class LoginController:
    def __init__(self, conn: sqlite3.Connection, parent=None):
        self.conn = conn
        self.parent = parent
        # Expose details about the last attempt (for the main window to message on)
        self.last_error_code: str | None = None   # e.g. "user_not_found", "wrong_password", "cancelled", "empty_fields", "user_inactive"
        self.last_error_message: str | None = None
        self.last_username: str | None = None

    def prompt(self) -> dict | None:
        """
        Shows the login dialog and returns a user dict on success, or None on failure/cancel.
        On failure, sets self.last_error_code / last_error_message / last_username for the caller to inspect.
        """
        # reset error state for this attempt
        self.last_error_code = None
        self.last_error_message = None
        self.last_username = None

        from .form import LoginForm
        dlg = LoginForm(self.parent)
        if not dlg.exec():
            self.last_error_code = "cancelled"
            self.last_error_message = "Login cancelled by user."
            return None

        username, password = dlg.get_values()
        self.last_username = (username or "").strip()

        if not username or not password:
            self.last_error_code = "empty_fields"
            self.last_error_message = "Please enter both username and password."
            return None

        u = self.conn.execute(
            """
            SELECT user_id, username, password_hash, full_name, email, role, is_active
            FROM users WHERE username=?
            """,
            (username,),
        ).fetchone()

        if not u:
            self.last_error_code = "user_not_found"
            self.last_error_message = f"No account exists for username “{self.last_username}”."
            return None

        if not u["is_active"]:
            self.last_error_code = "user_inactive"
            self.last_error_message = f"Account “{self.last_username}” is inactive. Contact an administrator."
            return None

        if not verify_password(password, u["password_hash"]):
            # Track failed attempts, but still return a friendly reason
            self.conn.execute(
                "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE user_id=?",
                (u["user_id"],),
            )
            self.conn.commit()
            self.last_error_code = "wrong_password"
            self.last_error_message = f"Incorrect password for “{self.last_username}”."
            return None

        # success
        self.conn.execute(
            "UPDATE users SET last_login=CURRENT_TIMESTAMP, failed_attempts=0 WHERE user_id=?",
            (u["user_id"],),
        )
        self.conn.commit()
        return {k: u[k] for k in ("user_id", "username", "full_name", "email", "role")}
