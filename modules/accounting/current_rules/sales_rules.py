"""Current-rule wrappers for sale total and discount reads."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from typing import Any

from ..dto import (
    QuotationFinancials,
    SaleFinancialSummary,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SalesDashboardMetrics,
    SaleTotalInputLine,
    SaleTotals,
)


def get_sale_totals(conn: Connection, sale_id: int | str) -> SaleTotals:
    row = conn.execute(
        """
        SELECT sale_id,
               order_discount,
               subtotal_before_order_discount,
               calculated_total_amount,
               returned_value,
               net_total_amount
          FROM sale_detailed_totals
         WHERE sale_id = ?
        """,
        (sale_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown sale_id: {sale_id}")
    return SaleTotals(
        sale_id=row["sale_id"],
        subtotal_before_order_discount=Decimal(str(row["subtotal_before_order_discount"])),
        order_discount=Decimal(str(row["order_discount"])),
        returned_value=Decimal(str(row["returned_value"])),
        net_total=Decimal(str(row["net_total_amount"])),
        stored_total=Decimal(str(row["calculated_total_amount"])),
    )


def preview_sale_total(
    items: tuple[SaleTotalInputLine, ...],
    order_discount: Decimal,
) -> SaleTotals:
    subtotal = Decimal("0")
    line_disc = Decimal("0")
    for item in items:
        subtotal += item.quantity * item.unit_price
        line_disc += item.quantity * item.item_discount
    net_subtotal = subtotal - line_disc
    total = max(Decimal("0"), net_subtotal - order_discount)
    return SaleTotals(
        sale_id=None,
        subtotal_before_order_discount=subtotal,
        order_discount=order_discount,
        returned_value=Decimal("0"),
        net_total=total,
        stored_total=total,
    )


def get_sale_financial_summary(
    conn: Connection, sale_id: int | str
) -> SaleFinancialSummary:
    row = conn.execute(
        """
        SELECT sdt.calculated_total_amount,
               sdt.returned_value,
               sdt.net_total_amount,
               srt.paid_amount,
               srt.advance_payment_applied,
               srt.remaining_due
          FROM sale_detailed_totals sdt
          JOIN sale_receivable_totals srt ON srt.sale_id = sdt.sale_id
         WHERE sdt.sale_id = ?
        """,
        (sale_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown sale_id: {sale_id}")
    gross = Decimal(str(row["calculated_total_amount"]))
    net_total = Decimal(str(row["net_total_amount"]))
    paid = Decimal(str(row["paid_amount"] or 0))
    advance = Decimal(str(row["advance_payment_applied"] or 0))
    returned = Decimal(str(row["returned_value"] or 0))
    remaining = Decimal(str(row["remaining_due"] or 0))
    return SaleFinancialSummary(
        sale_id=sale_id,
        gross_total_amount=gross,
        net_total=net_total,
        paid_amount=paid,
        applied_credit=advance,
        returned_value=returned,
        outstanding=remaining,
        total_amount=gross,
        is_fully_paid=remaining <= Decimal("1e-9"),
    )


def get_sale_invoice_financials(
    conn: Connection, sale_id: int | str
) -> SaleInvoiceFinancials:
    fin = get_sale_financial_summary(conn, sale_id)
    returns = conn.execute(
        """
        SELECT srs.return_date, p.name AS product_name, u.unit_name AS uom_name,
               CAST(srs.returned_quantity AS REAL) AS returned_quantity,
               CAST(srs.return_value AS REAL) AS return_value
        FROM sale_return_snapshots srs
        JOIN products p ON p.product_id = srs.product_id
        JOIN uoms u ON u.uom_id = srs.uom_id
        WHERE srs.sale_id = ?
        ORDER BY srs.return_date, srs.transaction_id
        """,
        (sale_id,),
    ).fetchall()

    credit_row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN source_type='return_credit'
                            THEN CAST(amount AS REAL) ELSE 0 END), 0.0) AS return_credit,
          COALESCE(SUM(CASE WHEN source_type='applied_to_sale'
                            THEN -CAST(amount AS REAL) ELSE 0 END), 0.0) AS applied_credit
        FROM customer_advances
        WHERE source_id = ? AND source_type IN ('return_credit', 'applied_to_sale')
        """,
        (sale_id,),
    ).fetchone()

    context: dict[str, Any] = {
        "returns": [dict(r) for r in returns],
        "return_credit": float(credit_row["return_credit"] or 0.0),
        "applied_credit": float(credit_row["applied_credit"] or float(fin.applied_credit)),
        "paid_amount": float(fin.paid_amount),
        "advance_payment_applied": float(fin.applied_credit),
        "remaining": float(fin.outstanding),
        "returned_value": float(fin.returned_value),
        "net_total": float(fin.net_total),
    }
    return SaleInvoiceFinancials(sale_id=sale_id, context=context)


