"""Current-rule wrappers for sale total and discount reads."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from typing import Any

from ..dto import (
    CustomerPaymentEffect,
    CustomerPaymentPayload,
    CustomerPaymentResult,
    CustomerRefundRow,
    QuotationFinancials,
    SaleFinancialSummary,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SaleReturnEffect,
    SaleReturnPayload,
    SaleReturnResult,
    SaleReturnTotals,
    SaleReturnValue,
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


def get_sale_return_totals(
    conn: Connection, sale_id: int | str
) -> SaleReturnTotals:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CAST(srs.returned_quantity AS REAL)), 0.0) AS qty,
               COALESCE(SUM(CAST(srs.return_value AS REAL)), 0.0) AS value,
               COALESCE(SUM(CAST(srs.cogs_reversal_value AS REAL)), 0.0) AS cogs_reversed
        FROM inventory_transactions it
        JOIN sale_return_snapshots srs ON srs.transaction_id = it.transaction_id
        WHERE it.reference_table = 'sales'
          AND it.reference_id = ?
          AND it.transaction_type = 'sale_return'
        """,
        (sale_id,),
    ).fetchone()
    return SaleReturnTotals(
        qty=Decimal(str(row["qty"] or 0)),
        value=Decimal(str(row["value"] or 0)),
        cogs_reversed=Decimal(str(row["cogs_reversed"] or 0)),
    )


def get_sale_return_values(
    conn: Connection, sale_id: int | str
) -> tuple[SaleReturnValue, ...]:
    rows = conn.execute(
        """
        SELECT srs.transaction_id, srs.item_id,
               CAST(srs.returned_quantity AS REAL) AS qty_returned,
               CAST(srs.unit_sale_price AS REAL) AS unit_sale_price,
               CAST(srs.unit_discount AS REAL) AS unit_discount,
               srs.return_date,
               CAST(srs.return_value AS REAL) AS return_value,
               CAST(srs.allocated_order_discount AS REAL) AS allocated_order_discount,
               'resolved' AS valuation_status
        FROM sale_return_snapshots srs
        WHERE srs.sale_id = ?
        ORDER BY srs.return_date, srs.transaction_id
        """,
        (sale_id,),
    ).fetchall()
    return tuple(
        SaleReturnValue(
            transaction_id=r["transaction_id"],
            item_id=r["item_id"],
            qty_returned=Decimal(str(r["qty_returned"] or 0)),
            unit_sale_price=Decimal(str(r["unit_sale_price"] or 0)),
            unit_discount=Decimal(str(r["unit_discount"] or 0)),
            return_date=r["return_date"],
            valuation_status=r["valuation_status"],
            return_value=Decimal(str(r["return_value"] or 0)),
            allocated_order_discount=Decimal(str(r["allocated_order_discount"] or 0)),
        )
        for r in rows
    )


def record_sale_return_event(
    conn: Connection, payload: SaleReturnPayload
) -> SaleReturnEffect:
    from .customer_rules import get_customer_receivable_summary

    fin = get_sale_financial_summary(conn, payload.sale_id)
    remaining_due_before = fin.outstanding

    prior_credit = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS total "
        "FROM customer_advances WHERE source_type = 'return_credit' AND source_id = ?",
        (payload.sale_id,),
    ).fetchone()["total"]

    net_total_before = fin.net_total
    advance_applied = fin.applied_credit
    net_advance = max(Decimal("0"), advance_applied - Decimal(str(prior_credit or 0)))

    prop_adv = Decimal("0")
    if net_total_before > Decimal("1e-9"):
        prop_adv = min(
            (payload.return_value / net_total_before) * advance_applied,
            net_advance,
        )

    settlement_due = max(Decimal("0"), payload.return_value - remaining_due_before)
    paid_before = fin.paid_amount
    max_cash = max(Decimal("0"), settlement_due - prop_adv)
    cash_cap = min(settlement_due, paid_before, max_cash)
    requested = payload.settlement_cash_refund
    cash_refund = min(requested, cash_cap)
    credit_amount = max(Decimal("0"), settlement_due - cash_refund)

    if settlement_due > 0:
        if cash_refund > 0:
            conn.execute(
                "INSERT INTO sale_payments (sale_id, date, amount, method, instrument_type, "
                "clearing_state, cleared_date, notes, created_by) "
                "VALUES (?, ?, ?, 'Cash', 'other', 'cleared', ?, ?, ?)",
                (payload.sale_id, payload.date, -float(cash_refund),
                 payload.date,
                 payload.notes or "[Return refund]",
                 payload.created_by),
            )
        if credit_amount > 0:
            conn.execute(
                "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, "
                "source_id, notes, created_by) VALUES (?, ?, ?, 'return_credit', ?, ?, ?)",
                (int(conn.execute(
                    "SELECT customer_id FROM sales WHERE sale_id = ?",
                    (payload.sale_id,),
                ).fetchone()["customer_id"]),
                 payload.date, float(credit_amount), payload.sale_id,
                 payload.notes or "[Return credit]",
                 payload.created_by),
            )

    return SaleReturnEffect(
        return_value=payload.return_value,
        allocated_order_discount=Decimal("0"),
        cogs_reversal_value=Decimal("0"),
        remaining_due_before_return=remaining_due_before,
        settlement_due=settlement_due,
        cash_refund_cap=cash_cap,
        cash_refund=cash_refund,
        credit_amount=credit_amount,
    )


