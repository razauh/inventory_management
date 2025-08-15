import sqlite3
from ...utils.auth import verify_password

class LoginController:
    def __init__(self, conn: sqlite3.Connection, parent=None):
        self.conn = conn
        self.parent = parent

    def prompt(self) -> dict | None:
        from .form import LoginForm
        dlg = LoginForm(self.parent)
        if not dlg.exec():
            return None
        username, password = dlg.get_values()
        if not username or not password:
            return None
        u = self.conn.execute("""
            SELECT user_id, username, password_hash, full_name, email, role, is_active
            FROM users WHERE username=?
        """, (username,)).fetchone()
        if not u or not u["is_active"]:
            return None
        if not verify_password(password, u["password_hash"]):
            self.conn.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE user_id=?", (u["user_id"],))
            self.conn.commit()
            return None
        self.conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP, failed_attempts=0 WHERE user_id=?", (u["user_id"],))
        self.conn.commit()
        return {k: u[k] for k in ("user_id","username","full_name","email","role")}
