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

    Notes on security/operations:
      - This repo does NOT verify passwords. Callers must verify passwords
        with a proper KDF (e.g., argon2/bcrypt/scrypt) before treating a login
        as successful and before calling the "success" logging path.
      - Account lock timestamps:
          By default, lock windows are computed using the database clock via
          SQLite datetime('now', '+X minutes'). If you want the application
          clock to be the single source of truth (to avoid app/DB clock
          drift), pass an explicit lock-until timestamp to
          increment_failed_attempts(..., lock_until_ts=...).
          The value should be an SQLite-compatible datetime text (e.g.,
          'YYYY-MM-DD HH:MM:SS' — UTC recommended).
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

    def increment_failed_attempts(
        self,
        user_id: int,
        max_attempts: int,
        lock_minutes: int,
        lock_until_ts: Optional[str] = None,  # Optional absolute lock-until timestamp (SQLite-compatible)
    ) -> None:
        """
        Atomically bump failed_attempts; if threshold reached, set locked_until.

        Args:
            user_id: Target user.
            max_attempts: Threshold for locking (min 1; defaults to 3 if < 1).
            lock_minutes: Window length in minutes (min 1; defaults to 15 if < 1)
                          when using DB-clock-based locking.
            lock_until_ts: Optional absolute timestamp to set when the threshold is
                           reached. If provided, it is written as-is to locked_until
                           (must be SQLite-compatible datetime text, e.g.
                           'YYYY-MM-DD HH:MM:SS'; UTC recommended). If not provided,
                           the DB clock is used via datetime('now', '+X minutes').

        Behavior:
            - Always increments failed_attempts.
            - If after increment the count >= max_attempts, sets locked_until either
              to lock_until_ts (if provided) or to DB-clock 'now' + lock_minutes.
        """
        if max_attempts < 1:
            max_attempts = 3
        if lock_minutes < 1:
            lock_minutes = 15

        if lock_until_ts is not None:
            # Use an application-supplied absolute timestamp to avoid app/DB clock drift.
            sql = """
            UPDATE users
               SET failed_attempts = failed_attempts + 1,
                   locked_until = CASE
                       WHEN (failed_attempts + 1) >= ?
                       THEN ?
                       ELSE locked_until
                   END
             WHERE user_id = ?
            """
            params = (max_attempts, lock_until_ts, user_id)
        else:
            # Fall back to DB clock: datetime('now', '+X minutes')
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
            params = (max_attempts, plus, user_id)

        self.conn.execute(sql, params)
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

        NOTE: Callers should ensure password verification uses a strong KDF
              before marking an attempt as successful.
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
