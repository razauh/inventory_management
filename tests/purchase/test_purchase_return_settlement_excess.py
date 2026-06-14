import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.purchases_repo import PurchasesRepo
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL


@pytest.fixture()
def return_settlement_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Return Settlement Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Return Vendor', 'Test')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-RETURN-SETTLEMENT', ?, '2026-06-01', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-RETURN-SETTLEMENT', ?, 10, ?, 10, 12, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (
            ?, 10, ?, 'purchase', 'purchases',
            'PO-RETURN-SETTLEMENT', ?, '2026-06-01', 10
        )
        """,
        (product_id, uom_id, item_id),
    )

    try:
        yield conn, int(vendor_id), int(item_id)
    finally:
        conn.close()


def _record_payment(conn, amount):
    if amount <= 0:
        return
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-RETURN-SETTLEMENT",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-01",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-01",
        created_by=None,
    )


def _apply_advance(conn, vendor_id, amount):
    if amount <= 0:
        return
    repo = VendorAdvancesRepo(conn)
    repo.grant_credit(
        vendor_id,
        amount,
        date="2026-06-01",
        notes="Advance for return settlement test",
        created_by=None,
    )
    repo.apply_credit_to_purchase(
        vendor_id,
        "PO-RETURN-SETTLEMENT",
        amount,
        date="2026-06-01",
        notes="Applied advance for return settlement test",
        created_by=None,
    )


def _record_return(conn, item_id, qty, mode="credit_note"):
    settlement = {"mode": mode}
    if mode == "refund_now":
        settlement.update({"method": "Cash", "clearing_state": "cleared"})
    PurchasesRepo(conn).record_return(
        pid="PO-RETURN-SETTLEMENT",
        date="2026-06-02",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": qty}],
        notes="Return settlement test",
        settlement=settlement,
    )


@pytest.mark.parametrize(
    ("paid", "advance", "return_qty", "mode", "expected_net", "expected_credit"),
    [
        (0.0, 0.0, 10.0, "credit_note", 0.0, 0.0),
        (30.0, 0.0, 4.0, "credit_note", 60.0, 0.0),
        (80.0, 0.0, 4.0, "credit_note", 60.0, 20.0),
        (100.0, 0.0, 4.0, "refund_now", 60.0, 40.0),
        (50.0, 30.0, 4.0, "credit_note", 60.0, 20.0),
    ],
)
def test_return_settlement_uses_only_post_return_funded_excess(
    return_settlement_db,
    paid,
    advance,
    return_qty,
    mode,
    expected_net,
    expected_credit,
):
    conn, vendor_id, item_id = return_settlement_db
    _record_payment(conn, paid)
    _apply_advance(conn, vendor_id, advance)

    _record_return(conn, item_id, return_qty, mode)

    net_total = conn.execute(
        """
        SELECT calculated_total_amount
        FROM purchase_detailed_totals
        WHERE purchase_id = 'PO-RETURN-SETTLEMENT'
        """
    ).fetchone()[0]
    if mode == "refund_now":
        return_credit = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM purchase_refunds
            WHERE purchase_id = 'PO-RETURN-SETTLEMENT'
            """
        ).fetchone()[0]
        expected_balance = 0.0
    else:
        return_credit = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM vendor_advances
            WHERE source_type = 'return_credit'
              AND source_id = 'PO-RETURN-SETTLEMENT'
            """
        ).fetchone()[0]
        expected_balance = expected_credit

    assert float(net_total) == pytest.approx(expected_net)
    assert float(return_credit) == pytest.approx(expected_credit)
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(
        expected_balance
    )


def test_sequential_returns_grant_only_incremental_excess(return_settlement_db):
    conn, _vendor_id, item_id = return_settlement_db
    _record_payment(conn, 100.0)

    _record_return(conn, item_id, 2.0)
    _record_return(conn, item_id, 1.0)

    credits = conn.execute(
        """
        SELECT amount
        FROM vendor_advances
        WHERE source_type = 'return_credit'
          AND source_id = 'PO-RETURN-SETTLEMENT'
        ORDER BY tx_id
        """
    ).fetchall()

    assert [float(row["amount"]) for row in credits] == pytest.approx([20.0, 10.0])
