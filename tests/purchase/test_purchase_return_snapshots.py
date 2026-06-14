import sqlite3

import pytest

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import (
    SQL,
    _backfill_purchase_return_snapshots,
    unresolved_purchase_return_count,
)


def _create_purchase(conn, ids, purchase_id="PO-RETURN-SNAPSHOT"):
    repo = PurchasesRepo(conn)
    header = PurchaseHeader(
        purchase_id=purchase_id,
        vendor_id=ids["vendor_id"],
        date="2026-06-01",
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Snapshot test",
        created_by=ids["user_ops"],
    )
    repo.create_purchase(
        header,
        [
            PurchaseItem(
                None, purchase_id, ids["prod_A"], 10.0, ids["uom_piece"],
                12.0, 20.0, 2.0,
            )
        ],
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, clearing_state, cleared_date
        ) VALUES (?, '2026-06-01', 100.0, 'Cash', 'cleared', '2026-06-01')
        """,
        (purchase_id,),
    )
    item_id = int(repo.list_items(purchase_id)[0]["item_id"])
    return repo, header, item_id


def test_repository_and_direct_returns_capture_immutable_snapshots(conn, ids):
    repo, header, item_id = _create_purchase(conn, ids)
    repo.record_return(
        pid=header.purchase_id,
        date="2026-06-02",
        created_by=ids["user_ops"],
        lines=[{"item_id": item_id, "qty_return": 2.0}],
        notes="Repository return",
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 1.5, ?, 'purchase_return', 'purchases', ?, ?, '2026-06-03')
        """,
        (ids["prod_A"], ids["uom_piece"], header.purchase_id, item_id),
    )

    rows = repo.list_return_values_by_purchase(header.purchase_id)
    assert len(rows) == 2
    assert [row["valuation_status"] for row in rows] == ["resolved", "resolved"]
    assert [row["return_date"] for row in rows] == ["2026-06-02", "2026-06-03"]
    assert [float(row["unit_buy_price"]) for row in rows] == [12.0, 12.0]
    assert [float(row["unit_discount"]) for row in rows] == [2.0, 2.0]
    assert [float(row["return_value"]) for row in rows] == [20.0, 15.0]


def test_repository_aborts_entire_return_when_snapshot_capture_is_missing(conn, ids):
    repo, header, item_id = _create_purchase(conn, ids, "PO-RETURN-MISSING-SNAPSHOT")
    conn.execute("DROP TRIGGER trg_purchase_return_snapshot_insert")

    with pytest.raises(sqlite3.IntegrityError, match="snapshot capture failed"):
        repo.record_return(
            pid=header.purchase_id,
            date="2026-06-02",
            created_by=ids["user_ops"],
            lines=[{"item_id": item_id, "qty_return": 2.0}],
            notes="Must roll back",
            settlement={"mode": "credit_note"},
        )

    assert conn.execute(
        "SELECT 1 FROM inventory_transactions WHERE transaction_type='purchase_return' AND reference_id=?",
        (header.purchase_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM vendor_advances WHERE source_type='return_credit' AND source_id=?",
        (header.purchase_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM audit_logs WHERE action_type='return' AND record_id=?",
        (header.purchase_id,),
    ).fetchone() is None


def test_price_correction_only_affects_later_returns_and_not_existing_credit(conn, ids):
    repo, header, item_id = _create_purchase(conn, ids, "PO-RETURN-PRICE-CORRECTION")
    repo.record_return(
        pid=header.purchase_id,
        date="2026-06-02",
        created_by=ids["user_ops"],
        lines=[{"item_id": item_id, "qty_return": 2.0}],
        notes="First return",
        settlement={"mode": "credit_note"},
    )

    repo.update_purchase(
        header,
        [
            PurchaseItem(
                item_id, header.purchase_id, ids["prod_A"], 10.0,
                ids["uom_piece"], 15.0, 20.0, 3.0,
            )
        ],
    )
    repo.record_return(
        pid=header.purchase_id,
        date="2026-06-04",
        created_by=ids["user_ops"],
        lines=[{"item_id": item_id, "qty_return": 1.0}],
        notes="Second return",
    )

    rows = repo.list_return_values_by_purchase(header.purchase_id)
    assert [float(row["unit_buy_price"]) for row in rows] == [12.0, 15.0]
    assert [float(row["unit_discount"]) for row in rows] == [2.0, 3.0]
    assert [float(row["return_value"]) for row in rows] == [20.0, 12.0]
    credit = conn.execute(
        "SELECT amount FROM vendor_advances WHERE source_type='return_credit' AND source_id=?",
        (header.purchase_id,),
    ).fetchone()
    assert float(credit["amount"]) == 20.0


def test_snapshot_and_snapshotted_return_financial_fields_are_immutable(conn, ids):
    repo, header, item_id = _create_purchase(conn, ids, "PO-RETURN-GUARDS")
    repo.record_return(
        pid=header.purchase_id,
        date="2026-06-02",
        created_by=ids["user_ops"],
        lines=[{"item_id": item_id, "qty_return": 2.0}],
        notes="Guarded return",
    )
    transaction_id = conn.execute(
        "SELECT transaction_id FROM purchase_return_snapshots WHERE purchase_id=?",
        (header.purchase_id,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="snapshots are immutable"):
        conn.execute(
            "UPDATE purchase_return_snapshots SET return_value=999 WHERE transaction_id=?",
            (transaction_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="source purchase return"):
        conn.execute(
            "DELETE FROM purchase_return_snapshots WHERE transaction_id=?",
            (transaction_id,),
        )
    for column, value in (("quantity", 1), ("date", "2026-06-05"), ("reference_id", "OTHER")):
        with pytest.raises(sqlite3.IntegrityError, match="financial fields are immutable"):
            conn.execute(
                f"UPDATE inventory_transactions SET {column}=? WHERE transaction_id=?",
                (value, transaction_id),
            )

    conn.execute(
        "DELETE FROM inventory_transactions WHERE transaction_id=?",
        (transaction_id,),
    )
    assert conn.execute(
        "SELECT 1 FROM purchase_return_snapshots WHERE transaction_id=?",
        (transaction_id,),
    ).fetchone() is None


def test_legacy_backfill_leaves_orphaned_returns_unresolved():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
        ) VALUES ('PO-LEGACY', ?, '2026-01-01', 50, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-LEGACY', ?, 5, ?, 10, 12, 1)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute("DROP TRIGGER trg_purchase_return_snapshot_insert")
    conn.execute("DROP TRIGGER trg_inventory_ref_validate")
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 2, ?, 'purchase_return', 'purchases', 'PO-LEGACY', ?, '2026-01-02')
        """,
        (product_id, uom_id, item_id),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 1, ?, 'purchase_return', 'purchases', 'PO-LEGACY', 999999, '2026-01-03')
        """,
        (product_id, uom_id),
    )

    _backfill_purchase_return_snapshots(conn)

    rows = conn.execute(
        "SELECT valuation_status, return_value FROM purchase_return_valuations ORDER BY transaction_id"
    ).fetchall()
    assert rows[0]["valuation_status"] == "resolved"
    assert float(rows[0]["return_value"]) == 18.0
    assert rows[1]["valuation_status"] == "unresolved"
    assert rows[1]["return_value"] is None
    assert unresolved_purchase_return_count(conn) == 1
    conn.close()
