from __future__ import annotations

from types import SimpleNamespace


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
