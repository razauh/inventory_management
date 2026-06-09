import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from inventory_management.database.repositories.purchases_repo import PurchasesRepo
from inventory_management.database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.vendor import controller as controller_module
from inventory_management.modules.vendor.controller import VendorController
from inventory_management.modules.vendor.payment_history_view import _VendorHistoryDialog


def _payment(amount, *, payment_id=1, state="cleared", date="2026-06-09"):
    return {
        "payment_id": payment_id,
        "purchase_id": "PO-1",
        "date": date,
        "amount": amount,
        "method": "Cash",
        "instrument_no": None,
        "instrument_type": None,
        "bank_account_id": None,
        "vendor_bank_account_id": None,
        "ref_no": None,
        "clearing_state": state,
    }


def _advance(tx_id, amount, source_type, *, date="2026-06-09", **metadata):
    row = {
        "tx_id": tx_id,
        "tx_date": date,
        "amount": amount,
        "source_type": source_type,
        "source_id": "PO-1",
    }
    row.update(metadata)
    return row


def _build_statement(
    monkeypatch,
    *,
    purchases,
    payments=(),
    advances=(),
    opening_advances=(),
    date_from=None,
):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE vendor_advances (
            vendor_id INTEGER,
            tx_date TEXT,
            amount REAL,
            source_type TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO vendor_advances VALUES (1, ?, ?, ?)",
        list(opening_advances),
    )

    purchase_repo = MagicMock()
    purchase_repo.list_purchases_by_vendor.return_value = list(purchases)
    monkeypatch.setattr(controller_module, "PurchasesRepo", lambda _conn: purchase_repo)

    controller = VendorController.__new__(VendorController)
    controller.conn = conn
    controller.ppay = MagicMock()
    controller.ppay.list_payments_for_vendor.return_value = list(payments)
    controller.vadv = MagicMock()
    controller.vadv.list_ledger.return_value = list(advances)

    statement = controller.build_vendor_statement(1, date_from=date_from)
    return conn, statement


