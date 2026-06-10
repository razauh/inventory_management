from __future__ import annotations

def test_database_exposes_configured_db_path():
    import database
    from config import DB_PATH

    assert database.get_db_path() == str(DB_PATH.resolve())


def test_sqlite_ops_resolves_app_db_path_before_env(monkeypatch, tmp_path):
    import database
    from modules.backup_restore import sqlite_ops

    env_db = tmp_path / "wrong.sqlite"
    monkeypatch.setenv("APP_DB_PATH", str(env_db))
    monkeypatch.setattr(sqlite_ops, "_DB_PATH", None)

    assert sqlite_ops.get_db_path() == database.get_db_path()
    assert sqlite_ops.get_db_path() != str(env_db.resolve())
