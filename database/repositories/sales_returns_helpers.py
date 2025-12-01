from __future__ import annotations

from typing import Dict
import sqlite3


def get_returnable_quantities(conn: sqlite3.Connection, sale_id: str) -> Dict[int, float]:
    """
    Compute remaining returnable quantity per sale item for a given sale.

    Returns a dict mapping item_id -> remaining_qty (float, clamped to >= 0.0).
    """
    sql = """
    SELECT
      si.item_id,
      SUM(CAST(si.quantity AS REAL)) AS sold_qty,
      COALESCE((
        SELECT SUM(CAST(it.quantity AS REAL))
        FROM inventory_transactions it
        WHERE it.transaction_type = 'sale_return'
          AND it.reference_table = 'sales'
          AND it.reference_id = si.sale_id
          AND it.reference_item_id = si.item_id
      ), 0.0) AS returned_so_far
    FROM sale_items si
    WHERE si.sale_id = ?
    GROUP BY si.item_id
    """
    rows = conn.execute(sql, (sale_id,)).fetchall()
    out: Dict[int, float] = {}
    for r in rows:
        if hasattr(r, "keys"):
            item_id = int(r["item_id"])
            sold_qty = float(r["sold_qty"])
            returned_so_far = float(r["returned_so_far"])
        else:
            item_id = int(r[0])
            sold_qty = float(r[1])
            returned_so_far = float(r[2])
        remaining = max(0.0, sold_qty - returned_so_far)
        out[item_id] = remaining
    return out
