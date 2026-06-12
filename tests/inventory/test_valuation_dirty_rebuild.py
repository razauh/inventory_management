import sqlite3

import pytest

from inventory_management.database.repositories.inventory_repo import (
    InventoryRepo,
    rebuild_dirty_valuations,
)
from inventory_management.database.repositories.dashboard_repo import DashboardRepo
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def valuation_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Valuation Vendor', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Valuation Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    try:
        yield conn, int(vendor_id), int(product_id), int(uom_id)
    finally:
        conn.close()


def _insert_purchase(conn, vendor_id, product_id, uom_id, purchase_id, date, qty, price, seq):
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES (?, ?, ?, ?, 'unpaid')
        """,
        (purchase_id, vendor_id, date, qty * price),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (purchase_id, product_id, qty, uom_id, price, price + 5),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?)
        """,
        (product_id, qty, uom_id, purchase_id, item_id, date, seq),
    )
    return int(item_id)


def test_stock_on_hand_reads_stale_snapshot_without_rebuilding_dirty_valuation(valuation_db):
    conn, vendor_id, product_id, uom_id = valuation_db
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-LATE", "2026-01-10", 10, 10, 10)
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-EARLY", "2026-01-01", 10, 20, 10)

    dirty = conn.execute("SELECT * FROM valuation_dirty WHERE product_id=?", (product_id,)).fetchone()
    assert dirty is not None
    assert dirty["earliest_impacted"] == "2026-01-01"

    stale = conn.execute(
        "SELECT qty_in_base, unit_value, total_value FROM v_stock_on_hand WHERE product_id=?",
        (product_id,),
    ).fetchone()
    assert float(stale["qty_in_base"]) == pytest.approx(10.0)
    assert float(stale["unit_value"]) == pytest.approx(20.0)

    dirty_before = conn.execute(
        "SELECT COUNT(*) AS c FROM valuation_dirty WHERE product_id=?",
        (product_id,),
    ).fetchone()["c"]
    history_before = conn.execute(
        "SELECT COUNT(*) AS c FROM stock_valuation_history WHERE product_id=?",
        (product_id,),
    ).fetchone()["c"]
    changes_before = conn.total_changes

    snapshot = InventoryRepo(conn).stock_on_hand(product_id)

    assert snapshot["on_hand_qty"] == pytest.approx(10.0)
    assert snapshot["unit_value"] == pytest.approx(20.0)
    assert snapshot["total_value"] == pytest.approx(200.0)
    assert (
        conn.execute(
            "SELECT COUNT(*) AS c FROM valuation_dirty WHERE product_id=?",
            (product_id,),
        ).fetchone()["c"]
        == dirty_before
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) AS c FROM stock_valuation_history WHERE product_id=?",
            (product_id,),
        ).fetchone()["c"]
        == history_before
    )
    assert conn.total_changes == changes_before


def test_rebuild_replays_purchase_price_changes_from_dirty_date(valuation_db):
    conn, vendor_id, product_id, uom_id = valuation_db
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-ONE", "2026-01-01", 10, 20, 10)
    item_id = _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-TWO", "2026-01-10", 10, 10, 10)

    conn.execute(
        "UPDATE purchase_items SET purchase_price = 14 WHERE item_id = ?",
        (item_id,),
    )
    dirty = conn.execute("SELECT * FROM valuation_dirty WHERE product_id=?", (product_id,)).fetchone()
    assert dirty is not None
    assert dirty["earliest_impacted"] == "2026-01-10"

    rebuilt = rebuild_dirty_valuations(conn, product_id)
    snapshot = conn.execute(
        "SELECT qty_in_base, unit_value, total_value FROM v_stock_on_hand WHERE product_id=?",
        (product_id,),
    ).fetchone()

    assert rebuilt == 1
    assert float(snapshot["qty_in_base"]) == pytest.approx(20.0)
    assert float(snapshot["unit_value"]) == pytest.approx(17.0)
    assert float(snapshot["total_value"]) == pytest.approx(340.0)
    assert conn.execute("SELECT 1 FROM valuation_dirty WHERE product_id=?", (product_id,)).fetchone() is None


def test_read_only_valuation_helpers_do_not_mutate_dirty_state(valuation_db):
    conn, vendor_id, product_id, uom_id = valuation_db
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-LATE", "2026-01-10", 10, 10, 10)
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-EARLY", "2026-01-01", 10, 20, 10)
    conn.execute(
        "UPDATE products SET min_stock_level = 100 WHERE product_id = ?",
        (product_id,),
    )

    dirty_before = conn.execute(
        "SELECT COUNT(*) AS c FROM valuation_dirty WHERE product_id=?",
        (product_id,),
    ).fetchone()["c"]
    history_before = conn.execute(
        "SELECT COUNT(*) AS c FROM stock_valuation_history WHERE product_id=?",
        (product_id,),
    ).fetchone()["c"]
    changes_before = conn.total_changes

    reporting = ReportingRepo(conn)
    dashboard = DashboardRepo(conn)
    inventory = InventoryRepo(conn)
    products = ProductsRepo(conn)

    current_rows = reporting.stock_on_hand_current()
    current_iter_rows = list(reporting.stock_on_hand_current_iter())
    as_of_rows = reporting.stock_on_hand_as_of("2026-01-31")
    as_of_iter_rows = list(reporting.stock_on_hand_as_of_iter("2026-01-31"))
    valuation_rows = reporting.valuation_history(product_id, 10)
    low_stock_count = dashboard.low_stock_count()
    low_stock_rows = dashboard.low_stock_rows(limit_n=10)
    stock_snapshot = inventory.stock_on_hand(product_id)
    on_hand_base = products.on_hand_base(product_id)

    assert current_rows
    assert current_iter_rows
    assert as_of_rows
    assert as_of_iter_rows
    assert valuation_rows
    assert low_stock_count == 1
    assert low_stock_rows
    assert low_stock_rows[0]["product_id"] == product_id
    assert stock_snapshot["on_hand_qty"] == pytest.approx(10.0)
    assert on_hand_base == pytest.approx(10.0)
    assert (
        conn.execute(
            "SELECT COUNT(*) AS c FROM valuation_dirty WHERE product_id=?",
            (product_id,),
        ).fetchone()["c"]
        == dirty_before
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) AS c FROM stock_valuation_history WHERE product_id=?",
            (product_id,),
        ).fetchone()["c"]
        == history_before
    )
    assert conn.total_changes == changes_before
