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

from modules.accounting import AccountingService


class DomainError(Exception):
    """Domain-level error suitable for surfacing to the UI."""
    pass


def rebuild_dirty_valuations(conn: sqlite3.Connection, product_id: int | None = None) -> int:
    """Maintenance helper for write paths and manual repair jobs."""
    rows = conn.execute(
        """
        SELECT product_id, earliest_impacted
        FROM valuation_dirty
        WHERE (? IS NULL OR product_id = ?)
        ORDER BY earliest_impacted, product_id
        """,
        (product_id, product_id),
    ).fetchall()
    if not rows:
        return 0

    was_in_transaction = conn.in_transaction
    rebuilt = 0
    try:
        for dirty in rows:
            pid = int(_cell(dirty, "product_id", 0))
            earliest = _cell(dirty, "earliest_impacted", 1)
            _rebuild_product_valuation(conn, pid, earliest)
            conn.execute("DELETE FROM valuation_dirty WHERE product_id = ?", (pid,))
            rebuilt += 1
        if not was_in_transaction:
            conn.commit()
        return rebuilt
    except Exception:
        if not was_in_transaction:
            conn.rollback()
        raise


def _rebuild_product_valuation(conn: sqlite3.Connection, product_id: int, earliest: str) -> None:
    prior = conn.execute(
        """
        SELECT quantity, unit_value
        FROM stock_valuation_history
        WHERE product_id = ?
          AND DATE(valuation_date) < DATE(?)
        ORDER BY DATE(valuation_date) DESC, valuation_id DESC
        LIMIT 1
        """,
        (product_id, earliest),
    ).fetchone()
    quantity = float(_cell(prior, "quantity", 0)) if prior else 0.0
    unit_value = float(_cell(prior, "unit_value", 1)) if prior else 0.0

    conn.execute(
        """
        DELETE FROM stock_valuation_history
        WHERE product_id = ?
          AND DATE(valuation_date) >= DATE(?)
        """,
        (product_id, earliest),
    )

    txns = conn.execute(
        """
        SELECT
          it.transaction_id,
          it.date,
          it.transaction_type,
          CAST(it.quantity AS REAL) AS quantity,
          COALESCE(CAST(pu.factor_to_base AS REAL), 1.0) AS factor_to_base,
          CASE
            WHEN it.transaction_type = 'purchase' THEN
              COALESCE(
                (CAST(pi.purchase_price AS REAL) - COALESCE(CAST(pi.item_discount AS REAL), 0.0))
                / COALESCE(CAST(pi_uom.factor_to_base AS REAL), 1.0),
                0.0
              )
            ELSE NULL
          END AS purchase_unit_value,
          CASE
            WHEN it.transaction_type = 'sale_return' THEN
              COALESCE(CAST(srs.unit_cost_base AS REAL), 0.0)
            ELSE NULL
          END AS sale_return_unit_value
        FROM inventory_transactions it
        LEFT JOIN product_uoms pu
          ON pu.product_id = it.product_id
         AND pu.uom_id = it.uom_id
        LEFT JOIN purchase_items pi
          ON pi.item_id = it.reference_item_id
        LEFT JOIN product_uoms pi_uom
          ON pi_uom.product_id = pi.product_id
         AND pi_uom.uom_id = pi.uom_id
        LEFT JOIN sale_return_snapshots srs
          ON srs.transaction_id = it.transaction_id
        WHERE it.product_id = ?
          AND DATE(it.date) >= DATE(?)
        ORDER BY DATE(it.date), it.txn_seq, it.posted_at, it.transaction_id
        """,
        (product_id, earliest),
    ).fetchall()

    for txn in txns:
        txn_type = _cell(txn, "transaction_type", 2)
        movement = float(_cell(txn, "quantity", 3) or 0.0) * float(_cell(txn, "factor_to_base", 4) or 1.0)
        next_quantity = quantity
        next_unit_value = unit_value

        if txn_type in ("purchase", "sale_return", "adjustment"):
            next_quantity = quantity + movement
            if txn_type == "purchase":
                purchase_unit = _cell(txn, "purchase_unit_value", 5)
                purchase_unit_value = float(purchase_unit or 0.0)
                if next_quantity > 0:
                    next_unit_value = ((quantity * unit_value) + (movement * purchase_unit_value)) / next_quantity
                else:
                    next_unit_value = purchase_unit_value if purchase_unit is not None else unit_value
            elif txn_type == "sale_return":
                return_unit = _cell(txn, "sale_return_unit_value", 6)
                return_unit_value = float(return_unit or 0.0)
                if next_quantity > 0:
                    next_unit_value = ((quantity * unit_value) + (movement * return_unit_value)) / next_quantity
                else:
                    next_unit_value = return_unit_value if return_unit is not None else unit_value
            next_total_value = next_quantity * next_unit_value if next_quantity > 0 else 0.0
        elif txn_type in ("sale", "purchase_return"):
            next_quantity = quantity - movement
            next_total_value = next_quantity * next_unit_value
        else:
            next_total_value = next_quantity * next_unit_value

        conn.execute(
            """
            INSERT INTO stock_valuation_history
              (product_id, valuation_date, quantity, unit_value, total_value, valuation_method)
            VALUES (?, ?, ?, ?, ?, 'moving_average')
            """,
            (product_id, _cell(txn, "date", 1), next_quantity, next_unit_value, next_total_value),
        )
        quantity = next_quantity
        unit_value = next_unit_value


