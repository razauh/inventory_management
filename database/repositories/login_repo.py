# inventory_management/database/repositories/login_repo.py
from __future__ import annotations

import sqlite3
from typing import Optional


class LoginRepo:
    """
    Thin data-access layer for login/auth.

    Matches your current schema:
      users(user_id, username, password_hash, full_name, email, role,
            is_active, created_date, last_login, failed_attempts, locked_until)

    Also writes to audit_logs for attempt logging.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # ------------------------------ helpers ------------------------------

    @staticmethod
    def _norm_username(username: str) -> str:
        # Normalize consistently with your inserts; here we just trim.
        # (If you lower() at insert time, lower() here too.)
        return (username or "").strip()

    # ------------------------------- reads -------------------------------

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """
        Return the full user as a plain dict (caller decides what to use).
        Only columns that exist in your schema are selected.
        """
        uname = self._norm_username(username)
        sql = """
        SELECT
            user_id,
            username,
            password_hash,
            full_name,
            email,
            role,
            is_active,
            last_login,
            failed_attempts,
            locked_until
        FROM users
        WHERE username = ?
        """
        row = self.conn.execute(sql, (uname,)).fetchone()
        return dict(row) if row else None

    # ------------------------------ writes -------------------------------

    def increment_failed_attempts(self, user_id: int, max_attempts: int, lock_minutes: int) -> None:
        """
        Atomically bump failed_attempts; if threshold reached, set locked_until now + lock_minutes.
        """
        if max_attempts < 1:
            max_attempts = 3
        if lock_minutes < 1:
            lock_minutes = 15

        # Build a "+<minutes> minutes" modifier for SQLite datetime()
        plus = f"+{int(lock_minutes)} minutes"

        sql = """
        UPDATE users
           SET failed_attempts = failed_attempts + 1,
               locked_until = CASE
                   WHEN (failed_attempts + 1) >= ?
                   THEN datetime('now', ?)
                   ELSE locked_until
               END
         WHERE user_id = ?
        """
        self.conn.execute(sql, (max_attempts, plus, user_id))
        self.conn.commit()

    def reset_failed_attempts_and_touch_login(self, user_id: int) -> None:
        """
        On successful login: zero failed_attempts, set last_login=now, clear locked_until.
        (No prev_login column in schema; not updating it.)
        """
        sql = """
        UPDATE users
           SET failed_attempts = 0,
               last_login = CURRENT_TIMESTAMP,
               locked_until = NULL
         WHERE user_id = ?
        """
        self.conn.execute(sql, (user_id,))
        self.conn.commit()

    def insert_auth_log(self, username: str, success: bool, reason: str, client: Optional[str]) -> None:
        """
        Record the attempt in audit_logs. We’ll try to resolve user_id by username;
        if not found (e.g., unknown user), store NULL for user_id.
        """
        uname = self._norm_username(username)

        # Resolve user_id (may be None if user does not exist)
        row = self.conn.execute(
            "SELECT user_id FROM users WHERE username = ?",
            (uname,),
        ).fetchone()
        user_id = int(row["user_id"]) if row else None

        # Compose a compact details string; you can switch to JSON if you prefer.
        details = f"success={1 if success else 0}; reason={reason or ''}; username={uname}"

        self.conn.execute(
            """
            INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details, ip_address)
            VALUES (?, 'auth', 'users', NULL, ?, ?)
            """,
            (user_id, details, client),
        )
        self.conn.commit()

    # ------------------------------ optional -----------------------------

    # These are intentionally omitted because your schema has no such columns today:
    #
    # def set_require_password_change(self, user_id: int, flag: bool) -> None: ...
    # def update_password(self, user_id: int, new_hash: str) -> None: ...
