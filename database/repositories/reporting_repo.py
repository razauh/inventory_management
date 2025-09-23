# inventory_management/database/repositories/reporting_repo.py
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence


class ReportingRepo:
    """
    Read-only queries for Reporting tabs, aligned with schema.py.

    Uses only objects your schema defines:
      - Tables: sales, sale_items, customers, products,
                sale_payments, customer_advances,
                purchases, purchase_payments, vendor_advances,
                expenses, expense_categories,
                inventory_transactions, product_uoms,
                stock_valuation_history
      - Views:  sale_detailed_totals, v_stock_on_hand, sale_item_cogs

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

    # ----------------------------------------------------------------------
    # -------------------------- AGING (AP / AR) ---------------------------
    # ----------------------------------------------------------------------

    def vendor_headers_as_of(self, vendor_id: int, as_of: str) -> list[sqlite3.Row]:
        """
        Purchase headers for remaining due calc as of a cutoff (inclusive).
        remaining = total_amount - paid_amount - advance_payment_applied
        """
        sql = """
        SELECT
            p.purchase_id AS doc_no,
            p.date        AS date,
            COALESCE(p.total_amount, 0.0)             AS total_amount,
            COALESCE(p.paid_amount, 0.0)              AS paid_amount,
            COALESCE(p.advance_payment_applied, 0.0)  AS advance_payment_applied
        FROM purchases p
        WHERE p.vendor_id = ?
          AND p.date <= ?
        ORDER BY p.date, p.purchase_id
        """
        return list(self.conn.execute(sql, (vendor_id, as_of)))

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
        SELECT
            s.sale_id     AS doc_no,
            s.date        AS date,
            COALESCE(s.total_amount, 0.0)             AS total_amount,
            COALESCE(s.paid_amount, 0.0)              AS paid_amount,
            COALESCE(s.advance_payment_applied, 0.0)  AS advance_payment_applied
        FROM sales s
        WHERE s.customer_id = ?
          AND s.doc_type = 'sale'
          AND s.date <= ?
        ORDER BY s.date, s.sale_id
        """
        return list(self.conn.execute(sql, (customer_id, as_of)))

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
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> list[sqlite3.Row]:
        """
        Totals per category in [date_from, date_to].
        expense_categories(category_id, name)
        expenses(expense_id, date, amount, category_id, ...)
        """
        params: list[object] = [date_from, date_to]
        where_extra = ""
        if category_id is not None:
            where_extra = " AND e.category_id = ? "
            params.append(category_id)

        sql = f"""
        SELECT
            ec.category_id                     AS category_id,
            ec.name                            AS category_name,
            COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS total_amount
        FROM expense_categories ec
        LEFT JOIN expenses e
               ON e.category_id = ec.category_id
              AND e.date >= ?
              AND e.date <= ?
              {where_extra}
        GROUP BY ec.category_id, ec.name
        ORDER BY ec.name COLLATE NOCASE
        """
        return list(self.conn.execute(sql, params))

    def expense_lines(
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> list[sqlite3.Row]:
        """
        Raw expense lines for the period and optional category.
        """
        params: list[object] = [date_from, date_to]
        where_extra = ""
        if category_id is not None:
            where_extra = " AND e.category_id = ? "
            params.append(category_id)

        sql = f"""
        SELECT
            e.expense_id                 AS expense_id,
            e.date                       AS date,
            ec.name                      AS category_name,
            e.description                AS description,
            COALESCE(CAST(e.amount AS REAL), 0.0) AS amount
        FROM expenses e
        JOIN expense_categories ec ON ec.category_id = e.category_id
        WHERE e.date >= ?
          AND e.date <= ?
          {where_extra}
        ORDER BY e.date DESC, e.expense_id DESC
        """
        return list(self.conn.execute(sql, params))

    # ----------------------------------------------------------------------
    # ------------------------------ INVENTORY -----------------------------
    # ----------------------------------------------------------------------

    def stock_on_hand_current(self) -> list[sqlite3.Row]:
        """
        Current snapshot from v_stock_on_hand.
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
        return list(self.conn.execute(sql))

    def stock_on_hand_as_of(self, as_of: str) -> list[sqlite3.Row]:
        """
        Latest valuation row per product where valuation_date <= as_of.
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
        return list(self.conn.execute(sql, (as_of,)))

    def inventory_transactions(self, date_from: str, date_to: str, product_id: int | None) -> list[sqlite3.Row]:
        """
        Return transactions with base-qty conversion.
        Columns returned (UI expects): date, product_id, type, qty_base, ref_table, ref_id, notes
        """
        params: list[object] = [date_from, date_to]
        where_extra = ""
        if isinstance(product_id, int):
            where_extra = " AND it.product_id = ? "
            params.append(product_id)

        sql = f"""
        SELECT
          it.date AS date,
          it.product_id AS product_id,
          it.transaction_type AS type,
          (CAST(it.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)) AS qty_base,
          it.reference_table AS ref_table,
          it.reference_id    AS ref_id,
          it.notes           AS notes
        FROM inventory_transactions it
        LEFT JOIN product_uoms pu
          ON pu.product_id = it.product_id
         AND pu.uom_id     = it.uom_id
        WHERE it.date >= ? AND it.date <= ?
        {where_extra}
        ORDER BY it.date ASC, it.transaction_id ASC
        """
        return list(self.conn.execute(sql, params))

    def valuation_history(self, product_id: int, limit: int) -> list[sqlite3.Row]:
        """
        Latest N valuation rows for a product.
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
        """
        Revenue over period by sales.date; doc_type='sale' only.
        Prefer header total_amount but fall back to sale_detailed_totals if present.
        """
        sql = """
        SELECT COALESCE(
                 SUM(COALESCE(sdt.calculated_total_amount, CAST(s.total_amount AS REAL))),
                 0.0
               ) AS rev
        FROM sales s
        LEFT JOIN sale_detailed_totals sdt
          ON sdt.sale_id = s.sale_id
        WHERE s.doc_type = 'sale'
          AND s.date >= ? AND s.date <= ?
        """
        row = self.conn.execute(sql, (date_from, date_to)).fetchone()
        return float(row["rev"] if row and row["rev"] is not None else 0.0)

    def cogs_total(self, date_from: str, date_to: str) -> float:
        """
        Use sale_item_cogs view (moving-average at sale date; doc_type='sale' only).
        """
        sql = """
        SELECT COALESCE(SUM(c.cogs_value), 0.0) AS cogs
        FROM sales s
        JOIN sale_item_cogs c ON c.sale_id = s.sale_id
        WHERE s.doc_type = 'sale'
          AND s.date >= ? AND s.date <= ?
        """
        row = self.conn.execute(sql, (date_from, date_to)).fetchone()
        return float(row["cogs"] if row and row["cogs"] is not None else 0.0)

    def expenses_by_category(self, date_from: str, date_to: str) -> list[sqlite3.Row]:
        """
        Detailed expense totals by category for P&L middle block.
        Returns category_id, category_name, total_amount (names match UI).
        """
        sql = """
        SELECT
          ec.category_id                     AS category_id,
          ec.name                            AS category_name,
          COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS total_amount
        FROM expense_categories ec
        LEFT JOIN expenses e
               ON e.category_id = ec.category_id
              AND e.date >= ? AND e.date <= ?
        GROUP BY ec.category_id, ec.name
        ORDER BY ec.name COLLATE NOCASE
        """
        return list(self.conn.execute(sql, (date_from, date_to)))

    def sale_collections_by_day(self, date_from: str, date_to: str) -> list[sqlite3.Row]:
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
        return list(self.conn.execute(sql, (date_from, date_to)))

    def purchase_disbursements_by_day(self, date_from: str, date_to: str) -> list[sqlite3.Row]:
        """
        Cash disbursements grouped by cleared_date from purchase_payments (clearing_state='cleared').
        """
        sql = """
        SELECT
          pp.cleared_date AS date,
          COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS amount
        FROM purchase_payments pp
        WHERE pp.clearing_state = 'cleared'
          AND pp.cleared_date >= ?
          AND pp.cleared_date <= ?
        GROUP BY pp.cleared_date
        ORDER BY pp.cleared_date
        """
        return list(self.conn.execute(sql, (date_from, date_to)))

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
    ) -> list[sqlite3.Row]:
        fmt = {
            "daily": "%Y-%m-%d",
            "monthly": "%Y-%m",
            "yearly": "%Y",
        }.get(granularity, "%Y-%m-%d")

        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        # optional filters
        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

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
        SELECT
          STRFTIME('{fmt}', DATE(s.date)) AS period,
          COUNT(*)                         AS order_count,
          COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS revenue
        FROM sales s
        {where}
        GROUP BY STRFTIME('{fmt}', DATE(s.date))
        ORDER BY period
        """
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
    ) -> list[sqlite3.Row]:
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

        cw, cp = self._customer_where(customer_id)
        where += cw
        params += cp

        pw, pp_ = self._product_exists_where(product_id)
        where += pw
        params += pp_

        kw, kp = self._category_exists_where(category)
        where += kw
        params += kp

        # Revenue from headers; COGS via sale_item_cogs joined by sale_id (aggregated per customer)
        sql = f"""
        WITH revenue AS (
          SELECT s.customer_id,
                 COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS revenue,
                 COUNT(*) AS order_count
          FROM sales s
          {where}
          GROUP BY s.customer_id
        ), cogs AS (
          SELECT s.customer_id,
                 COALESCE(SUM(CAST(c.cogs_value AS REAL)), 0.0) AS cogs
          FROM sales s
          JOIN sale_item_cogs c ON c.sale_id = s.sale_id
          {where}
          GROUP BY s.customer_id
        )
        SELECT
          cu.name AS customer_name,
          COALESCE(r.order_count, 0) AS order_count,
          COALESCE(r.revenue, 0.0)   AS revenue,
          COALESCE(g.cogs, 0.0)      AS cogs,
          (COALESCE(r.revenue,0.0) - COALESCE(g.cogs,0.0)) AS gross,
          CASE WHEN COALESCE(r.revenue,0.0) = 0 THEN 0.0
               ELSE (COALESCE(r.revenue,0.0) - COALESCE(g.cogs,0.0)) / COALESCE(r.revenue,0.0)
          END AS margin_pct
        FROM revenue r
        LEFT JOIN cogs g ON g.customer_id = r.customer_id
        LEFT JOIN customers cu ON cu.customer_id = r.customer_id
        ORDER BY revenue DESC, cu.name COLLATE NOCASE
        """
        return list(self.conn.execute(sql, params * 2))  # same WHERE/params repeated for cogs CTE

    # ---- Sales by product ----

    def sales_by_product(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        """
        Revenue at product-level from line items:
          line_revenue = quantity * (unit_price - item_discount)
        qty_base via product_uoms.factor_to_base
        COGS via sale_item_cogs (already at product granularity)
        """
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

        cw, cp = self._customer_where(customer_id)
        where += cw
        params += cp

        if product_id is not None:
            where += " AND si.product_id = ? "
            params.append(product_id)

        if category:
            where += " AND COALESCE(p.category,'') = ? "
            params.append(category)

        sql = f"""
        WITH line_rev AS (
          SELECT
            si.product_id,
            p.name AS product_name,
            SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - COALESCE(CAST(si.item_discount AS REAL),0))) AS revenue,
            SUM(CAST(si.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)) AS qty_base
          FROM sales s
          JOIN sale_items si ON si.sale_id = s.sale_id
          LEFT JOIN products p ON p.product_id = si.product_id
          LEFT JOIN product_uoms pu
                 ON pu.product_id = si.product_id AND pu.uom_id = si.uom_id
          {where}
          GROUP BY si.product_id, p.name
        ),
        cogs AS (
          SELECT
            c.product_id,
            SUM(CAST(c.cogs_value AS REAL)) AS cogs
          FROM sales s
          JOIN sale_item_cogs c ON c.sale_id = s.sale_id
          {self._statuses_where(statuses)[0].replace('s.', 's.')}
          {self._customer_where(customer_id)[0].replace('s.', 's.')}
          {" AND c.product_id = ? " if product_id is not None else ""}
          {" AND EXISTS (SELECT 1 FROM products p3 WHERE p3.product_id = c.product_id AND COALESCE(p3.category,'') = ?) " if category else ""}
          AND s.doc_type = 'sale'
          AND s.date >= ? AND s.date <= ?
          GROUP BY c.product_id
        )
        SELECT
          lr.product_name,
          lr.qty_base,
          COALESCE(lr.revenue, 0.0) AS revenue,
          COALESCE(g.cogs, 0.0)     AS cogs,
          (COALESCE(lr.revenue,0.0) - COALESCE(g.cogs,0.0)) AS gross,
          CASE WHEN COALESCE(lr.revenue,0.0) = 0 THEN 0.0
               ELSE (COALESCE(lr.revenue,0.0) - COALESCE(g.cogs,0.0)) / COALESCE(lr.revenue,0.0)
          END AS margin_pct
        FROM line_rev lr
        LEFT JOIN cogs g ON g.product_id = lr.product_id
        ORDER BY revenue DESC, lr.product_name COLLATE NOCASE
        """
        params_cogs: list[object] = []
        # replicate optional filters for cogs CTE (order: statuses, customer, product, category, dates)
        if statuses:
            params_cogs += list(statuses)
        if customer_id is not None:
            params_cogs.append(customer_id)
        if product_id is not None:
            params_cogs.append(product_id)
        if category:
            params_cogs.append(category)
        params_cogs += [date_from, date_to]

        return list(self.conn.execute(sql, params + params_cogs))

    # ---- Sales by category ----

    def sales_by_category(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        """
        Use products.category free-text.
        """
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

        cw, cp = self._customer_where(customer_id)
        where += cw
        params += cp

        if product_id is not None:
            where += " AND si.product_id = ? "
            params.append(product_id)

        if category:
            where += " AND COALESCE(p.category,'') = ? "
            params.append(category)

        sql = f"""
        WITH line_rev AS (
          SELECT
            COALESCE(p.category, '(Uncategorized)') AS category,
            SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - COALESCE(CAST(si.item_discount AS REAL),0))) AS revenue,
            SUM(CAST(si.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)) AS qty_base
          FROM sales s
          JOIN sale_items si ON si.sale_id = s.sale_id
          LEFT JOIN products p ON p.product_id = si.product_id
          LEFT JOIN product_uoms pu
                 ON pu.product_id = si.product_id AND pu.uom_id = si.uom_id
          {where}
          GROUP BY COALESCE(p.category, '(Uncategorized)')
        ),
        cogs AS (
          SELECT
            COALESCE(p2.category, '(Uncategorized)') AS category,
            SUM(CAST(c.cogs_value AS REAL)) AS cogs
          FROM sales s
          JOIN sale_item_cogs c ON c.sale_id = s.sale_id
          LEFT JOIN products p2 ON p2.product_id = c.product_id
          {self._statuses_where(statuses)[0].replace('s.', 's.')}
          {self._customer_where(customer_id)[0].replace('s.', 's.')}
          {" AND c.product_id = ? " if product_id is not None else ""}
          {" AND COALESCE(p2.category,'') = ? " if category else ""}
          AND s.doc_type = 'sale'
          AND s.date >= ? AND s.date <= ?
          GROUP BY COALESCE(p2.category, '(Uncategorized)')
        )
        SELECT
          lr.category,
          lr.qty_base,
          COALESCE(lr.revenue, 0.0) AS revenue,
          COALESCE(g.cogs, 0.0)     AS cogs,
          (COALESCE(lr.revenue,0.0) - COALESCE(g.cogs,0.0)) AS gross,
          CASE WHEN COALESCE(lr.revenue,0.0) = 0 THEN 0.0
               ELSE (COALESCE(lr.revenue,0.0) - COALESCE(g.cogs,0.0)) / COALESCE(lr.revenue,0.0)
          END AS margin_pct
        FROM line_rev lr
        LEFT JOIN cogs g ON g.category = lr.category
        ORDER BY revenue DESC, lr.category COLLATE NOCASE
        """
        params_cogs: list[object] = []
        if statuses:
            params_cogs += list(statuses)
        if customer_id is not None:
            params_cogs.append(customer_id)
        if product_id is not None:
            params_cogs.append(product_id)
        if category:
            params_cogs.append(category)
        params_cogs += [date_from, date_to]

        return list(self.conn.execute(sql, params + params_cogs))

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
    ) -> list[sqlite3.Row]:
        fmt = {
            "daily": "%Y-%m-%d",
            "monthly": "%Y-%m",
            "yearly": "%Y",
        }.get(granularity, "%Y-%m-%d")

        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

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
        WITH rev AS (
          SELECT
            STRFTIME('{fmt}', DATE(s.date)) AS period,
            SUM(CAST(s.total_amount AS REAL)) AS revenue
          FROM sales s
          {where}
          GROUP BY STRFTIME('{fmt}', DATE(s.date))
        ),
        cg AS (
          SELECT
            STRFTIME('{fmt}', DATE(s.date)) AS period,
            SUM(CAST(c.cogs_value AS REAL)) AS cogs
          FROM sales s
          JOIN sale_item_cogs c ON c.sale_id = s.sale_id
          {where}
          GROUP BY STRFTIME('{fmt}', DATE(s.date))
        )
        SELECT
          r.period,
          COALESCE(r.revenue, 0.0) AS revenue,
          COALESCE(cg.cogs, 0.0)   AS cogs,
          (COALESCE(r.revenue,0.0) - COALESCE(cg.cogs,0.0)) AS gross,
          CASE WHEN COALESCE(r.revenue,0.0) = 0 THEN 0.0
               ELSE (COALESCE(r.revenue,0.0) - COALESCE(cg.cogs,0.0)) / COALESCE(r.revenue,0.0)
          END AS margin_pct
        FROM rev r
        LEFT JOIN cg ON cg.period = r.period
        ORDER BY r.period
        """
        # NOTE: same WHERE block used twice (rev + cg), so duplicate params
        return list(self.conn.execute(sql, params + params))

    # ---- Margin by customer ----

    def margin_by_customer(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        # Reuse the sales_by_customer logic but include margin fields; already implemented there.
        # Expose a dedicated method for the UI for clarity (same SQL pattern).
        return self.sales_by_customer(date_from, date_to, statuses, customer_id, product_id, category)

    # ---- Margin by product ----

    def margin_by_product(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        # Same output as sales_by_product with margin columns; reusing the same query is acceptable.
        return self.sales_by_product(date_from, date_to, statuses, customer_id, product_id, category)

    # ---- Margin by category ----

    def margin_by_category(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        return self.sales_by_category(date_from, date_to, statuses, customer_id, product_id, category)

    # ---- Top customers ----

    def top_customers(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        limit_n: int,
    ) -> list[sqlite3.Row]:
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

        sql = f"""
        SELECT
          cu.name AS customer_name,
          COUNT(*) AS order_count,
          COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS revenue
        FROM sales s
        LEFT JOIN customers cu ON cu.customer_id = s.customer_id
        {where}
        GROUP BY s.customer_id, cu.name
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
        """
        Rank by revenue from line items; also return qty_base.
        """
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

        sql = f"""
        SELECT
          p.name AS product_name,
          SUM(CAST(si.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)) AS qty_base,
          SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - COALESCE(CAST(si.item_discount AS REAL),0))) AS revenue
        FROM sales s
        JOIN sale_items si ON si.sale_id = s.sale_id
        LEFT JOIN products p ON p.product_id = si.product_id
        LEFT JOIN product_uoms pu
               ON pu.product_id = si.product_id AND pu.uom_id = si.uom_id
        {where}
        GROUP BY p.name
        ORDER BY revenue DESC, p.name COLLATE NOCASE
        LIMIT ?
        """
        params.append(int(limit_n))
        return list(self.conn.execute(sql, params))

    # ---- Returns summary ----

    def returns_summary(self, date_from: str, date_to: str) -> list[sqlite3.Row]:
        """
        Basic returns indicators using available schema:
          - refunds_sum: SUM of negative sale_payments.amount between dates (any clearing_state)
          - returns_qty_base: SUM base-qty of inventory_transactions with type='sale_return' between dates
        """
        # refunds (negative payments)
        sql_refunds = """
        SELECT COALESCE(SUM(CASE WHEN CAST(sp.amount AS REAL) < 0 THEN CAST(sp.amount AS REAL) ELSE 0 END), 0.0) AS refunds_sum
        FROM sale_payments sp
        WHERE sp.date >= ? AND sp.date <= ?
        """
        refunds = self.conn.execute(sql_refunds, (date_from, date_to)).fetchone()
        refunds_sum = float(refunds["refunds_sum"] if refunds and refunds["refunds_sum"] is not None else 0.0)

        # returns qty (base)
        sql_qty = """
        SELECT COALESCE(SUM(CAST(it.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)), 0.0) AS qty_base
        FROM inventory_transactions it
        LEFT JOIN product_uoms pu
               ON pu.product_id = it.product_id AND pu.uom_id = it.uom_id
        WHERE it.transaction_type = 'sale_return'
          AND it.date >= ? AND it.date <= ?
        """
        qty = self.conn.execute(sql_qty, (date_from, date_to)).fetchone()
        qty_base = float(qty["qty_base"] if qty and qty["qty_base"] is not None else 0.0)

        # Return as rows {metric, value}
        cur = self.conn.cursor()
        cur.execute("SELECT ? AS metric, ? AS value", ("refunds_sum", refunds_sum))
        row1 = cur.fetchone()
        cur.execute("SELECT ? AS metric, ? AS value", ("returns_qty_base", qty_base))
        row2 = cur.fetchone()
        return [row1, row2]

    # ---- Status breakdown ----

    def status_breakdown(
        self,
        date_from: str,
        date_to: str,
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

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
        SELECT
          s.payment_status AS payment_status,
          COUNT(*)         AS order_count,
          COALESCE(SUM(CAST(s.total_amount AS REAL)), 0.0) AS revenue
        FROM sales s
        {where}
        GROUP BY s.payment_status
        ORDER BY s.payment_status
        """
        return list(self.conn.execute(sql, params))

    # ---- Drill-down sales ----

    def drilldown_sales(
        self,
        date_from: str,
        date_to: str,
        statuses: Optional[Sequence[str]],
        customer_id: Optional[int],
        product_id: Optional[int],
        category: Optional[str],
    ) -> list[sqlite3.Row]:
        """
        Return header-level rows filtered by the same criteria,
        with customer name and amounts. Remaining = total - paid - advance.
        """
        params: list[object] = [date_from, date_to]
        where = " WHERE s.doc_type = 'sale' AND s.date >= ? AND s.date <= ? "

        sw, sp = self._statuses_where(statuses)
        where += sw
        params += sp

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
        SELECT
          s.sale_id                       AS sale_id,
          s.date                          AS date,
          cu.name                         AS customer_name,
          s.payment_status                AS payment_status,
          COALESCE(CAST(s.total_amount AS REAL), 0.0)            AS total_amount,
          COALESCE(CAST(s.paid_amount AS REAL), 0.0)             AS paid_amount,
          COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0) AS advance_payment_applied
        FROM sales s
        LEFT JOIN customers cu ON cu.customer_id = s.customer_id
        {where}
        ORDER BY s.date DESC, s.sale_id DESC
        """
        return list(self.conn.execute(sql, params))
