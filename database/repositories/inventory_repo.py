import sqlite3
from ..schema import init_schema  # not used here, but handy

class InventoryRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def stock_on_hand(self, product_id: int) -> dict | None:
        return self.conn.execute(
            "SELECT product_id, qty_in_base, unit_value, total_value, valuation_date FROM v_stock_on_hand WHERE product_id=?",
            (product_id,)
        ).fetchone()

    def add_adjustment(self, *, product_id: int, uom_id: int, quantity: float, date: str, notes: str | None, created_by: int | None):
        self.conn.execute("""
            INSERT INTO inventory_transactions(
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id, date, notes, created_by
            ) VALUES (?, ?, ?, 'adjustment', NULL, NULL, NULL, ?, ?, ?)
        """, (product_id, float(quantity), uom_id, date, notes, created_by))
        self.conn.commit()

    def recent_transactions(self, limit: int = 50) -> list[dict]:
        return self.conn.execute("""
            SELECT it.transaction_id, it.date, it.transaction_type, p.name AS product,
                   it.quantity, u.unit_name, it.notes
            FROM inventory_transactions it
            JOIN products p ON p.product_id = it.product_id
            JOIN uoms u ON u.uom_id = it.uom_id
            ORDER BY it.transaction_id DESC
            LIMIT ?
        """, (limit,)).fetchall()