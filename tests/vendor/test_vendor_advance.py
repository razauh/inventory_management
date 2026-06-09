import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from inventory_management.database.repositories.vendor_advances_repo import (
    InvalidPurchaseReferenceError,
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.vendor.controller import VendorController


class TrackingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, parameters=()):
        self.statements.append((sql, parameters))
        return MagicMock()


def make_controller():
    controller = VendorController.__new__(VendorController)
    controller.conn = TrackingConnection()
    controller.repo = MagicMock()
    controller.vadv = MagicMock()
    controller.view = SimpleNamespace()
    controller._selected_id = MagicMock(return_value=7)
    controller._list_company_bank_accounts = MagicMock(return_value=[])
    controller._list_vendor_bank_accounts = MagicMock(return_value=[])
    controller._reload = MagicMock()
    return controller


@pytest.fixture()
def vendor_credit_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Test Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_a = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor A', 'A')"
    ).lastrowid
    vendor_b = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor B', 'B')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-A', ?, '2026-06-09', 100, 'unpaid')
        """,
        (vendor_a,),
    )
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-B', ?, '2026-06-09', 100, 'unpaid')
        """,
        (vendor_b,),
    )
    conn.executemany(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES (?, ?, 1, ?, 100, 100, 0)
        """,
        (("PO-A", product_id, uom_id), ("PO-B", product_id, uom_id)),
    )

    try:
        yield conn, VendorAdvancesRepo(conn), int(vendor_a), int(vendor_b)
    finally:
        conn.close()


def grant_credit(repo, vendor_id, amount=100.0):
    return repo.grant_credit(
        vendor_id=vendor_id,
        amount=amount,
        date="2026-06-09",
        notes=None,
        created_by=None,
    )


def test_repository_rejects_credit_for_another_vendors_purchase(vendor_credit_db):
    conn, repo, vendor_a, vendor_b = vendor_credit_db
    grant_credit(repo, vendor_a)

    with pytest.raises(InvalidPurchaseReferenceError):
        repo.apply_credit_to_purchase(
            vendor_id=vendor_a,
            purchase_id="PO-B",
            amount=40.0,
            date="2026-06-09",
            notes=None,
            created_by=None,
        )

    assert repo.get_balance(vendor_a) == pytest.approx(100.0)
    assert repo.get_balance(vendor_b) == pytest.approx(0.0)
    assert conn.execute(
        "SELECT advance_payment_applied FROM purchases WHERE purchase_id = 'PO-B'"
    ).fetchone()[0] == pytest.approx(0.0)
    assert conn.execute(
        "SELECT COUNT(*) FROM vendor_advances WHERE source_type = 'applied_to_purchase'"
    ).fetchone()[0] == 0


def test_schema_rejects_cross_vendor_credit_insert(vendor_credit_db):
    conn, repo, vendor_a, _vendor_b = vendor_credit_db
    grant_credit(repo, vendor_a)

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Invalid purchase reference for vendor credit application",
    ):
        conn.execute(
            """
            INSERT INTO vendor_advances (
                vendor_id, tx_date, amount, source_type, source_id
            ) VALUES (?, '2026-06-09', -25, 'applied_to_purchase', 'PO-B')
            """,
            (vendor_a,),
        )


def test_schema_rejects_cross_vendor_credit_update(vendor_credit_db):
    conn, repo, vendor_a, vendor_b = vendor_credit_db
    grant_credit(repo, vendor_a)
    grant_credit(repo, vendor_b)
    tx_id = repo.apply_credit_to_purchase(
        vendor_id=vendor_a,
        purchase_id="PO-A",
        amount=20.0,
        date="2026-06-09",
        notes=None,
        created_by=None,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Invalid purchase reference for vendor credit application",
    ):
        conn.execute(
            "UPDATE vendor_advances SET vendor_id = ? WHERE tx_id = ?",
            (vendor_b, tx_id),
        )

    row = conn.execute(
        "SELECT vendor_id, source_id FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()
    assert (row["vendor_id"], row["source_id"]) == (vendor_a, "PO-A")


def test_same_vendor_credit_application_still_succeeds(vendor_credit_db):
    conn, repo, vendor_a, _vendor_b = vendor_credit_db
    grant_credit(repo, vendor_a)

    repo.apply_credit_to_purchase(
        vendor_id=vendor_a,
        purchase_id="PO-A",
        amount=40.0,
        date="2026-06-09",
        notes=None,
        created_by=None,
    )

    assert repo.get_balance(vendor_a) == pytest.approx(60.0)
    assert conn.execute(
        "SELECT advance_payment_applied FROM purchases WHERE purchase_id = 'PO-A'"
    ).fetchone()[0] == pytest.approx(40.0)


def test_unknown_purchase_keeps_invalid_reference_error(vendor_credit_db):
    _conn, repo, vendor_a, _vendor_b = vendor_credit_db
    grant_credit(repo, vendor_a)

    with pytest.raises(InvalidPurchaseReferenceError):
        repo.apply_credit_to_purchase(
            vendor_id=vendor_a,
            purchase_id="PO-MISSING",
            amount=10.0,
            date="2026-06-09",
            notes=None,
            created_by=None,
        )


def test_apply_advance_records_credit_once_after_dialog_accepts():
    payload = {
        "vendor_id": 7,
        "amount": 125.0,
        "date": "2026-06-09",
        "notes": "Advance",
    }
    controller = make_controller()
    controller.vadv.grant_credit.return_value = 42

    with (
        patch(
            "inventory_management.modules.vendor.payment_dialog.open_vendor_money_form",
            return_value=payload,
        ) as open_form,
        patch("inventory_management.modules.vendor.controller.info") as show_info,
    ):
        controller._on_apply_advance_dialog()

    defaults = open_form.call_args.kwargs["defaults"]
    assert "submit_advance" not in defaults
    controller.vadv.grant_credit.assert_called_once_with(
        vendor_id=7,
        amount=125.0,
        date="2026-06-09",
        notes="Advance",
        created_by=None,
        source_id=None,
        source_type="deposit",
    )
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT apply_advance",
        "RELEASE apply_advance",
    ]
    controller._reload.assert_called_once_with()
    show_info.assert_called_once_with(
        controller.view,
        "Recorded",
        "Advance payment of 125.00 recorded successfully (Tx #42).",
    )


def test_apply_advance_rolls_back_when_credit_cannot_be_recorded():
    payload = {
        "vendor_id": 7,
        "amount": 125.0,
        "date": "2026-06-09",
        "notes": "Advance",
    }
    controller = make_controller()
    controller.vadv.grant_credit.side_effect = ValueError("credit rejected")

    with (
        patch(
            "inventory_management.modules.vendor.payment_dialog.open_vendor_money_form",
            return_value=payload,
        ),
        patch("inventory_management.modules.vendor.controller.info") as show_info,
    ):
        controller._on_apply_advance_dialog()

    controller.vadv.grant_credit.assert_called_once()
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT apply_advance",
        "ROLLBACK TO apply_advance",
        "RELEASE apply_advance",
    ]
    controller._reload.assert_not_called()
    show_info.assert_called_once_with(
        controller.view,
        "Not recorded",
        "credit rejected",
    )


def test_grant_credit_preview_uses_fifo_purchase_date_then_purchase_id():
    controller = make_controller()
    controller.repo.get_open_purchases_for_vendor.return_value = [
        {"purchase_id": "P-103", "date": "2026-01-10"},
        {"purchase_id": "P-102", "date": "2026-01-05"},
        {"purchase_id": "P-101", "date": "2026-01-01"},
        {"purchase_id": "P-100", "date": "2026-01-01"},
    ]
    dues = {
        "P-100": 100.0,
        "P-101": 300.0,
        "P-102": 500.0,
        "P-103": 400.0,
    }
    controller._remaining_due_for_purchase = MagicMock(side_effect=lambda purchase_id: dues[purchase_id])

    preview = controller._build_grant_credit_allocation_preview(7, 700.0)

    assert [row["purchase_id"] for row in preview["rows"]] == ["P-100", "P-101", "P-102"]
    assert [row["amount_to_apply"] for row in preview["rows"]] == pytest.approx([100.0, 300.0, 300.0])
    assert preview["remaining_credit"] == pytest.approx(0.0)


def test_grant_credit_preview_leaves_excess_credit_available():
    controller = make_controller()
    controller.repo.get_open_purchases_for_vendor.return_value = [
        {"purchase_id": "P-101", "date": "2026-01-01"},
        {"purchase_id": "P-102", "date": "2026-01-05"},
    ]
    dues = {"P-101": 300.0, "P-102": 500.0}
    controller._remaining_due_for_purchase = MagicMock(side_effect=lambda purchase_id: dues[purchase_id])

    preview = controller._build_grant_credit_allocation_preview(7, 1000.0)

    assert [row["amount_to_apply"] for row in preview["rows"]] == pytest.approx([300.0, 500.0])
    assert preview["remaining_credit"] == pytest.approx(200.0)


def test_grant_credit_and_auto_apply_saves_in_preview_order_atomically():
    controller = make_controller()
    controller.repo.get_open_purchases_for_vendor.return_value = [
        {"purchase_id": "P-102", "date": "2026-01-05"},
        {"purchase_id": "P-101", "date": "2026-01-01"},
    ]
    dues = {"P-101": 300.0, "P-102": 500.0}
    controller._remaining_due_for_purchase = MagicMock(side_effect=lambda purchase_id: dues[purchase_id])
    controller.vadv.grant_credit.return_value = 42

    result = controller._grant_credit_and_auto_apply(7, 700.0, "2026-06-09", "Credit memo")

    assert [statement for statement, _ in controller.conn.statements] == [
        "BEGIN IMMEDIATE",
        "COMMIT",
    ]
    assert controller.vadv.method_calls == [
        call.grant_credit(
            vendor_id=7,
            amount=700.0,
            date="2026-06-09",
            notes="Credit memo",
            created_by=None,
            source_id=None,
        ),
        call.apply_credit_to_purchase(
            vendor_id=7,
            purchase_id="P-101",
            amount=300.0,
            date="2026-06-09",
            notes="Auto-applied from vendor advance (Tx #42)",
            created_by=None,
        ),
        call.apply_credit_to_purchase(
            vendor_id=7,
            purchase_id="P-102",
            amount=400.0,
            date="2026-06-09",
            notes="Auto-applied from vendor advance (Tx #42)",
            created_by=None,
        ),
    ]
    assert result["applied_amount"] == pytest.approx(700.0)
    assert result["remaining_credit"] == pytest.approx(0.0)


def test_grant_credit_and_auto_apply_rolls_back_when_application_fails():
    controller = make_controller()
    controller.repo.get_open_purchases_for_vendor.return_value = [
        {"purchase_id": "P-101", "date": "2026-01-01"},
    ]
    controller._remaining_due_for_purchase = MagicMock(return_value=300.0)
    controller.vadv.grant_credit.return_value = 42
    controller.vadv.apply_credit_to_purchase.side_effect = ValueError("cannot apply")

    with pytest.raises(ValueError, match="cannot apply"):
        controller._grant_credit_and_auto_apply(7, 100.0, "2026-06-09", None)

    assert [statement for statement, _ in controller.conn.statements] == [
        "BEGIN IMMEDIATE",
        "ROLLBACK",
    ]