def _cell(row, key: str, index: int):
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def next_inventory_txn_seq(conn: sqlite3.Connection, date: str, *, minimum: int = 0) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
        (date,),
    ).fetchone()
    max_seq = int(_cell(row, "max_seq", 0) or 0) if row else 0
    next_seq = max_seq + 10
    return max(next_seq, minimum)


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
        Ordered by t.date DESC, transaction_id DESC.

        IMPORTANT: Column aliases are chosen to match the *model*:
          transaction_id, date, transaction_type, product, quantity, unit_name, notes
        """
        return self.find_transactions(limit=limit)

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

        Ordering: t.date DESC, t.transaction_id DESC
        Only applies WHERE fragments when corresponding filters are provided.

        IMPORTANT: Column aliases are chosen to match the *model*:
          transaction_id, date, transaction_type, product, quantity, unit_name, notes
        """
        lim = self._normalize_limit(limit)
        product_names = {
            int(row["product_id"]): row["name"]
            for row in self.conn.execute("SELECT product_id, name FROM products")
        }
        uom_names = {
            int(row["uom_id"]): row["unit_name"]
            for row in self.conn.execute("SELECT uom_id, unit_name FROM uoms")
        }
        rows = []
        for event in AccountingService(self.conn).get_inventory_accounting_events(
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
        ):
            rows.append(
                {
                    "transaction_id": event.transaction_id,
                    "date": event.date,
                    "transaction_type": event.transaction_type,
                    "product": product_names.get(event.product_id, ""),
                    "quantity": float(event.quantity),
                    "unit_name": uom_names.get(event.uom_id, ""),
                    "notes": event.notes or "",
                }
            )
        rows.sort(
            key=lambda row: (row["date"] or "", int(row["transaction_id"] or 0)),
            reverse=True,
        )
        return rows[:lim]

    # ------------------------------------------------------------------
    # Existing: stock on hand snapshot for Stock Valuation tab
    # ------------------------------------------------------------------
    def stock_on_hand(self, product_id: int) -> Dict | None:
        """
        Return a read-only snapshot for a single product from v_stock_on_hand.

        Expected (ideal) view columns:
          product_id, product_name, uom_name, on_hand_qty, unit_value, total_value

        If `unit_value` or `total_value` are missing from the view, this method
        fills what it can and computes total_value = on_hand_qty * unit_value
        when both pieces are available. Returns None if the product isn't found.
        """
        # NOTE: We rely on the schema-level UNIQUE index
        # `idx_product_uoms_one_base` (product_id WHERE is_base = 1) to ensure
        # there is at most one base UoM row per product.
        row = self.conn.execute(
            """
            SELECT
                v.product_id                               AS product_id,
                COALESCE(p.name, '')                       AS product_name,
                COALESCE(u.unit_name, '')                  AS uom_name,
                CAST(v.qty_in_base AS REAL)                AS on_hand_qty,
                v.unit_value                               AS unit_value,
                v.total_value                              AS total_value
            FROM v_stock_on_hand v
            LEFT JOIN products p
                   ON p.product_id = v.product_id
            LEFT JOIN product_uoms pu
                   ON pu.product_id = v.product_id
                  AND pu.is_base = 1
            LEFT JOIN uoms u
                   ON u.uom_id = pu.uom_id
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

    def low_inventory_products(self) -> List[Dict]:
        rebuild_dirty_valuations(self.conn)
        rows = self.conn.execute(
            """
            SELECT
                p.product_id AS product_id,
                p.name AS product,
                COALESCE(CAST(v.qty_in_base AS REAL), 0.0) AS available_qty,
                CAST(p.min_stock_level AS REAL) AS min_stock_level,
                COALESCE(u.unit_name, '') AS unit_name
            FROM products p
            LEFT JOIN v_stock_on_hand v ON v.product_id = p.product_id
            LEFT JOIN product_uoms pu
                   ON pu.product_id = p.product_id
                  AND pu.is_base = 1
            LEFT JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE CAST(p.min_stock_level AS REAL) > 0
              AND COALESCE(CAST(v.qty_in_base AS REAL), 0.0) < CAST(p.min_stock_level AS REAL)
            ORDER BY
                (CAST(p.min_stock_level AS REAL) - COALESCE(CAST(v.qty_in_base AS REAL), 0.0)) DESC,
                p.name COLLATE NOCASE
            """
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

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
        was_in_transaction = self.conn.in_transaction
        qty = float(quantity)

        from modules.accounting import AccountingService, StockAdjustmentPayload

        try:
            result = AccountingService(self.conn).record_stock_adjustment_event(
                StockAdjustmentPayload(
                    product_id=int(product_id),
                    uom_id=int(uom_id),
                    quantity=qty,
                    date=date,
                    notes=notes,
                    created_by=created_by,
                )
            )
        except Exception as exc:
            if exc.__class__.__name__ == "DomainError":
                raise DomainError(str(exc)) from exc
            raise
        if not was_in_transaction:
            self.conn.commit()
        return result.transaction_id

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
