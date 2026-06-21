import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import (
    AccountingService,
    VendorAdvancePayload,
)


@pytest.fixture()
def advance_allocation_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Item')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'V')"
    ).lastrowid

    try:
        yield conn, int(vendor_id), int(product_id), int(uom_id)
    finally:
        conn.close()


def _add_purchase(conn, vendor_id, product_id, uom_id, purchase_id, date, total):
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES (?, ?, ?, ?, 'unpaid')
        """,
        (purchase_id, vendor_id, date, total),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES (?, ?, 1, ?, ?, ?, 0)
        """,
        (purchase_id, product_id, uom_id, total, total + 10),
    )


def test_preview_vendor_advance_allocation_preserves_fifo_order(advance_allocation_db):
    conn, vendor_id, product_id, uom_id = advance_allocation_db
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-103", "2026-01-10", 400)
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-102", "2026-01-05", 500)
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-101", "2026-01-01", 300)
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-100", "2026-01-01", 100)

    preview = AccountingService(conn).preview_vendor_advance_allocation(
        vendor_id,
        Decimal("700"),
    )

    assert [row["purchase_id"] for row in preview["rows"]] == [
        "P-100",
        "P-101",
        "P-102",
    ]
    assert [row["amount_to_apply"] for row in preview["rows"]] == pytest.approx(
        [100.0, 300.0, 300.0]
    )
    assert preview["remaining_credit"] == pytest.approx(0.0)


def test_preview_vendor_advance_allocation_keeps_excess_credit(advance_allocation_db):
    conn, vendor_id, product_id, uom_id = advance_allocation_db
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-101", "2026-01-01", 300)
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-102", "2026-01-05", 500)

    preview = AccountingService(conn).preview_vendor_advance_allocation(
        vendor_id,
        Decimal("1000"),
    )

    assert [row["amount_to_apply"] for row in preview["rows"]] == pytest.approx(
        [300.0, 500.0]
    )
    assert preview["remaining_credit"] == pytest.approx(200.0)


def test_record_vendor_advance_with_auto_apply_preserves_fifo_rows(
    advance_allocation_db,
):
    conn, vendor_id, product_id, uom_id = advance_allocation_db
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-102", "2026-01-05", 500)
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-101", "2026-01-01", 300)
    conn.commit()

    result = AccountingService(conn).record_vendor_advance_with_auto_apply(
        VendorAdvancePayload(
            vendor_id=vendor_id,
            amount=Decimal("700"),
            date="2026-06-09",
            notes="Credit memo",
        )
    )

    assert [row["purchase_id"] for row in result["rows"]] == ["P-101", "P-102"]
    assert [row["amount_to_apply"] for row in result["rows"]] == pytest.approx(
        [300.0, 400.0]
    )
    assert result["applied_amount"] == pytest.approx(700.0)
    assert result["remaining_credit"] == pytest.approx(0.0)
    ledger = conn.execute(
        """
        SELECT amount, source_type, source_id, notes
        FROM vendor_advances
        ORDER BY tx_id
        """
    ).fetchall()
    ledger_keys = [
        (row["amount"], row["source_type"], row["source_id"]) for row in ledger
    ]
    assert ledger_keys == [
        (700, "deposit", None),
        (-300, "applied_to_purchase", "P-101"),
        (-400, "applied_to_purchase", "P-102"),
    ]
    assert [row["notes"] for row in ledger[1:]] == [
        f"Auto-applied from vendor advance (Tx #{result['tx_id']})",
        f"Auto-applied from vendor advance (Tx #{result['tx_id']})",
    ]


def test_record_vendor_advance_with_auto_apply_preserves_rollback(
    advance_allocation_db,
):
    conn, vendor_id, product_id, uom_id = advance_allocation_db
    _add_purchase(conn, vendor_id, product_id, uom_id, "P-101", "2026-01-01", 300)
    conn.execute(
        """
        CREATE TRIGGER fail_vendor_auto_apply
        BEFORE INSERT ON vendor_advances
        WHEN NEW.source_type = 'applied_to_purchase'
        BEGIN
            SELECT RAISE(ABORT, 'cannot apply');
        END
        """
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="cannot apply"):
        AccountingService(conn).record_vendor_advance_with_auto_apply(
            VendorAdvancePayload(
                vendor_id=vendor_id,
                amount=Decimal("100"),
                date="2026-06-09",
                notes="Credit memo",
            )
        )

    assert conn.execute("SELECT COUNT(*) FROM vendor_advances").fetchone()[0] == 0
