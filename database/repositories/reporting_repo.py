# inventory_management/database/repositories/reporting_repo.py
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterable, Optional, Sequence

from modules.accounting import AccountingService


class ReportingRepo:
    """
    Queries for Reporting tabs, aligned with schema.py.

    Uses only objects your schema defines:
      - Tables: sales, sale_items, customers, products,
                sale_payments, customer_advances,
                purchases, purchase_payments, vendor_advances,
                expenses, expense_categories,
                inventory_transactions, product_uoms,
                stock_valuation_history
      - Views:  sale_detailed_totals, v_stock_on_hand, sale_item_cogs,
                sale_financial_events

    Notes on date handling:
      • All ORDER BY clauses sort directly on the date/timestamp column (no DATE() wrapper)
        to preserve index usage.
      • Callers should pass ISO 'YYYY-MM-DD' (or the same normalized format stored in the DB).
        If timestamps are ever used, ensure the cutoff value matches the stored representation
        so comparisons like `<= ?` behave as intended.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.accounting = AccountingService(conn)

    def __enter__(self):
        """Context manager entry for proper resource management."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit to ensure proper cleanup."""
        # Connection is typically managed by the caller, but we can ensure cleanup here
        pass

    @contextmanager
    def read_snapshot(self):
        """
        Run report reads against one SQLite snapshot.

        If the caller already has an open transaction, leave it alone.
        """
        started = False
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN")
            started = True
        try:
            yield self.conn
        finally:
            if started and self.conn.in_transaction:
                self.conn.execute("ROLLBACK")

    @staticmethod
    def _limit_clause(limit: Optional[int], offset: int = 0) -> tuple[str, list[object]]:
        if limit is None:
            return "", []
        if offset > 0:
            return " LIMIT ? OFFSET ? ", [int(limit), max(0, int(offset))]
        return " LIMIT ? ", [int(limit)]
    
    def close(self):
        """Explicitly close the database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    # ----------------------------------------------------------------------
    # -------------------------- AGING (AP / AR) ---------------------------
    # ----------------------------------------------------------------------

    def vendor_headers_as_of(self, vendor_id: int, as_of: str) -> list[sqlite3.Row]:
        """
        Purchase headers for remaining due calc as of a cutoff (inclusive).
        remaining = net total after returns - cleared payments - applied advances
        """
        return self._vendor_headers_as_of_rows([vendor_id], as_of)
    
    def vendor_headers_as_of_batch(self, vendor_ids: list[int], as_of: str) -> list[sqlite3.Row]:
        """
        Purchase headers for remaining due calc as of a cutoff for multiple vendors.
        This method addresses N+1 query pattern by fetching all vendor headers in a single query.
        remaining = net total after returns - cleared payments - applied advances
        """
        return self._vendor_headers_as_of_rows(vendor_ids, as_of)

    def _vendor_headers_as_of_rows(
        self, vendor_ids: Sequence[int], as_of: str
    ) -> list[sqlite3.Row]:
        if not vendor_ids:
            return []

        placeholders = ",".join("?" for _ in vendor_ids)
        sql = f"""
        WITH cutoff(as_of) AS (SELECT ?),
        selected_purchases AS (
            SELECT
                p.purchase_id,
                p.vendor_id,
                p.date,
                CAST(p.order_discount AS REAL) AS order_discount
            FROM purchases p
            WHERE p.vendor_id IN ({placeholders})
              AND p.date <= (SELECT as_of FROM cutoff)
        ),
        purchase_events AS (
            SELECT
                p.purchase_id,
                p.date AS event_date,
                MAX(
                    0.0,
                    COALESCE(
                        SUM(
                            CAST(pi.quantity AS REAL)
                            * (CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL))
                        ),
                        0.0
                    ) - COALESCE(CAST(p.order_discount AS REAL), 0.0)
                ) AS amount
            FROM purchases p
            JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
            JOIN selected_purchases sp ON sp.purchase_id = p.purchase_id
            GROUP BY p.purchase_id, p.date, p.order_discount
            UNION ALL
            SELECT
                prs.purchase_id,
                prs.return_date AS event_date,
                -CAST(prs.return_value AS REAL) AS amount
            FROM purchase_return_snapshots prs
            JOIN selected_purchases sp ON sp.purchase_id = prs.purchase_id
            WHERE prs.return_date <= (SELECT as_of FROM cutoff)
        ),
        total_amounts AS (
            SELECT
                purchase_id,
                COALESCE(SUM(amount), 0.0) AS total_amount
            FROM purchase_events
            WHERE event_date <= (SELECT as_of FROM cutoff)
            GROUP BY purchase_id
        ),
        payment_totals AS (
            SELECT
                pp.purchase_id,
                COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS paid_amount
            FROM purchase_payments pp
            JOIN selected_purchases sp ON sp.purchase_id = pp.purchase_id
            WHERE pp.clearing_state = 'cleared'
              AND pp.cleared_date IS NOT NULL
              AND pp.cleared_date <= (SELECT as_of FROM cutoff)
            GROUP BY pp.purchase_id
        ),
        credit_totals AS (
            SELECT
                va.source_id AS purchase_id,
                COALESCE(SUM(-CAST(va.amount AS REAL)), 0.0) AS advance_payment_applied
            FROM vendor_advances va
            JOIN selected_purchases sp ON sp.purchase_id = va.source_id
            WHERE va.source_type = 'applied_to_purchase'
              AND va.tx_date <= (SELECT as_of FROM cutoff)
            GROUP BY va.source_id
        )
        SELECT
            sp.vendor_id,
            sp.purchase_id AS doc_no,
            sp.date        AS date,
            MAX(0.0, COALESCE(ta.total_amount, 0.0)) AS total_amount,
            COALESCE(pt.paid_amount, 0.0) AS paid_amount,
            COALESCE(ct.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM selected_purchases sp
        LEFT JOIN total_amounts ta ON ta.purchase_id = sp.purchase_id
        LEFT JOIN payment_totals pt ON pt.purchase_id = sp.purchase_id
        LEFT JOIN credit_totals ct ON ct.purchase_id = sp.purchase_id
        ORDER BY sp.vendor_id, sp.date, sp.purchase_id
        """
        params = [as_of] + vendor_ids
        return list(self.conn.execute(sql, params))

    def vendor_credit_as_of_batch(self, vendor_ids: list[int], as_of: str) -> dict[int, float]:
        """
        Get vendor credit for multiple vendor IDs as of a specific date.
        This method addresses N+1 query pattern by fetching all vendor credits in a single query.
        """
        if not vendor_ids:
            return {}
            
        placeholders = ','.join(['?' for _ in vendor_ids])
        sql = f"""
        SELECT 
            va.vendor_id,
            COALESCE(SUM(CAST(va.amount AS REAL)), 0.0) AS credit
        FROM vendor_advances va
        WHERE va.vendor_id IN ({placeholders})
          AND va.tx_date <= ?
        GROUP BY va.vendor_id
        """
        params = vendor_ids + [as_of]
        result = {}
        for row in self.conn.execute(sql, params):
            result[int(row["vendor_id"])] = float(row["credit"])
        return result

    def vendor_credit_as_of(self, vendor_id: int, as_of: str) -> float:
        sql = """
        SELECT COALESCE(SUM(CAST(va.amount AS REAL)), 0.0) AS credit
        FROM vendor_advances va
        WHERE va.vendor_id = ?
          AND va.tx_date <= ?
        """
        row = self.conn.execute(sql, (vendor_id, as_of)).fetchone()
        return float(row["credit"] if row and row["credit"] is not None else 0.0)

    def customer_headers_as_of(self, customer_id: int, as_of: str) -> list[sqlite3.Row]:
        """
        Sales headers (doc_type='sale') for remaining due calc as of cutoff.
        """
        sql = """
        WITH cutoff(as_of) AS (SELECT ?),
        selected_sales AS (
            SELECT
                s.sale_id,
                s.customer_id,
                s.date,
                CAST(s.total_amount AS REAL) AS total_amount,
                CAST(s.order_discount AS REAL) AS order_discount,
                CAST(s.paid_amount AS REAL) AS paid_amount,
                CAST(s.advance_payment_applied AS REAL) AS advance_payment_applied
            FROM sales s
            WHERE s.customer_id = ?
              AND s.doc_type = 'sale'
              AND s.date <= (SELECT as_of FROM cutoff)
        ),
        line_totals AS (
            SELECT
                si.sale_id,
                COALESCE(
                    SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL))),
                    0.0
                ) AS subtotal
            FROM sale_items si
            JOIN selected_sales ss ON ss.sale_id = si.sale_id
            GROUP BY si.sale_id
        ),
        return_totals AS (
            SELECT
                srs.sale_id,
                COALESCE(SUM(CAST(srs.return_value AS REAL)), 0.0) AS returned_value
            FROM sale_return_snapshots srs
            JOIN selected_sales ss ON ss.sale_id = srs.sale_id
            WHERE srs.return_date <= (SELECT as_of FROM cutoff)
            GROUP BY srs.sale_id
        ),
        payment_totals AS (
            SELECT
                sp.sale_id,
                COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS paid_amount
            FROM sale_payments sp
            JOIN selected_sales ss ON ss.sale_id = sp.sale_id
            WHERE sp.clearing_state = 'cleared'
              AND sp.cleared_date IS NOT NULL
              AND sp.cleared_date <= (SELECT as_of FROM cutoff)
            GROUP BY sp.sale_id
        ),
        payment_activity AS (
            SELECT DISTINCT sp.sale_id
            FROM sale_payments sp
            WHERE sp.clearing_state = 'cleared'
              AND sp.cleared_date IS NOT NULL
        ),
        credit_totals AS (
            SELECT
                ca.source_id AS sale_id,
                COALESCE(SUM(-CAST(ca.amount AS REAL)), 0.0) AS advance_payment_applied
            FROM customer_advances ca
            JOIN selected_sales ss ON ss.sale_id = ca.source_id
            WHERE ca.source_type = 'applied_to_sale'
              AND ca.tx_date <= (SELECT as_of FROM cutoff)
            GROUP BY ca.source_id
        ),
        credit_activity AS (
            SELECT DISTINCT ca.source_id AS sale_id
            FROM customer_advances ca
            WHERE ca.source_type = 'applied_to_sale'
        )
        SELECT
            ss.sale_id     AS doc_no,
            ss.date        AS date,
            MAX(0.0, COALESCE(lt.subtotal, ss.total_amount, 0.0) - COALESCE(ss.order_discount, 0.0) - COALESCE(rt.returned_value, 0.0)) AS total_amount,
            CASE
              WHEN pa.sale_id IS NOT NULL THEN COALESCE(pt.paid_amount, 0.0)
              ELSE COALESCE(ss.paid_amount, 0.0)
            END AS paid_amount,
            CASE
              WHEN caa.sale_id IS NOT NULL THEN COALESCE(ct.advance_payment_applied, 0.0)
              ELSE COALESCE(ss.advance_payment_applied, 0.0)
            END AS advance_payment_applied
        FROM selected_sales ss
        LEFT JOIN line_totals lt ON lt.sale_id = ss.sale_id
        LEFT JOIN return_totals rt ON rt.sale_id = ss.sale_id
        LEFT JOIN payment_totals pt ON pt.sale_id = ss.sale_id
        LEFT JOIN payment_activity pa ON pa.sale_id = ss.sale_id
        LEFT JOIN credit_totals ct ON ct.sale_id = ss.sale_id
        LEFT JOIN credit_activity caa ON caa.sale_id = ss.sale_id
        ORDER BY ss.date, ss.sale_id
        """
        return list(self.conn.execute(sql, (as_of, customer_id)))
    
    def customer_headers_as_of_batch(self, customer_ids: list[int], as_of: str) -> list[sqlite3.Row]:
        """
        Sales headers (doc_type='sale') for remaining due calc as of cutoff for multiple customers.
        This method addresses N+1 query pattern by fetching all customer headers in a single query.
        """
        if not customer_ids:
            return []
        
        # Create placeholders for IN clause
        placeholders = ','.join(['?' for _ in customer_ids])
        sql = f"""
        WITH cutoff(as_of) AS (SELECT ?),
        selected_sales AS (
            SELECT
                s.sale_id,
                s.customer_id,
                s.date,
                CAST(s.total_amount AS REAL) AS total_amount,
                CAST(s.order_discount AS REAL) AS order_discount,
                CAST(s.paid_amount AS REAL) AS paid_amount,
                CAST(s.advance_payment_applied AS REAL) AS advance_payment_applied
            FROM sales s
            WHERE s.customer_id IN ({placeholders})
              AND s.doc_type = 'sale'
              AND s.date <= (SELECT as_of FROM cutoff)
        ),
        line_totals AS (
            SELECT
                si.sale_id,
                COALESCE(
                    SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL))),
                    0.0
                ) AS subtotal
            FROM sale_items si
            JOIN selected_sales ss ON ss.sale_id = si.sale_id
            GROUP BY si.sale_id
        ),
        return_totals AS (
            SELECT
                srs.sale_id,
                COALESCE(SUM(CAST(srs.return_value AS REAL)), 0.0) AS returned_value
            FROM sale_return_snapshots srs
            JOIN selected_sales ss ON ss.sale_id = srs.sale_id
            WHERE srs.return_date <= (SELECT as_of FROM cutoff)
            GROUP BY srs.sale_id
        ),
        payment_totals AS (
            SELECT
                sp.sale_id,
                COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS paid_amount
            FROM sale_payments sp
            JOIN selected_sales ss ON ss.sale_id = sp.sale_id
            WHERE sp.clearing_state = 'cleared'
              AND sp.cleared_date IS NOT NULL
              AND sp.cleared_date <= (SELECT as_of FROM cutoff)
            GROUP BY sp.sale_id
        ),
        payment_activity AS (
            SELECT DISTINCT sp.sale_id
            FROM sale_payments sp
            WHERE sp.clearing_state = 'cleared'
              AND sp.cleared_date IS NOT NULL
        ),
        credit_totals AS (
            SELECT
                ca.source_id AS sale_id,
                COALESCE(SUM(-CAST(ca.amount AS REAL)), 0.0) AS advance_payment_applied
            FROM customer_advances ca
            JOIN selected_sales ss ON ss.sale_id = ca.source_id
            WHERE ca.source_type = 'applied_to_sale'
              AND ca.tx_date <= (SELECT as_of FROM cutoff)
            GROUP BY ca.source_id
        ),
        credit_activity AS (
            SELECT DISTINCT ca.source_id AS sale_id
            FROM customer_advances ca
            WHERE ca.source_type = 'applied_to_sale'
        )
        SELECT
            ss.customer_id,
            ss.sale_id     AS doc_no,
            ss.date        AS date,
            MAX(0.0, COALESCE(lt.subtotal, ss.total_amount, 0.0) - COALESCE(ss.order_discount, 0.0) - COALESCE(rt.returned_value, 0.0)) AS total_amount,
            CASE
              WHEN pa.sale_id IS NOT NULL THEN COALESCE(pt.paid_amount, 0.0)
              ELSE COALESCE(ss.paid_amount, 0.0)
            END AS paid_amount,
            CASE
              WHEN caa.sale_id IS NOT NULL THEN COALESCE(ct.advance_payment_applied, 0.0)
              ELSE COALESCE(ss.advance_payment_applied, 0.0)
            END AS advance_payment_applied
        FROM selected_sales ss
        LEFT JOIN line_totals lt ON lt.sale_id = ss.sale_id
        LEFT JOIN return_totals rt ON rt.sale_id = ss.sale_id
        LEFT JOIN payment_totals pt ON pt.sale_id = ss.sale_id
        LEFT JOIN payment_activity pa ON pa.sale_id = ss.sale_id
        LEFT JOIN credit_totals ct ON ct.sale_id = ss.sale_id
        LEFT JOIN credit_activity caa ON caa.sale_id = ss.sale_id
        ORDER BY ss.customer_id, ss.date, ss.sale_id
        """
        params = [as_of] + customer_ids
        return list(self.conn.execute(sql, params))

    def customer_credit_as_of_batch(self, customer_ids: list[int], as_of: str) -> dict[int, float]:
        """
        Get customer credit for multiple customer IDs as of a specific date.
        This method addresses N+1 query pattern by fetching all customer credits in a single query.
        """
        if not customer_ids:
            return {}
            
        placeholders = ','.join(['?' for _ in customer_ids])
        sql = f"""
        SELECT 
            ca.customer_id,
            COALESCE(SUM(CAST(ca.amount AS REAL)), 0.0) AS credit
        FROM customer_advances ca
        WHERE ca.customer_id IN ({placeholders})
          AND ca.tx_date <= ?
        GROUP BY ca.customer_id
        """
        params = customer_ids + [as_of]
        result = {}
        for row in self.conn.execute(sql, params):
            result[int(row["customer_id"])] = float(row["credit"])
        return result

    def customer_credit_as_of(self, customer_id: int, as_of: str) -> float:
        sql = """
        SELECT COALESCE(SUM(CAST(ca.amount AS REAL)), 0.0) AS credit
        FROM customer_advances ca
        WHERE ca.customer_id = ?
          AND ca.tx_date <= ?
        """
        row = self.conn.execute(sql, (customer_id, as_of)).fetchone()
        return float(row["credit"] if row and row["credit"] is not None else 0.0)

    # ----------------------------------------------------------------------
    # ------------------------------ EXPENSES ------------------------------
    # ----------------------------------------------------------------------

    def expense_summary_by_category(
        self, date_from: str, date_to: str, category_id: Optional[int], limit: Optional[int] = 1000
    ) -> list[dict]:
        """
        Totals per category in [date_from, date_to].
        """
        from modules.accounting.service import AccountingService
        totals = AccountingService(self.conn).get_expense_report_category_totals(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )
        if limit is not None:
            totals = totals[:limit]
        return [
            {
                "category_id": t.category_id,
                "category_name": t.category_name,
                "total_amount": float(t.total_amount),
            }
            for t in totals
        ]

    def expense_summary_by_category_iter(
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> Iterable[dict]:
        """
        Generator version of expense_summary_by_category that yields rows one at a time.
        """
        from modules.accounting.service import AccountingService
        totals = AccountingService(self.conn).get_expense_report_category_totals(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )
        for t in totals:
            yield {
                "category_id": t.category_id,
                "category_name": t.category_name,
                "total_amount": float(t.total_amount),
            }

    def expense_lines(
        self, date_from: str, date_to: str, category_id: Optional[int], limit: Optional[int] = 1000
    ) -> list[dict]:
        """
        Raw expense lines for the period and optional category.
        """
        from modules.accounting.service import AccountingService
        lines = AccountingService(self.conn).get_expense_report_lines(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )
        if limit is not None:
            lines = lines[:limit]
        return [
            {
                "expense_id": l.expense_id,
                "date": l.date,
                "category_name": l.category_name,
                "description": l.description,
                "amount": float(l.amount),
            }
            for l in lines
        ]

    def expense_lines_iter(
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> Iterable[dict]:
        """
        Generator version of expense_lines that yields rows one at a time.
        This prevents loading all results into memory at once for large datasets.
        """
        from modules.accounting.service import AccountingService
        lines = AccountingService(self.conn).get_expense_report_lines(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )
        for l in lines:
            yield {
                "expense_id": l.expense_id,
                "date": l.date,
                "category_name": l.category_name,
                "description": l.description,
                "amount": float(l.amount),
            }

    # ----------------------------------------------------------------------
    # ------------------------------ INVENTORY -----------------------------
    # ----------------------------------------------------------------------

    def stock_on_hand_current(self, limit: Optional[int] = 1000) -> list[sqlite3.Row]:
        """
        Read-only current snapshot from v_stock_on_hand.
        View columns (per schema): product_id, qty_in_base, unit_value, total_value, valuation_date
        We also join products to provide product_name and alias qty_in_base -> qty_base
        to match the UI layer.
        """
        sql = """
        SELECT
          v.product_id,
          p.name AS product_name,
          v.qty_in_base AS qty_base,
          v.unit_value,
          v.total_value,
          v.valuation_date
        FROM v_stock_on_hand v
        LEFT JOIN products p ON p.product_id = v.product_id
        ORDER BY p.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        return list(self.conn.execute(sql, lim_params))

    def stock_on_hand_current_iter(self, limit: Optional[int] = None) -> Iterable[sqlite3.Row]:
        """
        Read-only generator version of stock_on_hand_current.
        This prevents loading all results into memory at once for large datasets.
        """
        sql = """
        SELECT
          v.product_id,
          p.name AS product_name,
          v.qty_in_base AS qty_base,
          v.unit_value,
          v.total_value,
          v.valuation_date
        FROM v_stock_on_hand v
        LEFT JOIN products p ON p.product_id = v.product_id
        ORDER BY p.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        cursor = self.conn.execute(sql, lim_params)
        for row in cursor:
            yield row

    def stock_on_hand_as_of(self, as_of: str, limit: Optional[int] = 1000) -> list[sqlite3.Row]:
        """
        Read-only latest valuation row per product where valuation_date <= as_of.
        stock_valuation_history columns: product_id, valuation_date, quantity, unit_value, total_value
        """
        sql = """
        WITH latest AS (
          SELECT svh.product_id,
                 MAX(svh.valuation_id) AS last_vid
          FROM stock_valuation_history svh
          WHERE svh.valuation_date <= ?
          GROUP BY svh.product_id
        )
        SELECT
          svh.product_id,
          p.name AS product_name,
          svh.quantity     AS qty_base,
          svh.unit_value   AS unit_value,
          svh.total_value  AS total_value,
          svh.valuation_date
        FROM latest l
        JOIN stock_valuation_history svh ON svh.valuation_id = l.last_vid
        LEFT JOIN products p ON p.product_id = svh.product_id
        ORDER BY p.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        return list(self.conn.execute(sql, [as_of, *lim_params]))

    def stock_on_hand_as_of_iter(self, as_of: str, limit: Optional[int] = None) -> Iterable[sqlite3.Row]:
        """
        Read-only generator version of stock_on_hand_as_of.
        This prevents loading all results into memory at once for large datasets.
        """
        sql = """
        WITH latest AS (
          SELECT svh.product_id,
                 MAX(svh.valuation_id) AS last_vid
          FROM stock_valuation_history svh
          WHERE svh.valuation_date <= ?
          GROUP BY svh.product_id
        )
        SELECT
          svh.product_id,
          p.name AS product_name,
          svh.quantity     AS qty_base,
          svh.unit_value   AS unit_value,
          svh.total_value  AS total_value,
          svh.valuation_date
        FROM latest l
        JOIN stock_valuation_history svh ON svh.valuation_id = l.last_vid
        LEFT JOIN products p ON p.product_id = svh.product_id
        ORDER BY p.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        cursor = self.conn.execute(sql, [as_of, *lim_params])
        for row in cursor:
            yield row

    def inventory_transactions(self, date_from: str, date_to: str, product_id: int | None, limit: Optional[int] = 1000) -> list[sqlite3.Row]:
        """
        Return transactions with both posted qty/UoM and base-qty conversion.
        Columns returned (UI expects): date, product_id, type, quantity, unit_name,
        qty_base, ref_table, ref_id, notes
        """
        return list(
            self.inventory_transactions_iter(
                date_from,
                date_to,
                product_id,
                limit=limit,
            )
        )

    def inventory_transactions_iter(self, date_from: str, date_to: str, product_id: int | None, limit: Optional[int] = None) -> Iterable[sqlite3.Row]:
        """
        Generator version of inventory_transactions that yields rows one at a time.
        This prevents loading all results into memory at once for large datasets.
        """
        product_uom_factors = {
            (int(row["product_id"]), int(row["uom_id"])): float(row["factor_to_base"] or 1.0)
            for row in self.conn.execute(
                "SELECT product_id, uom_id, factor_to_base FROM product_uoms"
            )
        }
        uom_names = {
            int(row["uom_id"]): row["unit_name"]
            for row in self.conn.execute("SELECT uom_id, unit_name FROM uoms")
        }
        count = 0
        for event in self.accounting.get_inventory_accounting_events(
            date_from=date_from,
            date_to=date_to,
            product_id=product_id if isinstance(product_id, int) else None,
        ):
            quantity = float(event.quantity)
            factor = product_uom_factors.get(
                (event.product_id, int(event.uom_id or 0)),
                1.0,
            )
            yield {
                "date": event.date,
                "product_id": event.product_id,
                "type": event.transaction_type,
                "quantity": quantity,
                "unit_name": uom_names.get(event.uom_id, ""),
                "qty_base": quantity * factor,
                "ref_table": event.source_type,
                "ref_id": event.source_id,
                "notes": event.notes,
            }
            count += 1
            if limit is not None and count >= int(limit):
                return

    def valuation_history(self, product_id: int, limit: int) -> list[sqlite3.Row]:
        """
        Read-only latest N valuation rows for a product.
        """
        sql = """
        SELECT
          svh.product_id,
          svh.valuation_date AS date,
          svh.quantity       AS qty_base,
          svh.unit_value     AS unit_value,
          svh.total_value    AS total_value
        FROM stock_valuation_history svh
        WHERE svh.product_id = ?
        ORDER BY svh.valuation_date DESC, svh.valuation_id DESC
        LIMIT ?
        """
        return list(self.conn.execute(sql, (product_id, limit)))

    # ----------------------------------------------------------------------
    # ------------------------------ FINANCIALS ----------------------------
    # ----------------------------------------------------------------------

    def revenue_total(self, date_from: str, date_to: str) -> float:
        """Net revenue from sale and return events in the period."""
        sql = """
        SELECT COALESCE(SUM(CAST(revenue AS REAL)), 0.0) AS rev
        FROM sale_financial_events
        WHERE event_date >= ? AND event_date <= ?
        """
        row = self.conn.execute(sql, (date_from, date_to)).fetchone()
        return float(row["rev"] if row and row["rev"] is not None else 0.0)

    def cogs_total(self, date_from: str, date_to: str) -> float:
        """Net COGS after return reversals in the period."""
        sql = """
        SELECT COALESCE(SUM(CAST(cogs AS REAL)), 0.0) AS cogs
        FROM sale_financial_events
        WHERE event_date >= ? AND event_date <= ?
        """
        row = self.conn.execute(sql, (date_from, date_to)).fetchone()
        return float(row["cogs"] if row and row["cogs"] is not None else 0.0)

    def expenses_by_category(
        self, date_from: str, date_to: str, limit: Optional[int] = 1000
    ) -> list[dict]:
        """
        Detailed expense totals by category for P&L middle block.
        Returns category_id, category_name, total_amount (names match UI).
        """
        from modules.accounting.service import AccountingService
        summary = AccountingService(self.conn).get_profit_loss_expense_summary(
            date_from=date_from,
            date_to=date_to,
        )
        expenses = summary.expenses
        if limit is not None:
            expenses = expenses[:limit]
        return [
            {
                "category_id": e.category_id,
                "category_name": e.category_name,
                "total_amount": float(e.total_amount),
            }
            for e in expenses
        ]

    def sale_collections_by_day(self, date_from: str, date_to: str, limit: Optional[int] = 1000) -> list[sqlite3.Row]:
        """
        Cash collections grouped by cleared_date from sale_payments (clearing_state='cleared').
        """
        sql = """
        SELECT
          sp.cleared_date AS date,
          COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS amount
        FROM sale_payments sp
        WHERE sp.clearing_state = 'cleared'
          AND sp.cleared_date >= ?
          AND sp.cleared_date <= ?
        GROUP BY sp.cleared_date
        ORDER BY sp.cleared_date
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        return list(self.conn.execute(sql, [date_from, date_to, *lim_params]))

    def purchase_disbursements_by_day(self, date_from: str, date_to: str, limit: Optional[int] = 1000) -> list[sqlite3.Row]:
        """
        Cash disbursements grouped by cleared_date.
        Returns gross vendor payments, refunds received, and net outflow.
        """
        totals: dict[str, dict[str, float]] = {}
        for movement in self.accounting.get_vendor_cash_movements(date_from, date_to):
            if movement.type not in {"Disbursement", "Vendor Refund"}:
                continue
            day = movement.date
            totals.setdefault(day, {"date": day, "gross_outflow": 0.0, "refunds_received": 0.0})
            if movement.type == "Disbursement":
                totals[day]["gross_outflow"] += float(movement.amount)
            else:
                totals[day]["refunds_received"] += float(movement.amount)
        rows = []
        for row in sorted(totals.values(), key=lambda item: item["date"]):
            row["net_outflow"] = row["gross_outflow"] - row["refunds_received"]
            rows.append(row)
        return rows if limit is None else rows[:limit]

    # ----------------------------------------------------------------------
    # ------------------------------ SALES (NEW) ---------------------------
    # ----------------------------------------------------------------------
    # Utilities for optional filters

    @staticmethod
    def _statuses_where(statuses: Optional[Sequence[str]]) -> tuple[str, list[object]]:
        if not statuses:
            return "", []
        marks = ",".join("?" for _ in statuses)
        return f" AND s.payment_status IN ({marks}) ", list(statuses)

    @staticmethod
    def _historical_status_where(
        statuses: Optional[Sequence[str]],
        as_of_date: Optional[str],
    ) -> tuple[str, list[object]]:
        if not statuses:
            return "", []
        if not as_of_date:
            marks = ",".join("?" for _ in statuses)
            return f" AND s.payment_status IN ({marks}) ", list(statuses)

        marks = ",".join("?" for _ in statuses)
        paid_total_expr = """
COALESCE((
  SELECT MAX(0.0, COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0))
  FROM sale_payments sp
  WHERE sp.sale_id = s.sale_id
    AND sp.clearing_state = 'cleared'
    AND sp.cleared_date IS NOT NULL
    AND sp.cleared_date <= ?
), 0.0)
"""
        status_expr = f"""
CASE
  WHEN {paid_total_expr} + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)
       >= COALESCE(CAST(s.total_amount AS REAL), 0.0)
  THEN 'paid'
  WHEN {paid_total_expr} + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0) > 0
  THEN 'partial'
  ELSE 'unpaid'
END
"""
        where = f" AND ({status_expr}) IN ({marks}) "
        return where, [as_of_date, as_of_date, *statuses]

    @staticmethod
    def _historical_status_expr(as_of_date: Optional[str]) -> tuple[str, list[object]]:
        if not as_of_date:
            return "s.payment_status", []

        paid_total_expr = """
COALESCE((
  SELECT MAX(0.0, COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0))
  FROM sale_payments sp
  WHERE sp.sale_id = s.sale_id
    AND sp.clearing_state = 'cleared'
    AND sp.cleared_date IS NOT NULL
    AND sp.cleared_date <= ?
), 0.0)
"""
        status_expr = f"""
CASE
  WHEN {paid_total_expr} + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)
       >= COALESCE(CAST(s.total_amount AS REAL), 0.0)
  THEN 'paid'
  WHEN {paid_total_expr} + COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0) > 0
  THEN 'partial'
  ELSE 'unpaid'
END
"""
        return status_expr, [as_of_date, as_of_date]

    @staticmethod
    def _customer_where(customer_id: Optional[int]) -> tuple[str, list[object]]:
        if customer_id is None:
            return "", []
        return " AND s.customer_id = ? ", [customer_id]

    @staticmethod
    def _product_exists_where(product_id: Optional[int]) -> tuple[str, list[object]]:
        """
        Restrict to sales that have at least one line for the given product.
        """
        if product_id is None:
            return "", []
        return (
            " AND EXISTS (SELECT 1 FROM sale_items si WHERE si.sale_id = s.sale_id AND si.product_id = ?) ",
            [product_id],
        )

    @staticmethod
    def _category_exists_where(category: Optional[str]) -> tuple[str, list[object]]:
        """
        Restrict to sales that have at least one line whose product.category matches exactly.
        """
        if not category:
            return "", []
        return (
            " AND EXISTS (SELECT 1 FROM sale_items si JOIN products p2 ON p2.product_id = si.product_id "
            "             WHERE si.sale_id = s.sale_id AND COALESCE(p2.category,'') = ?) ",
            [category],
        )

    @staticmethod
    def _event_where(
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]] = None,
        status_as_of: Optional[str] = None,
        customer_id: Optional[int] = None,
        product_id: Optional[int] = None,
        category: Optional[str] = None,
    ) -> tuple[str, list[object]]:
        where = " WHERE e.event_date >= ? AND e.event_date <= ? "
        params: list[object] = [date_from, date_to]
        sw, sp = ReportingRepo._historical_status_where(statuses, status_as_of)
        where += sw
        params.extend(sp)
        if customer_id is not None:
            where += " AND e.customer_id = ? "
            params.append(customer_id)
        if product_id is not None:
            where += " AND e.product_id = ? "
            params.append(product_id)
        if category:
            where += " AND e.category = ? "
            params.append(category)
        return where, params

    # ---- Lists & lookups ----

    def get_product_categories(self) -> list[sqlite3.Row]:
        """
        Distinct non-empty categories from products.
        Returns rows with a single column 'category'.
        """
        sql = """
        SELECT DISTINCT p.category AS category
        FROM products p
        WHERE p.category IS NOT NULL
          AND TRIM(p.category) <> ''
        ORDER BY p.category COLLATE NOCASE
        """
        return list(self.conn.execute(sql))
    
    def get_all_customers(self) -> list[sqlite3.Row]:
        """
        Get all customers with id and name for batch operations.
        This replaces individual customer queries and addresses N+1 pattern.
        """
        sql = """
        SELECT customer_id, name
        FROM customers
        ORDER BY name COLLATE NOCASE
        """
        return list(self.conn.execute(sql))
    
    def get_all_vendors(self) -> list[sqlite3.Row]:
        """
        Get all vendors with id and name for batch operations.
        This replaces individual vendor queries and addresses N+1 pattern.
        """
        sql = """
        SELECT vendor_id, name
        FROM vendors
        ORDER BY name COLLATE NOCASE
        """
        return list(self.conn.execute(sql))

    # ---- Sales by period (daily/monthly/yearly) ----

    def sales_by_period(
        self,
        date_from: str,
        date_to: str,
        granularity: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        fmt = {
            "daily": "%Y-%m-%d",
            "monthly": "%Y-%m",
            "yearly": "%Y",
        }.get(granularity, "%Y-%m-%d")

        where, params = self._event_where(
            date_from, date_to, statuses, date_to, customer_id, product_id, category
        )

        sql = f"""
        SELECT
          STRFTIME('{fmt}', DATE(e.event_date)) AS period,
          COUNT(DISTINCT CASE WHEN e.event_type = 'sale' THEN e.sale_id END) AS order_count,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        {where}
        GROUP BY STRFTIME('{fmt}', DATE(e.event_date))
        ORDER BY period
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        params.extend(lim_params)
        return list(self.conn.execute(sql, params))

    # ---- Sales by customer ----

    def sales_by_customer(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        where, params = self._event_where(
            date_from, date_to, statuses, date_to, customer_id, product_id, category
        )
        sql = f"""
        SELECT
          cu.name AS customer_name,
          COUNT(DISTINCT CASE WHEN e.event_type = 'sale' THEN e.sale_id END) AS order_count,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue,
          COALESCE(SUM(CAST(e.cogs AS REAL)), 0.0) AS cogs,
          COALESCE(SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL)), 0.0) AS gross,
          CASE WHEN COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) = 0 THEN 0.0
               ELSE SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL))
                    / SUM(CAST(e.revenue AS REAL))
          END AS margin_pct
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        LEFT JOIN customers cu ON cu.customer_id = e.customer_id
        {where}
        GROUP BY e.customer_id, cu.name
        ORDER BY revenue DESC, cu.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        params.extend(lim_params)
        return list(self.conn.execute(sql, params))

    # ---- Sales by product ----

    def sales_by_product(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        """Net sales, quantity, and COGS by product."""
        where, params = self._event_where(
            date_from, date_to, statuses, date_to, customer_id, product_id, category
        )

        sql = f"""
        SELECT
          p.name AS product_name,
          COALESCE(SUM(CAST(e.quantity_base AS REAL)), 0.0) AS qty_base,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue,
          COALESCE(SUM(CAST(e.cogs AS REAL)), 0.0) AS cogs,
          COALESCE(SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL)), 0.0) AS gross,
          CASE WHEN COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) = 0 THEN 0.0
               ELSE SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL))
                    / SUM(CAST(e.revenue AS REAL))
          END AS margin_pct
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        LEFT JOIN products p ON p.product_id = e.product_id
        {where}
        GROUP BY e.product_id, p.name
        ORDER BY revenue DESC, p.name COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        params.extend(lim_params)
        return list(self.conn.execute(sql, params))

    # ---- Sales by category ----

    def sales_by_category(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        """Net sales, quantity, and COGS by product category."""
        where, params = self._event_where(
            date_from, date_to, statuses, date_to, customer_id, product_id, category
        )

        sql = f"""
        SELECT
          CASE WHEN e.category = '' THEN '(Uncategorized)' ELSE e.category END AS category,
          COALESCE(SUM(CAST(e.quantity_base AS REAL)), 0.0) AS qty_base,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue,
          COALESCE(SUM(CAST(e.cogs AS REAL)), 0.0) AS cogs,
          COALESCE(SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL)), 0.0) AS gross,
          CASE WHEN COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) = 0 THEN 0.0
               ELSE SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL))
                    / SUM(CAST(e.revenue AS REAL))
          END AS margin_pct
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        {where}
        GROUP BY CASE WHEN e.category = '' THEN '(Uncategorized)' ELSE e.category END
        ORDER BY revenue DESC, category COLLATE NOCASE
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        params.extend(lim_params)
        return list(self.conn.execute(sql, params))

    # ---- Margin by period (daily/monthly/yearly) ----

    def margin_by_period(
        self,
        date_from: str,
        date_to: str,
        granularity: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        fmt = {
            "daily": "%Y-%m-%d",
            "monthly": "%Y-%m",
            "yearly": "%Y",
        }.get(granularity, "%Y-%m-%d")

        where, params = self._event_where(
            date_from, date_to, statuses, date_to, customer_id, product_id, category
        )

        sql = f"""
        SELECT
          STRFTIME('{fmt}', DATE(e.event_date)) AS period,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue,
          COALESCE(SUM(CAST(e.cogs AS REAL)), 0.0) AS cogs,
          COALESCE(SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL)), 0.0) AS gross,
          CASE WHEN COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) = 0 THEN 0.0
               ELSE SUM(CAST(e.revenue AS REAL) - CAST(e.cogs AS REAL))
                    / SUM(CAST(e.revenue AS REAL))
          END AS margin_pct
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        {where}
        GROUP BY STRFTIME('{fmt}', DATE(e.event_date))
        ORDER BY period
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        params.extend(lim_params)
        return list(self.conn.execute(sql, params))

    # ---- Margin by customer ----

    def margin_by_customer(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        # Reuse the sales_by_customer logic but include margin fields; already implemented there.
        # Expose a dedicated method for the UI for clarity (same SQL pattern).
        return self.sales_by_customer(date_from, date_to, statuses, customer_id, product_id, category, limit=limit)

    # ---- Margin by product ----

    def margin_by_product(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        # Same output as sales_by_product with margin columns; reusing the same query is acceptable.
        return self.sales_by_product(date_from, date_to, statuses, customer_id, product_id, category, limit=limit)

    # ---- Margin by category ----

    def margin_by_category(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        return self.sales_by_category(date_from, date_to, statuses, customer_id, product_id, category, limit=limit)

    # ---- Top customers ----

    def top_customers(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        limit_n: int,
    ) -> list[sqlite3.Row]:
        where, params = self._event_where(date_from, date_to, statuses, date_to)

        sql = f"""
        SELECT
          cu.name AS customer_name,
          COUNT(DISTINCT CASE WHEN e.event_type = 'sale' THEN e.sale_id END) AS order_count,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        LEFT JOIN customers cu ON cu.customer_id = e.customer_id
        {where}
        GROUP BY e.customer_id, cu.name
        ORDER BY revenue DESC, cu.name COLLATE NOCASE
        LIMIT ?
        """
        params.append(int(limit_n))
        return list(self.conn.execute(sql, params))

    # ---- Top products ----

    def top_products(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        limit_n: int,
    ) -> list[sqlite3.Row]:
        """Rank products by net revenue and quantity."""
        where, params = self._event_where(date_from, date_to, statuses, date_to)

        sql = f"""
        SELECT
          p.name AS product_name,
          COALESCE(SUM(CAST(e.quantity_base AS REAL)), 0.0) AS qty_base,
          COALESCE(SUM(CAST(e.revenue AS REAL)), 0.0) AS revenue
        FROM sale_financial_events e
        JOIN sales s ON s.sale_id = e.sale_id
        LEFT JOIN products p ON p.product_id = e.product_id
        {where}
        GROUP BY e.product_id, p.name
        ORDER BY revenue DESC, p.name COLLATE NOCASE
        LIMIT ?
        """
        params.append(int(limit_n))
        return list(self.conn.execute(sql, params))

    # ---- Returns summary ----

    def returns_summary(self, date_from: str, date_to: str) -> list[sqlite3.Row]:
        """
        Sale return indicators:
          - Requested Refunds: SUM of negative sale_payments.amount by posting date
          - Cleared Refunds: SUM of negative sale_payments.amount by cleared_date,
            limited to clearing_state='cleared'
          - Returned Qty (base): returned base quantity
          - Return Value: immutable returned revenue value
          - COGS Reversed: immutable original-sale COGS reversal
        """
        # Refund requests follow posting date.
        sql_requested_refunds = """
        SELECT COALESCE(SUM(CASE WHEN CAST(sp.amount AS REAL) < 0 THEN CAST(sp.amount AS REAL) ELSE 0 END), 0.0) AS refunds_sum
        FROM sale_payments sp
        WHERE sp.date >= ? AND sp.date <= ?
        """
        requested = self.conn.execute(sql_requested_refunds, (date_from, date_to)).fetchone()
        requested_refunds_sum = float(
            requested["refunds_sum"] if requested and requested["refunds_sum"] is not None else 0.0
        )

        # Cleared cash follows cleared_date and cleared state.
        sql_cleared_refunds = """
        SELECT COALESCE(SUM(CASE WHEN CAST(sp.amount AS REAL) < 0 THEN CAST(sp.amount AS REAL) ELSE 0 END), 0.0) AS refunds_sum
        FROM sale_payments sp
        WHERE sp.clearing_state = 'cleared'
          AND sp.cleared_date IS NOT NULL
          AND sp.cleared_date >= ?
          AND sp.cleared_date <= ?
        """
        cleared = self.conn.execute(sql_cleared_refunds, (date_from, date_to)).fetchone()
        cleared_refunds_sum = float(
            cleared["refunds_sum"] if cleared and cleared["refunds_sum"] is not None else 0.0
        )

        # returns qty (base)
        sql_qty = """
        SELECT COALESCE(SUM(CAST(srs.returned_quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)), 0.0) AS qty_base
        FROM sale_return_snapshots srs
        LEFT JOIN product_uoms pu
               ON pu.product_id = srs.product_id AND pu.uom_id = srs.uom_id
        WHERE srs.return_date >= ? AND srs.return_date <= ?
        """
        qty = self.conn.execute(sql_qty, (date_from, date_to)).fetchone()
        qty_base = float(qty["qty_base"] if qty and qty["qty_base"] is not None else 0.0)

        values = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(CAST(return_value AS REAL)), 0.0) AS returns_value,
              COALESCE(SUM(CAST(cogs_reversal_value AS REAL)), 0.0) AS cogs_reversed
            FROM sale_return_snapshots
            WHERE return_date >= ? AND return_date <= ?
            """,
            (date_from, date_to),
        ).fetchone()
        returns_value = float(values["returns_value"] or 0.0)
        cogs_reversed = float(values["cogs_reversed"] or 0.0)

        # Return as rows {metric, value}
        cur = self.conn.cursor()
        cur.execute("SELECT ? AS metric, ? AS value", ("Requested Refunds", requested_refunds_sum))
        row1 = cur.fetchone()
        cur.execute("SELECT ? AS metric, ? AS value", ("Cleared Refunds", cleared_refunds_sum))
        row2 = cur.fetchone()
        cur.execute("SELECT ? AS metric, ? AS value", ("Returned Qty (base)", qty_base))
        row3 = cur.fetchone()
        cur.execute("SELECT ? AS metric, ? AS value", ("Return Value", returns_value))
        row4 = cur.fetchone()
        cur.execute("SELECT ? AS metric, ? AS value", ("COGS Reversed", cogs_reversed))
        row5 = cur.fetchone()
        return [row1, row2, row3, row4, row5]

    # ---- Status breakdown ----

    def status_breakdown(
        self,
        date_from: str,
        date_to: str,
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
    ) -> list[sqlite3.Row]:
        where, params = self._event_where(
            date_from, date_to, None, None, customer_id, product_id, category
        )
        status_expr, status_params = self._historical_status_expr(date_to)

        sql = f"""
        WITH filtered AS (
          SELECT
            {status_expr} AS payment_status,
            e.event_type,
            e.sale_id,
            e.revenue
          FROM sale_financial_events e
          JOIN sales s ON s.sale_id = e.sale_id
          {where}
        )
        SELECT
          payment_status,
          COUNT(DISTINCT CASE WHEN event_type = 'sale' THEN sale_id END) AS order_count,
          COALESCE(SUM(CAST(revenue AS REAL)), 0.0) AS revenue
        FROM filtered
        GROUP BY payment_status
        ORDER BY payment_status
        """
        lim_sql, lim_params = self._limit_clause(limit)
        sql += lim_sql
        return list(self.conn.execute(sql, [*status_params, *params, *lim_params]))

    # ---- Drill-down sales ----

    def drilldown_sales(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
        limit: Optional[int] = 1000,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """
        Return header-level rows filtered by the same criteria,
        with customer name and amounts. Remaining = total - paid - advance.
        """
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._historical_status_where(statuses, date_to)
        where += sw
        params += sp
        status_expr, status_params = self._historical_status_expr(date_to)

        cw, cp = self._customer_where(customer_id)
        where += cw
        params += cp

        pw, pp_ = self._product_exists_where(product_id)
        where += pw
        params += pp_

        kw, kp = self._category_exists_where(category)
        where += kw
        params += kp

        sql = f"""
        WITH filtered AS (
          SELECT
            s.sale_id                       AS sale_id,
            s.date                          AS date,
            cu.name                         AS customer_name,
            {status_expr}                   AS payment_status,
            srt.canonical_total_amount AS total_amount,
            srt.paid_amount AS paid_amount,
            srt.advance_payment_applied AS advance_payment_applied,
            srt.remaining_due AS remaining_due
          FROM sales s
          JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
          LEFT JOIN customers cu ON cu.customer_id = s.customer_id
          {where}
        )
        SELECT *
        FROM filtered
        ORDER BY date DESC, sale_id DESC
        """
        lim_sql, lim_params = self._limit_clause(limit, offset)
        sql += lim_sql
        return list(self.conn.execute(sql, [*status_params, *params, *lim_params]))
