"""Current purchase report read bundles, preserved before cleanup."""

from __future__ import annotations

from sqlite3 import Connection

from ..dto import PurchaseReportBundle


def get_purchase_reports(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> PurchaseReportBundle:
    # ACC-RULE-111: Purchase report bundle
    # Builds purchase drilldown rows and spend by period for a date range.
    # Uses purchase totals, paid amounts, applied advances, and remaining due.
    # Supports purchase reports without changing payable state.
    date_from = start_date or "0001-01-01"
    date_to = end_date or "9999-12-31"

    rows_by_key: dict[str, tuple[dict, ...]] = {}
    rows_by_key["drilldown"] = tuple(
        dict(row)
        for row in conn.execute(
            """
            SELECT p.purchase_id, p.date, v.name AS vendor_name, p.payment_status,
                   COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) AS total_amount,
                   CAST(p.paid_amount AS REAL) AS paid_amount,
                   CAST(p.advance_payment_applied AS REAL) AS adv,
                   (COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))
                    - CAST(p.paid_amount AS REAL)
                    - CAST(p.advance_payment_applied AS REAL)) AS remaining
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            JOIN vendors v ON v.vendor_id = p.vendor_id
            WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
            ORDER BY DATE(p.date) DESC, p.purchase_id DESC
            """,
            (date_from, date_to),
        )
    )
    rows_by_key["purch_by_period"] = tuple(
        dict(row)
        for row in conn.execute(
            """
            SELECT p.date AS period,
                   COUNT(*) AS order_count,
                   SUM(COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))) AS spend
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
            GROUP BY p.date
            ORDER BY p.date
            """,
            (date_from, date_to),
        )
    )
    return PurchaseReportBundle(rows_by_key)