def test_purchase_listing_returns_gross_and_net_totals_after_returns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-1', ?, '2026-06-01', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-1', ?, 10, ?, 10, 10, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 3, ?, 'purchase_return', 'purchases', 'PO-1', ?, '2026-06-02')
        """,
        (product_id, uom_id, item_id),
    )

    row = PurchasesRepo(conn).list_purchases_by_vendor(vendor_id)[0]

    assert row["total_amount"] == pytest.approx(100.0)
    assert row["net_total_amount"] == pytest.approx(70.0)
    conn.close()


def test_statement_uses_net_purchase_payment_refund_and_advance_equation(monkeypatch):
    conn, statement = _build_statement(
        monkeypatch,
        purchases=[{"purchase_id": "PO-1", "date": "2026-06-01", "total_amount": 100, "net_total_amount": 80}],
        payments=[_payment(30, payment_id=1), _payment(99, payment_id=3, state="pending")],
        advances=[
            _advance(1, 20, "deposit"),
            _advance(2, 25, "return_credit"),
            _advance(3, -5, "applied_to_purchase"),
        ],
    )

    effects = {row["type"]: row["amount_effect"] for row in statement["rows"]}
    assert effects == {
        "Purchase": pytest.approx(80.0),
        "Cash Payment": pytest.approx(-30.0),
        "Credit Note": pytest.approx(0.0),
        "Credit Applied": pytest.approx(0.0),
    }
    deposit_row = next(row for row in statement["rows"] if row["type"] == "Credit Note" and row["amount_effect"] < 0)
    assert deposit_row["amount_effect"] == pytest.approx(-20.0)
    assert statement["closing_balance"] == pytest.approx(30.0)
    assert statement["totals"] == {
        "purchases": pytest.approx(80.0),
        "cash_paid": pytest.approx(30.0),
        "refunds": pytest.approx(0.0),
        "credit_notes": pytest.approx(45.0),
        "credit_applied": pytest.approx(5.0),
    }
    conn.close()


@pytest.mark.parametrize(
    ("payments", "advances", "expected"),
    [
        ([], [_advance(1, 50, "return_credit")], 50.0),
        ([], [_advance(1, 100, "deposit"), _advance(2, -100, "applied_to_purchase")], -50.0),
    ],
)
def test_statement_settlement_rows_follow_confirmed_effects(monkeypatch, payments, advances, expected):
    conn, statement = _build_statement(
        monkeypatch,
        purchases=[{"purchase_id": "PO-1", "date": "2026-06-01", "total_amount": 100, "net_total_amount": 50}],
        payments=payments,
        advances=advances,
    )

    assert statement["closing_balance"] == pytest.approx(expected)
    conn.close()


def test_statement_exposes_vendor_advance_payment_metadata(monkeypatch):
    conn, statement = _build_statement(
        monkeypatch,
        purchases=[],
        advances=[
            _advance(
                1,
                125,
                "deposit",
                method="Bank Transfer",
                bank_account_id=10,
                vendor_bank_account_id=20,
                instrument_type="online",
                instrument_no="TRX-100",
                instrument_date="2026-06-09",
                clearing_state="cleared",
                ref_no=None,
                temp_vendor_bank_name=None,
                temp_vendor_bank_number=None,
            )
        ],
    )

    row = statement["rows"][0]
    assert row["reference"] == {
        "tx_id": 1,
        "method": "Bank Transfer",
        "bank_account_id": 10,
        "vendor_bank_account_id": 20,
        "instrument_type": "online",
        "instrument_no": "TRX-100",
        "instrument_date": "2026-06-09",
        "clearing_state": "cleared",
        "ref_no": None,
        "temp_vendor_bank_name": None,
        "temp_vendor_bank_number": None,
    }
    conn.close()


def test_statement_opening_payable_uses_complete_preperiod_equation():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-OPEN', ?, '2026-05-01', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-OPEN', ?, 10, ?, 10, 10, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 2, ?, 'purchase_return', 'purchases', 'PO-OPEN', ?, '2026-05-10')
        """,
        (product_id, uom_id, item_id),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, clearing_state
        ) VALUES ('PO-OPEN', '2026-05-15', 30, 'Cash', 'cleared')
        """
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type
        ) VALUES (?, '2026-05-18', 20, 'deposit')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id
        ) VALUES (?, '2026-05-19', 5, 'return_credit', 'PO-OPEN')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-IN', ?, '2026-06-02', 12, 'unpaid')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-IN', ?, 1, ?, 12, 12, 0)
        """,
        (product_id, uom_id),
    )

    controller = VendorController.__new__(VendorController)
    controller.conn = conn
    controller.ppay = PurchasePaymentsRepo(conn)
    controller.vadv = VendorAdvancesRepo(conn)

    statement = controller.build_vendor_statement(vendor_id, date_from="2026-06-01")

    assert statement["opening_credit"] == pytest.approx(20.0)
    assert statement["opening_payable"] == pytest.approx(30.0)
    assert [(row["type"], row["doc_id"]) for row in statement["rows"]] == [("Purchase", "PO-IN")]
    assert statement["closing_balance"] == pytest.approx(42.0)
    conn.close()


def test_fallback_history_uses_refund_and_zero_effect_credit_semantics():
    helper = SimpleNamespace(
        _safe_float=_VendorHistoryDialog._safe_float,
        _flatten_reference=lambda ref: _VendorHistoryDialog._flatten_reference(None, ref),
    )
    rows = _VendorHistoryDialog._build_tx_rows(
        helper,
        {
            "advances": [
                _advance(1, 30, "deposit"),
                _advance(2, 45, "return_credit"),
                _advance(3, -10, "applied_to_purchase"),
            ],
        },
    )

    assert [(row["type"], row["amount_effect"]) for row in rows] == [
        ("Credit Note", pytest.approx(-30.0)),
        ("Credit Note", pytest.approx(0.0)),
        ("Credit Applied", pytest.approx(0.0)),
    ]


def test_fallback_history_includes_vendor_advance_payment_metadata():
    helper = SimpleNamespace(
        _safe_float=_VendorHistoryDialog._safe_float,
        _flatten_reference=lambda ref: _VendorHistoryDialog._flatten_reference(None, ref),
    )
    rows = _VendorHistoryDialog._build_tx_rows(
        helper,
        {
            "advances": [
                _advance(
                    1,
                    125,
                    "deposit",
                    method="Cash Deposit",
                    instrument_no="SLIP-1",
                    instrument_type="cash_deposit",
                    instrument_date="2026-06-09",
                    clearing_state="cleared",
                    bank_account_id=None,
                    vendor_bank_account_id=None,
                    temp_vendor_bank_name="Walk-in Bank",
                    temp_vendor_bank_number="TEMP-123",
                ),
            ],
        },
    )

    row = rows[0]
    assert row["method"] == "Cash Deposit"
    assert row["instrument_no"] == "SLIP-1"
    assert row["temp_vendor_bank_name"] == "Walk-in Bank"
    assert row["temp_vendor_bank_number"] == "TEMP-123"
