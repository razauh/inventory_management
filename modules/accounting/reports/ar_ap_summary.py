"""Current AR/AP and payment report reads, preserved before cleanup."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from ..dto import APSummary, PaymentActivityReport, VendorAgingReport


_EPS = 1e-9


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _reporting_repo(conn: Connection, repo=None):
    if repo is not None:
        return repo
    try:
        from ....database.repositories.reporting_repo import ReportingRepo
    except ImportError:
        from database.repositories.reporting_repo import ReportingRepo

    return ReportingRepo(conn)


def _days_between(older_yyyy_mm_dd: str, asof_yyyy_mm_dd: str) -> int:
    from datetime import datetime

    try:
        d1 = datetime.strptime(older_yyyy_mm_dd, "%Y-%m-%d").date()
        d2 = datetime.strptime(asof_yyyy_mm_dd, "%Y-%m-%d").date()
        return (d2 - d1).days
    except Exception:
        return 0


def get_vendor_aging(
    conn: Connection,
    cutoff_date: str,
    *,
    max_rows: int = 1000,
    repo=None,
) -> VendorAgingReport:
    # ACC-RULE-108: Vendor aging buckets
    # Calculates vendor due amounts into 0-30, 31-60, 61-90, and 91+ day buckets.
    # Uses vendor headers, paid amounts, applied advances, and credit as of cutoff.
    # Supports accounts payable aging reports.
    repo = _reporting_repo(conn, repo)
    vendors = repo.get_all_vendors()
    vendor_ids = [int(v["vendor_id"]) for v in vendors]
    vendor_headers = repo.vendor_headers_as_of_batch(vendor_ids, cutoff_date)

    headers_by_vendor: dict[int, list] = {}
    for header in vendor_headers:
        headers_by_vendor.setdefault(int(header["vendor_id"]), []).append(header)

    vendor_credits = repo.vendor_credit_as_of_batch(vendor_ids, cutoff_date)
    rows: list[dict[str, Any]] = []

    for vendor in vendors:
        vendor_id = int(vendor["vendor_id"])
        total_due = 0.0
        b_0_30 = b_31_60 = b_61_90 = b_91_plus = 0.0

        for header in headers_by_vendor.get(vendor_id, []):
            total_amount = float(header["total_amount"] or 0.0)
            paid_amount = float(header["paid_amount"] or 0.0)
            advance = float(header["advance_payment_applied"] or 0.0)
            remaining = total_amount - paid_amount - advance
            remaining = remaining if remaining > _EPS else 0.0
            if remaining <= 0.0:
                continue

            days = _days_between(str(header["date"]), cutoff_date)
            total_due += remaining
            if days <= 30:
                b_0_30 += remaining
            elif days <= 60:
                b_31_60 += remaining
            elif days <= 90:
                b_61_90 += remaining
            else:
                b_91_plus += remaining

        if total_due == 0.0:
            continue

        rows.append(
            {
                "vendor_id": vendor_id,
                "name": str(vendor["name"] or vendor_id),
                "total_due": total_due,
                "b_0_30": b_0_30,
                "b_31_60": b_31_60,
                "b_61_90": b_61_90,
                "b_91_plus": b_91_plus,
                "available_credit": vendor_credits.get(vendor_id, 0.0),
            }
        )

    rows.sort(key=lambda row: row["name"].lower())
    return VendorAgingReport(cutoff_date, tuple(rows[:max_rows]))


def get_ap_summary(
    conn: Connection,
    cutoff_date: str | None = None,
    *,
    repo=None,
) -> APSummary:
    # ACC-RULE-109: AR/AP open balance summary
    # Sums positive customer receivables and vendor payables as of a cutoff.
    # Uses total, paid amount, and applied advance amounts from reporting headers.
    # Supports dashboard and reporting totals for open AR and AP.
    as_of = cutoff_date
    if as_of is None:
        row = conn.execute("SELECT DATE('now') AS today").fetchone()
        as_of = str(row["today"] if hasattr(row, "keys") else row[0])

    repo = _reporting_repo(conn, repo)
    ar_total = Decimal("0")
    customer_ids = [int(row["customer_id"]) for row in repo.get_all_customers()]
    for header in repo.customer_headers_as_of_batch(customer_ids, as_of):
        remaining = _decimal(header["total_amount"]) - _decimal(
            header["paid_amount"]
        ) - _decimal(header["advance_payment_applied"])
        if remaining > 0:
            ar_total += remaining

    ap_total = Decimal("0")
    for row in get_vendor_aging(conn, as_of, repo=repo).rows:
        ap_total += Decimal(str(row["total_due"]))

    return APSummary(as_of, ar_total, ap_total)


def get_payment_activity(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    date_basis: str = "posting",
    repo=None,
) -> PaymentActivityReport:
    # ACC-RULE-110: Payment activity date basis
    # Uses posting date or cleared date depending on requested basis.
    # Summarizes collections, disbursements, refunds, statuses, and detail rows.
    # Supports cash-basis and posting-basis payment activity reports.
    repo = _reporting_repo(conn, repo)
    date_from = start_date or "0001-01-01"
    date_to = end_date or "9999-12-31"
    date_expr = (
        "CASE WHEN p.clearing_state = 'cleared' "
        "AND p.cleared_date IS NOT NULL AND p.cleared_date != '' "
        "THEN p.cleared_date ELSE p.date END"
        if date_basis == "cash"
        else "p.date"
    )

    collections: list[dict[str, Any]] = []
    total_collections = Decimal("0")
    for row in repo.sale_collections_by_day(date_from, date_to):
        amount = _decimal(row["amount"])
        collections.append({"date": str(row["date"]), "amount": float(amount)})
        total_collections += amount

    disbursements: list[dict[str, Any]] = []
    total_disbursements = Decimal("0")
    for row in repo.purchase_disbursements_by_day(date_from, date_to):
        net = _decimal(row["net_outflow"])
        disbursements.append(
            {
                "date": str(row["date"]),
                "gross_outflow": float(_decimal(row["gross_outflow"])),
                "refunds_received": float(_decimal(row["refunds_received"])),
                "net_outflow": float(net),
            }
        )
        total_disbursements += net

    where_clause = f"WHERE {date_expr} >= ? AND {date_expr} <= ?"
    params = [date_from, date_to]
    summary_rows = tuple(
        {
            "status": str(row["status"]),
            "type": str(row["type"]),
            "count": int(row["count"]),
            "total_amount": float(row["total_amount"]),
        }
        for row in conn.execute(
            f"""
            SELECT p.clearing_state AS status, 'Collection' AS type,
                   COUNT(*) AS count,
                   COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
            FROM sale_payments p
            {where_clause}
            GROUP BY p.clearing_state
            UNION ALL
            SELECT p.clearing_state AS status, 'Disbursement' AS type,
                   COUNT(*) AS count,
                   COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
            FROM purchase_payments p
            {where_clause}
            GROUP BY p.clearing_state
            UNION ALL
            SELECT p.clearing_state AS status, 'Vendor Refund' AS type,
                   COUNT(*) AS count,
                   COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
            FROM purchase_refunds p
            {where_clause}
            GROUP BY p.clearing_state
            ORDER BY status, type
            """,
            params * 3,
        )
    )

    def _detail_rows(extra_where: str, order_by: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "date": str(row["date"]),
                "type": str(row["type"]),
                "amount": float(row["amount"]),
                "method": str(row["method"]),
                "status": str(row["status"]),
                "doc_id": str(row["doc_id"]),
                "notes": str(row["notes"]) if row["notes"] else "",
            }
            for row in conn.execute(
                f"""
                SELECT {date_expr} AS date, 'Collection' AS type, p.amount,
                       p.method, p.clearing_state AS status, p.sale_id AS doc_id,
                       p.notes
                FROM sale_payments p
                {where_clause} {extra_where}
                UNION ALL
                SELECT {date_expr} AS date, 'Disbursement' AS type, p.amount,
                       p.method, p.clearing_state AS status, p.purchase_id AS doc_id,
                       p.notes
                FROM purchase_payments p
                {where_clause} {extra_where}
                UNION ALL
                SELECT {date_expr} AS date, 'Vendor Refund' AS type, p.amount,
                       p.method, p.clearing_state AS status, p.purchase_id AS doc_id,
                       p.notes
                FROM purchase_refunds p
                {where_clause} {extra_where}
                {order_by}
                """,
                params * 3,
            )
        )

    return PaymentActivityReport(
        start_date,
        end_date,
        tuple(collections),
        tuple(disbursements),
        total_collections,
        total_disbursements,
        summary_rows,
        _detail_rows("AND p.clearing_state IN ('posted', 'pending')", "ORDER BY date DESC"),
        _detail_rows("", "ORDER BY date DESC, type"),
    )
