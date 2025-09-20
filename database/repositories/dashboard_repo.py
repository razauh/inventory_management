# inventory_management/database/repositories/dashboard_repo.py
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def _to_float(x: Optional[Any]) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0


class DashboardRepo:
    """
    Thin query layer for the Dashboard.

    All methods are read-only and compatible with schema.py.
    Each method returns either a float or a list[dict].

    Performance note:
    - Date columns are compared directly (e.g., col >= ? AND col <= ?) to keep
      SQLite eligible to use indexes on those columns. Ensure dates are stored
      as ISO 8601 'YYYY-MM-DD' text.
    - NO use of SQLite clock (DATE('now'), strftime(...)) inside filters; the
      caller must pass app-locale date_from/date_to for time-bound queries.

    Consistency note:
    - For both sales and purchases, we standardize on:
        paid_total := paid_amount + advance_payment_applied
      (for sales, paid_amount rolls up *all* payments; for purchases, triggers
      already clamp paid_amount to cleared-only). Open receivables/payables use
      this composition: remaining = total_amount - paid_total.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        # Ensure we can access columns by name in a safe, schema-friendly way.
        self.conn.row_factory = sqlite3.Row

    # ----------------------------- Sales & P&L -----------------------------

    def total_sales(self, date_from: str, date_to: str) -> float:
        sql = """
            SELECT COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS v
            FROM sales s
            WHERE s.doc_type = 'sale'
              AND s.date >= ? AND s.date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def cogs_for_sales(self, date_from: str, date_to: str) -> float:
        # sale_item_cogs already ties COGS to the sale date via its join.
        sql = """
            SELECT COALESCE(SUM(c.cogs_value), 0.0) AS v
            FROM sale_item_cogs c
            JOIN sales s ON s.sale_id = c.sale_id
            WHERE s.doc_type = 'sale'
              AND s.date >= ? AND s.date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def expenses_total(self, date_from: str, date_to: str) -> float:
        sql = """
            SELECT COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS v
            FROM expenses e
            WHERE e.date >= ? AND e.date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def gross_profit(self, date_from: str, date_to: str) -> float:
        sales = self.total_sales(date_from, date_to)
        cogs = self.cogs_for_sales(date_from, date_to)
        return sales - cogs

    def net_profit(self, date_from: str, date_to: str) -> float:
        sales = self.total_sales(date_from, date_to)
        cogs = self.cogs_for_sales(date_from, date_to)
        opex = self.expenses_total(date_from, date_to)
        return sales - cogs - opex

    # --------------------------- Cash & Bank flows -------------------------

    def receipts_cleared(self, date_from: str, date_to: str) -> float:
        """
        Incoming receipts that actually CLEARED in the window.
        Uses cleared_date and clearing_state='cleared'.
        (This is a bank-cleared metric; it intentionally excludes customer-credit applications.)
        """
        sql = """
            SELECT COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS v
            FROM sale_payments sp
            WHERE sp.clearing_state = 'cleared'
              AND sp.cleared_date >= ? AND sp.cleared_date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def vendor_payments_cleared(self, date_from: str, date_to: str) -> float:
        """
        Outgoing payments to vendors that CLEARED in the window.
        Positive amounts = outflow; negative = refunds (inflow).
        Returns the signed net (out - refunds).
        (Purchase side is already cleared-only in triggers for paid rollups.)
        """
        sql = """
            SELECT COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS v
            FROM purchase_payments pp
            WHERE pp.clearing_state = 'cleared'
              AND pp.cleared_date >= ? AND pp.cleared_date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def bank_movements_by_account(
        self, date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """
        Sums in/out by company bank account using v_bank_ledger_ext.
        Note: Cash payments have bank_account_id NULL and are excluded.
        """
        sql = """
            SELECT
              a.account_id,
              a.label,
              COALESCE(SUM(CAST(v.amount_in  AS REAL)), 0.0) AS amount_in,
              COALESCE(SUM(CAST(v.amount_out AS REAL)), 0.0) AS amount_out
            FROM v_bank_ledger_ext v
            JOIN company_bank_accounts a
              ON a.account_id = v.bank_account_id
            WHERE v.date >= ? AND v.date <= ?
            GROUP BY a.account_id, a.label
            ORDER BY a.label COLLATE NOCASE
        """
        rows = self._rows(sql, (date_from, date_to))
        out: List[Dict[str, Any]] = []
        for r in rows:
            ai = _to_float(r["amount_in"])
            ao = _to_float(r["amount_out"])
            out.append(
                {
                    "account_id": r["account_id"],
                    "label": r["label"],
                    "amount_in": ai,
                    "amount_out": ao,
                    "net": ai - ao,
                }
            )
        return out

    # ----------------------------- AR / AP & health ------------------------

    def open_receivables(self) -> float:
        """
        Remaining = total_amount - (paid_amount + advance_payment_applied).
        Only real sales (doc_type = 'sale'); only positive remaining.
        """
        sql = """
            SELECT COALESCE(SUM(remaining), 0.0) AS v
            FROM (
              SELECT
                CAST(s.total_amount AS REAL)
                - (
                    COALESCE(CAST(s.paid_amount AS REAL), 0.0)
                    + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)
                  )
                AS remaining
              FROM sales s
              WHERE s.doc_type = 'sale'
            )
            WHERE remaining > 0.0000001
        """
        return _to_float(self._scalar(sql))

    def open_payables(self) -> float:
        """
        Remaining for purchases = total_amount - (paid_amount + advance_payment_applied).
        Only positive remaining.
        (For purchases, paid_amount is already a cleared-only rollup via triggers.)
        """
        sql = """
            SELECT COALESCE(SUM(remaining), 0.0) AS v
            FROM (
              SELECT
                CAST(p.total_amount AS REAL)
                - (
                    COALESCE(CAST(p.paid_amount AS REAL), 0.0)
                    + COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
                  )
                AS remaining
              FROM purchases p
            )
            WHERE remaining > 0.0000001
        """
        return _to_float(self._scalar(sql))

    def low_stock_count(self) -> int:
        """
        Products with on-hand < min_stock_level.
        v_stock_on_hand may not have a row; treat missing qty as 0.
        """
        sql = """
            SELECT COUNT(*) AS c
            FROM products p
            LEFT JOIN v_stock_on_hand v ON v.product_id = p.product_id
            WHERE COALESCE(CAST(v.qty_in_base AS REAL), 0.0) < CAST(p.min_stock_level AS REAL)
        """
        val = self._scalar(sql)  # alias 'c' – handled by _scalar's fallback
        try:
            return int(val or 0)
        except Exception:
            return 0

    def low_stock_rows(self, limit_n: int = 20) -> List[Dict[str, Any]]:
        sql = """
            SELECT
              p.product_id,
              p.name,
              COALESCE(CAST(v.qty_in_base AS REAL), 0.0) AS qty_in_base,
              CAST(p.min_stock_level AS REAL)           AS min_stock_level
            FROM products p
            LEFT JOIN v_stock_on_hand v ON v.product_id = p.product_id
            WHERE COALESCE(CAST(v.qty_in_base AS REAL), 0.0) < CAST(p.min_stock_level AS REAL)
            ORDER BY (CAST(p.min_stock_level AS REAL) - COALESCE(CAST(v.qty_in_base AS REAL), 0.0)) DESC,
                     p.name COLLATE NOCASE
            LIMIT ?
        """
        rows = self._rows(sql, (int(limit_n),))
        return [
            {
                "product_id": r["product_id"],
                "name": r["name"],
                "qty_in_base": _to_float(r["qty_in_base"]),
                "min_stock_level": _to_float(r["min_stock_level"]),
            }
            for r in rows
        ]

    # --------------------------- Leaderboards / lists -----------------------

    def top_products(
        self, date_from: str, date_to: str, limit_n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Top products by revenue within date range (sales only).
        qty_base computed via product_uoms factor_to_base (same logic as sale_item_cogs).
        revenue = quantity * (unit_price - item_discount).
        """
        sql = """
            SELECT
              p.name AS product_name,
              /* convert sold qty to base */
              COALESCE(SUM(
                CAST(si.quantity AS REAL) *
                COALESCE((
                  SELECT CAST(pu.factor_to_base AS REAL)
                  FROM product_uoms pu
                  WHERE pu.product_id = si.product_id
                    AND pu.uom_id     = si.uom_id
                  LIMIT 1
                ), 1.0)
              ), 0.0) AS qty_base,
              /* revenue before order-level discount (consistent with sale_detailed_totals' subtotal) */
              COALESCE(SUM(
                CAST(si.quantity AS REAL) *
                (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL))
              ), 0.0) AS revenue
            FROM sale_items si
            JOIN sales s    ON s.sale_id = si.sale_id AND s.doc_type = 'sale'
            JOIN products p ON p.product_id = si.product_id
            WHERE s.date >= ? AND s.date <= ?
            GROUP BY p.name
            ORDER BY revenue DESC, qty_base DESC, p.name COLLATE NOCASE
            LIMIT ?
        """
        rows = self._rows(sql, (date_from, date_to, int(limit_n)))
        return [
            {
                "product_name": r["product_name"],
                "qty_base": _to_float(r["qty_base"]),
                "revenue": _to_float(r["revenue"]),
            }
            for r in rows
        ]

    def top_customers(
        self, date_from: str, date_to: str, limit_n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Top customers by revenue over an explicit date range (app-locale provided).
        Replace any prior MTD variant that used the DB clock.
        """
        sql = """
            SELECT
              c.name AS customer_name,
              COUNT(*) AS order_count,
              COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS revenue
            FROM sales s
            JOIN customers c ON c.customer_id = s.customer_id
            WHERE s.doc_type = 'sale'
              AND s.date >= ? AND s.date <= ?
            GROUP BY c.name
            ORDER BY revenue DESC, order_count DESC, c.name COLLATE NOCASE
            LIMIT ?
        """
        rows = self._rows(sql, (date_from, date_to, int(limit_n)))
        return [
            {
                "customer_name": r["customer_name"],
                "order_count": int(r["order_count"] or 0),
                "revenue": _to_float(r["revenue"]),
            }
            for r in rows
        ]

    def quotations_expiring(self, date_from: str, date_to: str) -> List[Dict[str, Any]]:
        """
        Quotations whose expiry_date is within [date_from, date_to] (inclusive).
        Caller must pass app-locale bounds (e.g., today → today+N).
        """
        sql = """
            SELECT
              s.sale_id,
              c.name AS customer_name,
              s.expiry_date,
              CAST(s.total_amount AS REAL) AS amount
            FROM sales s
            JOIN customers c ON c.customer_id = s.customer_id
            WHERE s.doc_type = 'quotation'
              AND s.expiry_date IS NOT NULL
              AND s.expiry_date >= ? AND s.expiry_date <= ?
            ORDER BY s.expiry_date ASC, s.sale_id
            LIMIT 50
        """
        rows = self._rows(sql, (date_from, date_to))
        return [
            {
                "sale_id": r["sale_id"],
                "customer_name": r["customer_name"],
                "expiry_date": r["expiry_date"],
                "amount": _to_float(r["amount"]),
            }
            for r in rows
        ]

    # ---------------------- Payment pipeline breakdowns --------------------

    def sales_payments_breakdown(
        self, date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """
        Sum sales payments by method and clearing_state over posting date range.
        (Use cleared_date only for 'cleared totals' KPI; this is a pipeline view.)
        Note: This is *payments only*; customer-credit applications are reflected
        in 'paid_total' via advance_payment_applied, not in this breakdown table.
        """
        sql = """
            SELECT
              sp.method,
              sp.clearing_state,
              COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS amount
            FROM sale_payments sp
            WHERE sp.date >= ? AND sp.date <= ?
            GROUP BY sp.method, sp.clearing_state
            ORDER BY sp.method, sp.clearing_state
        """
        rows = self._rows(sql, (date_from, date_to))
        return [
            {
                "method": r["method"],
                "clearing_state": r["clearing_state"],
                "amount": _to_float(r["amount"]),
            }
            for r in rows
        ]

    def purchase_payments_breakdown(
        self, date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """
        Sum purchase payments by method and clearing_state over posting date range.
        Positive amounts are outflows; negatives are refunds/inflows.
        """
        sql = """
            SELECT
              pp.method,
              pp.clearing_state,
              COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS amount
            FROM purchase_payments pp
            WHERE pp.date >= ? AND pp.date <= ?
            GROUP BY pp.method, pp.clearing_state
            ORDER BY pp.method, pp.clearing_state
        """
        rows = self._rows(sql, (date_from, date_to))
        return [
            {
                "method": r["method"],
                "clearing_state": r["clearing_state"],
                "amount": _to_float(r["amount"]),
            }
            for r in rows
        ]

    # --------------------------- Paid-total helpers -------------------------

    def sales_paid_total(self, date_from: str, date_to: str) -> float:
        """
        Sum of (paid_amount + advance_payment_applied) for sales whose *invoice date*
        is within [date_from, date_to]. This treats 'paid total' by sale header date.
        """
        sql = """
            SELECT COALESCE(SUM(
                COALESCE(CAST(s.paid_amount AS REAL), 0.0)
              + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)
            ), 0.0) AS v
            FROM sales s
            WHERE s.doc_type = 'sale'
              AND s.date >= ? AND s.date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    def purchases_paid_total(self, date_from: str, date_to: str) -> float:
        """
        Sum of (paid_amount + advance_payment_applied) for purchases whose *header date*
        is within [date_from, date_to]. Note: paid_amount on purchases is cleared-only.
        """
        sql = """
            SELECT COALESCE(SUM(
                COALESCE(CAST(p.paid_amount AS REAL), 0.0)
              + COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
            ), 0.0) AS v
            FROM purchases p
            WHERE p.date >= ? AND p.date <= ?
        """
        return _to_float(self._scalar(sql, (date_from, date_to)))

    # ------------------------------- Helpers --------------------------------

    def _scalar(
        self,
        sql: str,
        params: Tuple[Any, ...] | List[Any] | None = None,
        *,
        alias: str = "v",
    ) -> Any:
        """
        Execute a scalar query. Prefer returning by named alias (default 'v').
        Falls back to the single column or index 0 for robustness.
        """
        cur = self.conn.execute(sql, params or [])
        row = cur.fetchone()
        if row is None:
            return None
        try:
            if isinstance(row, sqlite3.Row):
                keys = row.keys()
                if alias in keys:
                    return row[alias]
                if len(keys) == 1:
                    return row[keys[0]]
                return row[0]  # fallback
            # tuple or sequence
            return row[0]
        except Exception:
            # very defensive fallback paths
            try:
                return row[alias]
            except Exception:
                try:
                    return row[0]
                except Exception:
                    return None

    def _rows(self, sql: str, params: Tuple[Any, ...] | List[Any] | None = None) -> List[sqlite3.Row]:
        cur = self.conn.execute(sql, params or [])
        return cur.fetchall()