def get_quotation_financials(
    conn: Connection, quotation_id: int | str
) -> QuotationFinancials:
    return QuotationFinancials(
        quotation_id=quotation_id, context={"id": quotation_id}
    )


def get_sales_dashboard_metrics(
    conn: Connection, date_from: str, date_to: str
) -> SalesDashboardMetrics:
    row = conn.execute(
        """
        WITH
        sales_cte AS (
          SELECT
            COALESCE(SUM(CAST(revenue AS REAL)), 0.0) AS total_sales,
            COALESCE(SUM(CAST(cogs AS REAL)), 0.0) AS total_cogs
          FROM sale_financial_events
          WHERE event_date >= ? AND event_date <= ?
        ),
        expenses_cte AS (
          SELECT COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS total_expenses
          FROM expenses e
          WHERE e.date >= ? AND e.date <= ?
        ),
        receipts AS (
          SELECT COALESCE(SUM(CAST(sp.amount AS REAL)), 0.0) AS receipts_cleared
          FROM sale_payments sp
          WHERE sp.clearing_state = 'cleared'
            AND sp.cleared_date >= ? AND sp.cleared_date <= ?
        ),
        payables AS (
          SELECT
            COALESCE((SELECT SUM(CAST(pp.amount AS REAL)) FROM purchase_payments pp
                      WHERE pp.clearing_state = 'cleared' AND pp.cleared_date >= ? AND pp.cleared_date <= ?), 0.0)
            - COALESCE((SELECT SUM(CAST(pr.amount AS REAL)) FROM purchase_refunds pr
                        WHERE pr.clearing_state = 'cleared' AND pr.cleared_date >= ? AND pr.cleared_date <= ?), 0.0)
            AS vendor_payments_cleared
        ),
        receivables AS (
          SELECT COALESCE(SUM(srt.remaining_due), 0.0) AS open_receivables
          FROM sales s
          JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
          WHERE s.doc_type = 'sale' AND srt.remaining_due > 0.0000001
        ),
        all_payables AS (
          SELECT MAX(0.0, COALESCE(SUM(CAST(p.total_amount AS REAL)
            - COALESCE(CAST(p.paid_amount AS REAL), 0.0)
            - COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)), 0.0)) AS open_payables
          FROM purchases p
        )
        SELECT sales_cte.total_sales, sales_cte.total_cogs, expenses_cte.total_expenses,
               receipts.receipts_cleared, payables.vendor_payments_cleared,
               receivables.open_receivables, all_payables.open_payables
        FROM sales_cte, expenses_cte, receipts, payables, receivables, all_payables
        """,
        (date_from, date_to, date_from, date_to, date_from, date_to,
         date_from, date_to, date_from, date_to),
    ).fetchone()
    # ponytail: empty result set is degenerate — the CROSS JOIN yields one row
    return SalesDashboardMetrics(
        as_of=date_to,
        total_sales=Decimal(str(row["total_sales"] or 0)),
        total_cogs=Decimal(str(row["total_cogs"] or 0)),
        total_expenses=Decimal(str(row["total_expenses"] or 0)),
        receipts_cleared=Decimal(str(row["receipts_cleared"] or 0)),
        vendor_payments_cleared=Decimal(str(row["vendor_payments_cleared"] or 0)),
        open_receivables=Decimal(str(row["open_receivables"] or 0)),
        open_payables=Decimal(str(row["open_payables"] or 0)),
    )


