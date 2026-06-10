from __future__ import annotations

import sqlite3

from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.inventory_reports import InventoryReports


def _inventory_report_db(path: str) -> tuple[sqlite3.Connection, int]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    base_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES (?)",
        ("Each",),
    ).lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES (?)",
        ("Old Widget",),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, base_uom_id),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type, date, txn_seq, notes
        ) VALUES (?, ?, ?, 'adjustment', '2026-06-01', 10, 'seed row')
        """,
        (product_id, 1, base_uom_id),
    )
    conn.commit()
    return conn, int(product_id)


def test_inventory_reports_refresh_product_cache_updates_transaction_names(tmp_path):
    conn, product_id = _inventory_report_db(str(tmp_path / "inventory_reports_cache.sqlite"))
    try:
        InventoryReports._product_cache = {product_id: "Stale Widget"}
        InventoryReports._cache_initialized = True

        reports = InventoryReports(conn)

        stale_rows = reports.transactions("2026-06-01", "2026-06-30", product_id)
        assert stale_rows == [
            {
                "date": "2026-06-01",
                "product_name": "Stale Widget",
                "type": "adjustment",
                "quantity": 1.0,
                "unit_name": "Each",
                "qty_base": 1.0,
                "ref_table": "",
                "ref_id": "",
                "notes": "seed row",
            }
        ]

        conn.execute(
            "UPDATE products SET name = ? WHERE product_id = ?",
            ("Fresh Widget", product_id),
        )
        conn.commit()

        reports.refresh_product_cache(conn)

        fresh_rows = reports.transactions("2026-06-01", "2026-06-30", product_id)
        assert fresh_rows == [
            {
                "date": "2026-06-01",
                "product_name": "Fresh Widget",
                "type": "adjustment",
                "quantity": 1.0,
                "unit_name": "Each",
                "qty_base": 1.0,
                "ref_table": "",
                "ref_id": "",
                "notes": "seed row",
            }
        ]
        assert InventoryReports._product_cache[product_id] == "Fresh Widget"
    finally:
        InventoryReports._product_cache = {}
        InventoryReports._cache_initialized = False
        conn.close()
