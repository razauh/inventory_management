import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from inventory_management.modules.purchase.controller import PurchaseController


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "purchase_transactions.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE purchases (purchase_id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE vendor_advances (advance_id INTEGER PRIMARY KEY, purchase_id TEXT NOT NULL)"
    )
    conn.commit()
    try:
        yield path, conn
    finally:
        conn.close()


def _controller(conn):
    controller = PurchaseController.__new__(PurchaseController)
    controller.conn = conn
    controller.view = None
    controller.user = None
    controller._reload = MagicMock()
    return controller


def _visible_count(path, table):
    with sqlite3.connect(path) as observer:
        return observer.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_vendor_credit_commits_before_reporting_success(database):
    path, conn = database
    controller = _controller(conn)
    controller._selected_row_dict = lambda: {"purchase_id": "PO-1", "vendor_id": 7}
    controller._remaining_due_header = lambda purchase_id: 50.0
    controller._vendor_credit_balance = lambda vendor_id: 50.0
    controller.vadv = MagicMock()
    controller.vadv.apply_credit_to_purchase.side_effect = lambda **kwargs: conn.execute(
        "INSERT INTO vendor_advances (purchase_id) VALUES (?)", (kwargs["purchase_id"],)
    )

    with patch("inventory_management.modules.purchase.controller.info") as show_info:
        controller.apply_vendor_credit(amount=20.0, date="2026-06-10")

    assert not conn.in_transaction
    assert _visible_count(path, "vendor_advances") == 1
    show_info.assert_called_once_with(None, "Saved", "Applied vendor credit of 20 to PO-1.")
    controller._reload.assert_called_once_with()


def test_vendor_credit_rolls_back_partial_write_and_does_not_report_success(database):
    path, conn = database
    controller = _controller(conn)
    controller._selected_row_dict = lambda: {"purchase_id": "PO-1", "vendor_id": 7}
    controller._remaining_due_header = lambda purchase_id: 50.0
    controller._vendor_credit_balance = lambda vendor_id: 50.0
    controller.vadv = MagicMock()

    def fail_after_insert(**kwargs):
        conn.execute(
            "INSERT INTO vendor_advances (purchase_id) VALUES (?)", (kwargs["purchase_id"],)
        )
        raise sqlite3.OperationalError("forced credit failure")

    controller.vadv.apply_credit_to_purchase.side_effect = fail_after_insert

    with patch("inventory_management.modules.purchase.controller.info") as show_info:
        controller.apply_vendor_credit(amount=20.0, date="2026-06-10")

    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM vendor_advances").fetchone()[0] == 0
    assert _visible_count(path, "vendor_advances") == 0
    assert show_info.call_args.args[1] == "Credit not applied"
    controller._reload.assert_not_called()