def get_sale_outstanding(conn: Connection, sale_id: int | str) -> SaleOutstanding:
    summary = get_sale_financial_summary(conn, sale_id)
    return SaleOutstanding(
        sale_id=int(sale_id) if isinstance(sale_id, int) else sale_id,
        outstanding=summary.outstanding,
    )


def _compute_payment_status(
    remaining_due: Decimal, paid_amount: Decimal, applied_credit: Decimal
) -> str:
    if remaining_due <= Decimal("1e-9"):
        return "paid"
    if paid_amount + applied_credit > Decimal("1e-9"):
        return "partial"
    return "unpaid"


def get_sale_payment_status(
    conn: Connection, sale_id: int | str
) -> SalePaymentStatus:
    row = conn.execute(
        """
        SELECT COALESCE(srt.remaining_due, 0.0) AS remaining_due,
               COALESCE(s.paid_amount, 0.0) AS paid_amount,
               COALESCE(s.advance_payment_applied, 0.0) AS advance_payment_applied
          FROM sales s
          LEFT JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
         WHERE s.sale_id = ?
        """,
        (sale_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown sale_id: {sale_id}")
    remaining = Decimal(str(row["remaining_due"] or 0))
    paid = Decimal(str(row["paid_amount"] or 0))
    advance = Decimal(str(row["advance_payment_applied"] or 0))
    status = _compute_payment_status(remaining, paid, advance)
    return SalePaymentStatus(
        sale_id=sale_id,
        status=status,
        paid_amount=paid,
        applied_credit=advance,
        remaining_due=remaining,
    )


def recalculate_sale_payment_status(
    conn: Connection, sale_id: int | str
) -> SalePaymentStatus:
    current = get_sale_payment_status(conn, sale_id)
    conn.execute(
        """
        UPDATE sales
           SET payment_status = ?
         WHERE sale_id = ? AND doc_type = 'sale'
        """,
        (current.status, sale_id),
    )
    return current


def get_sale_payment_history(
    conn: Connection, sale_id: int | str
) -> tuple[SalePaymentRow, ...]:
    rows = conn.execute(
        "SELECT * FROM sale_payments WHERE sale_id = ? ORDER BY date ASC, payment_id ASC",
        (sale_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        res.append(
            SalePaymentRow(
                payment_id=d["payment_id"],
                sale_id=d["sale_id"],
                date=d["date"],
                amount=Decimal(str(d["amount"] or 0)),
                method=d["method"],
                bank_account_id=d.get("bank_account_id"),
                instrument_type=d.get("instrument_type"),
                instrument_no=d.get("instrument_no"),
                instrument_date=d.get("instrument_date"),
                deposited_date=d.get("deposited_date"),
                cleared_date=d.get("cleared_date"),
                clearing_state=d.get("clearing_state"),
                ref_no=d.get("ref_no"),
                notes=d.get("notes"),
                created_by=d.get("created_by"),
                bank_account_label=d.get("bank_account_label"),
            )
        )
    return tuple(res)


def get_latest_sale_payment(
    conn: Connection, sale_id: int | str
) -> SalePaymentRow | None:
    row = conn.execute(
        "SELECT * FROM sale_payments WHERE sale_id = ? ORDER BY date DESC, payment_id DESC LIMIT 1",
        (sale_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    return SalePaymentRow(
        payment_id=d["payment_id"],
        sale_id=d["sale_id"],
        date=d["date"],
        amount=Decimal(str(d["amount"] or 0)),
        method=d["method"],
        bank_account_id=d.get("bank_account_id"),
        instrument_type=d.get("instrument_type"),
        instrument_no=d.get("instrument_no"),
        instrument_date=d.get("instrument_date"),
        deposited_date=d.get("deposited_date"),
        cleared_date=d.get("cleared_date"),
        clearing_state=d.get("clearing_state"),
        ref_no=d.get("ref_no"),
        notes=d.get("notes"),
        created_by=d.get("created_by"),
        bank_account_label=d.get("bank_account_label"),
    )
