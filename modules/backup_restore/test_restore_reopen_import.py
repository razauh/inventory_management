from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from modules.base_module import BaseModule


class _Repo:
    def __init__(self, conn) -> None:
        self.conn = conn


class _Module(BaseModule):
    def __init__(self, conn) -> None:
        super().__init__()
        self.conn = conn
        self.repo = _Repo(conn)


def test_app_db_manager_open_works_without_package_context(monkeypatch):
    import database
    import main

    sentinel_conn = object()

    monkeypatch.setattr(main, "__package__", None)
    monkeypatch.setattr(database, "get_connection", lambda: sentinel_conn)

    main_window = SimpleNamespace(conn=None, modules=[])
    manager = main.MainWindow._AppDbManager(main_window)

    manager.open()

    assert main_window.conn is sentinel_conn


def test_app_db_manager_closes_and_reopens_module_connections(monkeypatch, tmp_path):
    import database
    import main

    live_db = tmp_path / "live.db"
    conn = sqlite3.connect(live_db)
    module = _Module(conn)
    main_window = SimpleNamespace(conn=conn, modules=[("Test", module)])
    manager = main.MainWindow._AppDbManager(main_window)
    sentinel_conn = object()

    monkeypatch.setattr(database, "get_connection", lambda: sentinel_conn)

    manager.close_all()
    assert main_window.conn is None
    assert module.conn is None
    assert module.repo.conn is None

    manager.open()

    assert main_window.conn is sentinel_conn
    assert module.conn is sentinel_conn
    assert module.repo.conn is sentinel_conn
