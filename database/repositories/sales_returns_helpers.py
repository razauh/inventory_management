from __future__ import annotations

from typing import Dict
import sqlite3

from modules.accounting import AccountingService


def get_returnable_quantities(conn: sqlite3.Connection, sale_id: str) -> Dict[int, float]:
    """
    Compute remaining returnable quantity per sale item for a given sale.

    Returns a dict mapping item_id -> remaining_qty (float, clamped to >= 0.0).
    """
    service = AccountingService(conn)
    res = service.get_sale_returnable_quantities(sale_id)
    return {item_id: float(qty) for item_id, qty in res.items()}
