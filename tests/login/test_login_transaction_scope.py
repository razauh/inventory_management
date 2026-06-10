import sqlite3

import pytest

from inventory_management.database.repositories.login_repo import LoginRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.login.controller import LoginController


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


class FakeLoginForm:
    username = ""
    password = ""

    def __init__(self, _parent):
        pass

    def exec(self):
        return True

    def get_values(self):
        return self.username, self.password


def test_login_repo_increment_failed_attempts_preserves_outer_transaction_and_commits_standalone():
    conn = make_db()
    user_id = conn.execute(
        """
        INSERT INTO users (username, password_hash, full_name, role)
        VALUES ('ops', 'hash', 'Ops User', 'admin')
        """
    ).lastrowid
    conn.commit()
    repo = LoginRepo(conn)

    conn.execute("BEGIN")
    repo.increment_failed_attempts(int(user_id), max_attempts=5, lock_minutes=15)
    assert conn.in_transaction is True
    conn.rollback()

    row = conn.execute(
        "SELECT failed_attempts FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row["failed_attempts"] == 0

    repo.increment_failed_attempts(int(user_id), max_attempts=5, lock_minutes=15)
    assert conn.in_transaction is False
    row = conn.execute(
        "SELECT failed_attempts FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row["failed_attempts"] == 1
    conn.close()


def test_wrong_password_rolls_back_failed_attempt_count_when_auth_log_write_fails(monkeypatch):
    conn = make_db()
    user_id = conn.execute(
        """
        INSERT INTO users (username, password_hash, full_name, role)
        VALUES ('ops', 'stored-hash', 'Ops User', 'admin')
        """
    ).lastrowid
    conn.commit()

    controller = LoginController(conn)
    FakeLoginForm.username = "ops"
    FakeLoginForm.password = "bad"

    monkeypatch.setattr("inventory_management.modules.login.controller.verify_password", lambda *_args: False)
    monkeypatch.setattr("inventory_management.modules.login.form.LoginForm", FakeLoginForm)
    monkeypatch.setattr(
        controller.repo,
        "insert_auth_log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("audit insert failed")),
    )

    with pytest.raises(sqlite3.OperationalError, match="audit insert failed"):
        controller.prompt()

    row = conn.execute(
        "SELECT failed_attempts, locked_until FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row["failed_attempts"] == 0
    assert row["locked_until"] is None
    assert controller.last_error_code == "wrong_password"
    conn.close()


def test_success_login_rolls_back_reset_when_auth_log_write_fails(monkeypatch):
    conn = make_db()
    user_id = conn.execute(
        """
        INSERT INTO users (
            username, password_hash, full_name, role, failed_attempts, locked_until, last_login
        ) VALUES ('ops', 'stored-hash', 'Ops User', 'admin', 2, '2030-01-01 00:00:00', '2025-01-01 00:00:00')
        """
    ).lastrowid
    conn.commit()

    controller = LoginController(conn)
    FakeLoginForm.username = "ops"
    FakeLoginForm.password = "good"

    monkeypatch.setattr("inventory_management.modules.login.controller.verify_password", lambda *_args: True)
    monkeypatch.setattr("inventory_management.modules.login.form.LoginForm", FakeLoginForm)
    monkeypatch.setattr(
        controller.repo,
        "insert_auth_log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("audit insert failed")),
    )

    with pytest.raises(sqlite3.OperationalError, match="audit insert failed"):
        controller.prompt()

    row = conn.execute(
        "SELECT failed_attempts, locked_until, last_login FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row["failed_attempts"] == 2
    assert row["locked_until"] == "2030-01-01 00:00:00"
    assert row["last_login"] == "2025-01-01 00:00:00"
    conn.close()
