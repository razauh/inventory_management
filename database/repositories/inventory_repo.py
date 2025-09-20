from __future__ import annotations

"""
Repository for inventory queries (transactions, stock-on-hand, adjustments).

This module intentionally avoids schema changes and only issues SELECT/INSERT
queries against the existing tables/views. It is designed to be consumed by the
Inventory UI (Adjustments & Recent, Transactions tab, Stock Valuation tab).

Conventions:
- All list-returning methods yield `list[dict]` (sqlite3.Row -> dict).
- Date strings are ISO 'YYYY-MM-DD'.
- Amounts/qty are cast to float in Python for consistent UI display.
"""

import sqlite3
from typing import Optional, List, Dict


class DomainError(Exception):
    """Domain-level error suitable for surfacing to the UI."""
    pass


class InventoryRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # Make sure rows are accessible as dicts
        try:
            self.conn.row_factory = sqlite3.Row
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Small helper for UI product selectors
    # ------------------------------------------------------------------
    def list_products_for_select(self) -> list[tuple[int, str]]:
        """
        Return [(product_id, name), ...] ordered by name for populating combos.
        """
        rows = self.conn.execute(
            "SELECT product_id, name FROM products ORDER BY name"
        ).fetchall()
        return [(int(r["product_id"]), r["name"]) for r in rows]

    # ------------------------------------------------------------------
    # Existing: recent transactions (used by "Adjustments & Recent" tab)
    # ------------------------------------------------------------------
    def recent_transactions(self, limit: int = 50) -> List[Dict]:
        """
        Return most recent inventory transactions limited by `limit`.
        Aliases match TransactionsTableModel headers:
           ID | Date | Type | Product | Qty | UoM | Notes
        Ordered by DATE(date) DESC, transaction_id DESC.

        IMPORTANT: Column aliases are chosen to match the *model*:
          transaction_id, date, transaction_type, product, quantity, unit_name, notes
        """
        lim = self._normalize_limit(limit)
        sql = """
            SELECT
                t.transaction_id              AS transaction_id,
                t.date                         AS date,
                t.transaction_type             AS transaction_type,
                p.name                         AS product,
                CAST(t.quantity AS REAL)       AS quantity,
                u.unit_name                    AS unit_name,
                COALESCE(t.notes, '')          AS notes
            FROM inventory_transactions t
            LEFT JOIN products p ON p.product_id = t.product_id
            LEFT JOIN uoms     u ON u.uom_id     = t.uom_id
            ORDER BY DATE(t.date) DESC, t.transaction_id DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, (lim,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # NEW: filtered transactions for the Transactions tab
    # ------------------------------------------------------------------
    def find_transactions(
        self,
        *,
        date_from: Optional[str] = None,   # inclusive 'YYYY-MM-DD'
        date_to: Optional[str] = None,     # inclusive 'YYYY-MM-DD'
        product_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Find transactions by optional date range and/or product id with a limit.
        Aliases match TransactionsTableModel headers:
           ID | Date | Type | Product | Qty | UoM | Notes

        Ordering: DATE(t.date) DESC, t.transaction_id DESC
        Only applies WHERE fragments when corresponding filters are provided.

        IMPORTANT: Column aliases are chosen to match the *model*:
          transaction_id, date, transaction_type, product, quantity, unit_name, notes
        """
        lim = self._normalize_limit(limit)

        where: List[str] = []
        params: List = []

        if date_from:
            where.append("DATE(t.date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            where.append("DATE(t.date) <= DATE(?)")
            params.append(date_to)
        if product_id is not None:
            where.append("t.product_id = ?")
            params.append(int(product_id))

        sql = """
            SELECT
                t.transaction_id              AS transaction_id,
                t.date                         AS date,
                t.transaction_type             AS transaction_type,
                p.name                         AS product,
                CAST(t.quantity AS REAL)       AS quantity,
                u.unit_name                    AS unit_name,
                COALESCE(t.notes, '')          AS notes
            FROM inventory_transactions t
            LEFT JOIN products p ON p.product_id = t.product_id
            LEFT JOIN uoms     u ON u.uom_id     = t.uom_id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += """
            ORDER BY DATE(t.date) DESC, t.transaction_id DESC
            LIMIT ?
        """
        params.append(lim)

        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Existing: stock on hand snapshot for Stock Valuation tab
    # ------------------------------------------------------------------
    def stock_on_hand(self, product_id: int) -> Dict | None:
        """
        Return a snapshot for a single product from v_stock_on_hand.

        Expected (ideal) view columns:
          product_id, product_name, uom_name, on_hand_qty, unit_value, total_value

        If `unit_value` or `total_value` are missing from the view, this method
        fills what it can and computes total_value = on_hand_qty * unit_value
        when both pieces are available. Returns None if the product isn't found.

        NOTE: This method is read-only and does not update any costing.
        """
        row = self.conn.execute(
            """
            SELECT
                v.product_id                 AS product_id,
                v.product_name               AS product_name,
                v.uom_name                   AS uom_name,
                CAST(v.on_hand_qty AS REAL)  AS on_hand_qty,
                /* unit_value/total_value may or may not exist depending on the view */
                v.unit_value                 AS unit_value,
                v.total_value                AS total_value
            FROM v_stock_on_hand v
            WHERE v.product_id = ?
            """,
            (int(product_id),),
        ).fetchone()

        if not row:
            return None

        d = self._row_to_dict(row)

        # Normalize numeric fields and compute if missing
        on_hand = self._to_float(d.get("on_hand_qty"))
        unit_val = self._to_float(d.get("unit_value"))
        total_val = self._to_float(d.get("total_value"))

        if total_val is None and on_hand is not None and unit_val is not None:
            total_val = on_hand * unit_val

        d["on_hand_qty"] = on_hand if on_hand is not None else 0.0
        d["unit_value"] = unit_val  # can be None if the view doesn't provide it
        d["total_value"] = total_val if total_val is not None else (
            (on_hand * unit_val) if (on_hand is not None and unit_val is not None) else None
        )
        return d

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------
    def add_adjustment(
        self,
        *,
        product_id: int,
        uom_id: int,
        quantity: float,
        date: str,
        notes: str | None = None,
        created_by: int | None = None,
    ) -> int:
        """
        Insert an 'adjustment' row into inventory_transactions.

        Matches real table columns (from PRAGMA table_info):
          transaction_id, product_id, quantity, uom_id, transaction_type,
          reference_table, reference_id, reference_item_id,
          date, posted_at, txn_seq, notes, created_by
        """
        # Pre-validate product↔UoM mapping to prevent silent stock corruption.
        # (The schema triggers will also guard this, but we fail early with a clear message.)
        exists = self.conn.execute(
            "SELECT 1 FROM product_uoms WHERE product_id=? AND uom_id=? LIMIT 1",
            (int(product_id), int(uom_id)),
        ).fetchone()
        if not exists:
            raise DomainError(
                "Selected unit of measure does not belong to the chosen product. "
                "Please pick a valid UoM for this product."
            )

        cur = self.conn.execute(
            """
            INSERT INTO inventory_transactions
                (product_id, quantity, uom_id, transaction_type,
                 reference_table, reference_id, reference_item_id,
                 date, notes, created_by)
            VALUES
                (?, ?, ?, 'adjustment',
                 NULL, NULL, NULL,
                 ?, ?, ?)
            """,
            (int(product_id), float(quantity), int(uom_id), date, notes, created_by),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_dict(r: sqlite3.Row | dict) -> Dict:
        return dict(r) if isinstance(r, sqlite3.Row) else dict(r)

    @staticmethod
    def _to_float(x) -> Optional[float]:
        if x is None:
            return None
        try:
            return float(x)
        except Exception:
            return None

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        """
        Guard the limit to a safe set (50/100/500) to match UI choices.
        Default to 100 if unrecognized.
        """
        try:
            v = int(limit)
        except Exception:
            return 100
        return v if v in (50, 100, 500) else 100
