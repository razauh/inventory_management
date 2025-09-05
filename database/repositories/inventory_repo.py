# database/repositories/inventory_repo.py
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence


class InventoryRepo:
    """
    Inventory data access:
      - stock_on_hand(product_id): read snapshot from v_stock_on_hand
      - add_adjustment(...): insert a manual inventory adjustment
      - recent_transactions(limit): list recent inventory transactions for the UI table

    Note:
      This repo does not compute valuation or on-hand; it relies on your DB views/triggers.
    """

    def __init__(self, conn: sqlite3.Connection):
        # Ensure rows can be accessed like dictionaries everywhere in this repo
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        self.conn = conn

    # ---------- Valuation / Snapshot ----------

    def stock_on_hand(self, product_id: int) -> Optional[sqlite3.Row]:
        """
        Returns a single row from v_stock_on_hand with columns:
          product_id, qty_in_base, unit_value, total_value, valuation_date
        or None if not found.
        """
        cur = self.conn.execute(
            """
            SELECT product_id, qty_in_base, unit_value, total_value, valuation_date
            FROM v_stock_on_hand
            WHERE product_id = ?
            """,
            (product_id,),
        )
        return cur.fetchone()

    # ---------- Adjustments ----------

    def add_adjustment(
        self,
        *,
        product_id: int,
        uom_id: int,
        quantity: float,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
    ) -> int:
        """
        Inserts a single manual adjustment into inventory_transactions.

        Parameters:
          product_id: target product id
          uom_id:     UoM id recorded with the transaction
          quantity:   positive or negative (controller enforces numeric)
          date:       'YYYY-MM-DD' (controller passes explicit value or today_str())
          notes:      optional free-text
          created_by: nullable user id for audit

        Returns:
          The new transaction_id (lastrowid).
        """
        cur = self.conn.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id,
                date, notes, created_by
            )
            VALUES (?, ?, ?, 'adjustment', NULL, NULL, NULL, ?, ?, ?)
            """,
            (product_id, float(quantity), uom_id, date, notes, created_by),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # ---------- Listings ----------

    def recent_transactions(self, limit: int = 50) -> Sequence[sqlite3.Row]:
        """
        Returns the latest transactions for the table model with columns:
          transaction_id, date, transaction_type, product, quantity, unit_name, notes
        Ordered by newest first (transaction_id DESC).
        """
        cur = self.conn.execute(
            """
            SELECT
                it.transaction_id,
                it.date,
                it.transaction_type,
                p.name AS product,
                it.quantity,
                u.unit_name,
                it.notes
            FROM inventory_transactions it
            JOIN products p ON p.product_id = it.product_id
            JOIN uoms     u ON u.uom_id     = it.uom_id
            ORDER BY it.transaction_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()