def record_customer_payment_event(
    conn: Connection, payload: CustomerPaymentPayload
) -> CustomerPaymentResult:
    from datetime import date as dt_date

    cs = payload.clearing_state or "posted"
    cleared_date = payload.cleared_date
    if cs == "cleared" and not cleared_date:
        cleared_date = (payload.date or dt_date.today().isoformat())

    cur = conn.execute(
        """
        INSERT INTO sale_payments (sale_id, date, amount, method,
            bank_account_id, instrument_type, instrument_no,
            instrument_date, deposited_date, cleared_date,
            clearing_state, ref_no, notes, created_by,
            overpayment_converted, converted_to_credit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (payload.sale_id, payload.date, float(payload.amount), payload.method,
         payload.bank_account_id, payload.instrument_type, payload.instrument_no,
         payload.instrument_date, payload.deposited_date, cleared_date,
         cs, payload.ref_no, payload.notes, payload.created_by),
    )
    payment_id = int(cur.lastrowid)

    if cs == "cleared":
        _handle_overpayment(conn, payload.sale_id, payload.customer_id,
                            cleared_date, payment_id, str(payment_id))

    return CustomerPaymentResult(
        payment_id=payment_id,
        effect=CustomerPaymentEffect(
            sale_id=payload.sale_id,
            customer_id=payload.customer_id,
            amount=payload.amount,
            clearing_state=cs,
        ),
    )


def _handle_overpayment(
    conn: Connection, sale_id: str, customer_id: int,
    date: str | None, payment_id: int, source_id: str,
) -> None:
    info = conn.execute(
        "SELECT COALESCE(canonical_total_amount, 0.0) AS total, "
        "COALESCE(advance_payment_applied, 0.0) AS adv "
        "FROM sale_receivable_totals WHERE sale_id = ?",
        (sale_id,),
    ).fetchone()
    if not info:
        return
    total_amount = float(info["total"])
    current_advance = float(info["adv"]) if info["adv"] else 0.0
    total_owed = total_amount - current_advance

    total_cleared = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS t "
        "FROM sale_payments WHERE sale_id = ? AND clearing_state = 'cleared'",
        (sale_id,),
    ).fetchone()["t"]

    already_conv = conn.execute(
        "SELECT COALESCE(SUM(CAST(converted_to_credit AS REAL)), 0.0) AS t "
        "FROM sale_payments WHERE sale_id = ? AND payment_id != ?",
        (sale_id, payment_id),
    ).fetchone()["t"]

    excess = max(0.0, total_cleared - total_owed)
    excess_amt = max(0.0, excess - already_conv)
    if excess_amt > 1e-9:
        conn.execute(
            "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by) "
            "VALUES (?, ?, ?, 'deposit', ?, ?, ?)",
            (customer_id, date, excess_amt, source_id,
             f"Excess payment converted to credit on {sale_id}", None),
        )
        conn.execute(
            "UPDATE sale_payments SET overpayment_converted = 1, converted_to_credit = ? WHERE payment_id = ?",
            (excess_amt, payment_id),
        )


def update_customer_payment_state(
    conn: Connection,
    payment_id: int,
    *,
    clearing_state: str,
    cleared_date: str | None = None,
    notes: str | None = None,
) -> int:
    if clearing_state not in {"posted", "pending", "cleared", "bounced"}:
        raise ValueError(f"Invalid clearing_state: {clearing_state}")
    if clearing_state == "cleared" and not cleared_date:
        from datetime import date as dt_date
        cleared_date = dt_date.today().isoformat()

    orig = conn.execute(
        "SELECT sale_id, clearing_state, converted_to_credit FROM sale_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    if not orig:
        raise ValueError(f"Payment not found: {payment_id}")
    old = str(orig["clearing_state"])
    if old == clearing_state:
        return 1
    if old not in ("posted", "pending"):
        raise ValueError(f"Cannot transition from {old} to {clearing_state}")

    conn.execute(
        "UPDATE sale_payments SET clearing_state = ?, cleared_date = ?, notes = COALESCE(?, notes) "
        "WHERE payment_id = ? AND clearing_state = ?",
        (clearing_state, cleared_date, notes, payment_id, old),
    )

    # Overpayment reconciliation when transitioning TO cleared
    if clearing_state == "cleared" and old != "cleared":
        _reconcile_overpayment_on_clear(conn, orig["sale_id"], payment_id, cleared_date)

    return 1


def _reconcile_overpayment_on_clear(
    conn: Connection, sale_id: str, payment_id: int, cleared_date: str | None
) -> None:
    info = conn.execute(
        "SELECT COALESCE(canonical_total_amount, 0.0) AS total, "
        "COALESCE(advance_payment_applied, 0.0) AS adv, c.customer_id "
        "FROM sales s JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id "
        "JOIN customers c ON c.customer_id = s.customer_id WHERE s.sale_id = ?",
        (sale_id,),
    ).fetchone()
    if not info:
        return
    owed = float(info["total"]) - float(info["adv"])
    cleared = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS t "
        "FROM sale_payments WHERE sale_id = ? AND clearing_state = 'cleared'",
        (sale_id,),
    ).fetchone()["t"]
    already = conn.execute(
        "SELECT COALESCE(SUM(CAST(converted_to_credit AS REAL)), 0.0) AS t "
        "FROM sale_payments WHERE sale_id = ? AND payment_id != ?",
        (sale_id, payment_id),
    ).fetchone()["t"]
    excess = max(0.0, max(0.0, cleared - owed) - already)
    if excess > 1e-9:
        conn.execute(
            "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by) "
            "VALUES (?, ?, ?, 'deposit', ?, ?, ?)",
            (int(info["customer_id"]), cleared_date, excess, str(payment_id),
             f"Excess from cleared payment #{payment_id} on {sale_id}", None),
        )
        conn.execute(
            "UPDATE sale_payments SET overpayment_converted = 1, converted_to_credit = ? WHERE payment_id = ?",
            (excess, payment_id),
        )


def reopen_customer_payment_state(
    conn: Connection,
    payment_id: int,
    *,
    reason: str | None = None,
) -> int:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reversal reason is required")

    payment = conn.execute(
        "SELECT sale_id, clearing_state, converted_to_credit FROM sale_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    if not payment:
        raise ValueError(f"Payment not found: {payment_id}")
    old_state = str(payment["clearing_state"])
    if old_state not in {"cleared", "bounced"}:
        raise ValueError(f"Only cleared or bounced payments can be reopened; current state is {old_state}")

    # Reverse any overpayment-to-credit that was granted
    converted_amount = float(payment["converted_to_credit"] or 0.0)
    if converted_amount > 1e-9:
        sr = conn.execute(
            "SELECT customer_id FROM sales WHERE sale_id = ?", (payment["sale_id"],)
        ).fetchone()
        cid = int(sr["customer_id"])
        bal = float(conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS b FROM customer_advances WHERE customer_id = ?",
            (cid,),
        ).fetchone()["b"])
        if bal < converted_amount - 1e-9:
            raise ValueError(
                f"Cannot reopen: customer credit of {converted_amount:g} consumed. Balance: {bal:g}."
            )
        conn.execute(
            "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by) "
            "VALUES (?, CURRENT_DATE, ?, 'deposit', ?, ?, ?)",
            (cid, -converted_amount, str(payment_id),
             f"Reversal of excess credit from payment #{payment_id}", None),
        )
        conn.execute(
            "UPDATE sale_payments SET overpayment_converted = 0, converted_to_credit = 0 WHERE payment_id = ?",
            (payment_id,),
        )

    conn.execute(
        "UPDATE sale_payments SET clearing_state = 'pending', cleared_date = NULL "
        "WHERE payment_id = ? AND clearing_state = ?",
        (payment_id, old_state),
    )
    return 1


def get_sale_refunds(conn: Connection, sale_id: int | str) -> tuple[CustomerRefundRow, ...]:
    rows = conn.execute(
        "SELECT payment_id, sale_id, date, amount, method, clearing_state, notes "
        "FROM sale_payments WHERE sale_id = ? AND amount < 0 "
        "ORDER BY date ASC, payment_id ASC",
        (sale_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        res.append(
            CustomerRefundRow(
                payment_id=d["payment_id"], sale_id=d["sale_id"], date=d["date"],
                amount=Decimal(str(abs(d["amount"] or 0))),
                method=d["method"], clearing_state=d.get("clearing_state"),
                notes=d.get("notes"),
            )
        )
    return tuple(res)
