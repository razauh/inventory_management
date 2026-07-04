"""Test that main() handles missing updater module gracefully."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module


def test_main_does_not_crash_when_updater_unavailable(monkeypatch):
    """main() runs without crash when updater import would fail."""
    def fake_get_updater_controller(self):
        return None
    monkeypatch.setattr(
        main_module.MainWindow,
        "_get_updater_controller",
        fake_get_updater_controller,
    )

    def fake_bootstrap():
        pass
    monkeypatch.setattr(main_module, "_bootstrap_inventory_management_namespace", fake_bootstrap)

    def fake_get_connection():
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    monkeypatch.setattr(main_module, "get_connection", fake_get_connection)

    def fake_unresolved_return_count(conn):
        return 0
    monkeypatch.setattr(
        main_module,
        "get_unresolved_purchase_return_count",
        fake_unresolved_return_count,
    )

    monkeypatch.setattr(main_module, "load_qss", lambda: "")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    try:
        main_module.main()
    except Exception as exc:
        pytest.fail(f"main() raised {type(exc).__name__}: {exc}")