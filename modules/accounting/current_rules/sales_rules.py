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
    QuotationConversionPayload,
    QuotationConversionResult,
    QuotationFinancials,
    SaleFinancialSummary,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SaleCogsSummary,
    SaleReturnEffect,
    SaleReturnPayload,
    SaleReturnResult,
    SaleReturnTotals,
    SaleReturnValue,
    SalesProfitSummary,
    SalesDashboardMetrics,
    SaleTotalInputLine,
    SaleTotals,
    SaleReturnPreviewPayload,
    SaleReturnPreviewLine,
)


def get_sale_totals(conn: Connection, sale_id: int | str) -> SaleTotals:
    # ACC-RULE-032: Stored sale totals read
    # Reads sale subtotal, order discount, returned value, and net total.
    # Uses sale_detailed_totals as the accounting source.
    # Supports sale screens and invoice financial context.
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
    # ACC-RULE-033: Sale total preview
    # Calculates sale subtotal, line discounts, order discount, and net total.
    # Uses sale input lines without database writes.
    # Supports sale entry previews before a sale is saved.
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


def preview_sale_return_value(
    payload: SaleReturnPreviewPayload,
) -> Decimal:
    # ACC-RULE-034: Sale return value preview
    # Allocates order discount proportionally across returned sale lines.
    # Calculates return value from quantity, unit price, and item discount.
    # Supports return previews before settlement records are written.
    subtotal = sum(
        line.quantity * max(Decimal("0"), line.unit_price - line.item_discount)
        for line in payload.lines
    )
    order_discount = max(Decimal("0"), payload.order_discount)
    if subtotal > Decimal("0"):
        order_discount = min(order_discount, subtotal)
        value_factor = (subtotal - order_discount) / subtotal
    else:
        value_factor = Decimal("0")

    return sum(
        max(
            Decimal("0"),
            line.return_qty
            * max(Decimal("0"), line.unit_price - line.item_discount)
            * value_factor,
        )
        for line in payload.lines
    )



def get_sale_financial_summary(
    conn: Connection, sale_id: int | str
) -> SaleFinancialSummary:
    # ACC-RULE-035: Sale financial position
    # Reads gross total, net total, paid amount, credits, returns, and due.
    # Uses sale detailed totals and receivable totals.
    # Supports receivable decisions and invoice/accounting displays.
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
    # ACC-RULE-036: Sale invoice financial context
    # Builds invoice totals, return credits, applied credits, and payments.
    # Uses sale header, items, receivable totals, returns, and payment rows.
    # Supports invoice display without changing stored accounting state.
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

    # Fetch sale header and customer details
    header_row = conn.execute(
        """
        SELECT s.sale_id, s.customer_id, s.date, s.total_amount, s.order_discount, s.payment_status,
               s.paid_amount, s.advance_payment_applied, s.notes, s.created_by, s.doc_type,
               c.name AS customer_name, c.contact_info AS customer_contact_info, c.address AS customer_address
        FROM sales s
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sale_id = ?
        """,
        (sale_id,),
    ).fetchone()

    doc = {}
    customer = {}
    if header_row:
        doc = dict(header_row)
        doc["id"] = doc.get("sale_id", "")
        doc["payment_status"] = doc.get("payment_status", "Unpaid")
        customer = {
            "name": doc.get("customer_name") or "",
            "contact_info": doc.get("customer_contact_info") or "",
            "address": doc.get("customer_address") or ""
        }

    # Fetch items
    items_rows = conn.execute(
        """
        SELECT si.item_id, si.sale_id, si.product_id, si.quantity, si.uom_id, si.unit_price, si.item_discount,
               p.name AS product_name, u.unit_name
        FROM sale_items si
        LEFT JOIN products p ON p.product_id = si.product_id
        LEFT JOIN uoms u ON u.uom_id = si.uom_id
        WHERE si.sale_id = ?
        """,
        (sale_id,),
    ).fetchall()

    items = []
    for row in items_rows:
        item_dict = dict(row)
        quantity = float(item_dict.get("quantity") or 0.0)
        unit_price = float(item_dict.get("unit_price") or 0.0)
        item_discount = float(item_dict.get("item_discount") or 0.0)
        line_total = (quantity * unit_price) - (quantity * item_discount)
        item_dict["line_total"] = line_total
        item_dict["idx"] = len(items) + 1
        item_dict["uom_name"] = item_dict.get("unit_name") or "N/A"
        items.append(item_dict)

    # Fetch totals
    sale_totals = get_sale_totals(conn, sale_id)
    line_discount_total = float(
        sale_totals.subtotal_before_order_discount
        - sale_totals.stored_total
        - sale_totals.order_discount
    )
    totals = {
        "subtotal_before_order_discount": float(sale_totals.subtotal_before_order_discount),
        "line_discount_total": line_discount_total,
        "order_discount": float(sale_totals.order_discount),
        "total": float(sale_totals.stored_total or sale_totals.net_total),
        "returned_value": float(fin.returned_value),
        "net_total": float(fin.net_total),
    }

    # Fetch payments
    bank_labels = {}
    try:
        cur = conn.execute(
            "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1"
        )
        bank_labels = {int(r["account_id"]): str(r["label"]) for r in cur.fetchall()}
    except Exception:
        pass

    raw_payments = conn.execute(
        """
        SELECT payment_id, sale_id, date, amount, method, bank_account_id, instrument_type, instrument_no, clearing_state
        FROM sale_payments
        WHERE sale_id = ?
        """,
        (sale_id,),
    ).fetchall()

    payments = []
    for row in raw_payments:
        d = dict(row)
        amount = float(d.get("amount") or 0.0)
        d["amount"] = amount
        state = str(d.get("clearing_state") or "posted").lower()
        if amount < 0:
            d["entry_type"] = "Payment Refund"
        elif state == "pending":
            d["entry_type"] = "Pending Payment"
        elif state == "bounced":
            d["entry_type"] = "Bounced Payment"
        else:
            d["entry_type"] = "Payment"
        bid = d.get("bank_account_id")
        if bid is not None:
            d["bank_account_label"] = bank_labels.get(int(bid), "")
        else:
            d["bank_account_label"] = ""
        payments.append(d)

    context: dict[str, Any] = {
        "returns": [dict(r) for r in returns],
        "return_credit": float(credit_row["return_credit"] or 0.0),
        "applied_credit": float(credit_row["applied_credit"] or float(fin.applied_credit)),
        "paid_amount": float(fin.paid_amount),
        "advance_payment_applied": float(fin.applied_credit),
        "remaining": float(fin.outstanding),
        "returned_value": float(fin.returned_value),
        "net_total": float(fin.net_total),
        "doc": doc,
        "customer": customer,
        "items": items,
        "totals": totals,
        "payments": payments,
        "initial_payment": payments[-1] if payments else None,
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
    # ACC-RULE-037: Sales dashboard accounting metrics
    # Sums revenue, COGS, expenses, cleared receipts, payments, AR, and AP.
    # Uses financial event, payment, refund, receivable, and payable data.
    # Supports dashboard totals for a selected date range.
    from .expense_rules import get_dashboard_expense_total

    total_expenses = float(get_dashboard_expense_total(conn, date_from, date_to))
    has_purchase_detailed_totals = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = 'purchase_detailed_totals'
          AND type IN ('table', 'view')
        """
    ).fetchone() is not None
    purchase_total_expr = (
        "COALESCE(pdt.calculated_total_amount, p.total_amount)"
        if has_purchase_detailed_totals
        else "p.total_amount"
    )
    purchase_totals_join = (
        "LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id"
        if has_purchase_detailed_totals
        else ""
    )
    row = conn.execute(
        f"""
        WITH
        sales_cte AS (
          SELECT
            COALESCE(SUM(CAST(revenue AS REAL)), 0.0) AS total_sales,
            COALESCE(SUM(CAST(cogs AS REAL)), 0.0) AS total_cogs
          FROM sale_financial_events
          WHERE event_date >= ? AND event_date <= ?
        ),
        expenses_cte AS (
          SELECT ? AS total_expenses
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
          SELECT COALESCE(SUM(remaining), 0.0) AS open_payables
          FROM (
            SELECT
              MAX(0.0,
                {purchase_total_expr}
                - COALESCE(CAST(p.paid_amount AS REAL), 0.0)
                - COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
              ) AS remaining
            FROM purchases p
            {purchase_totals_join}
          )
          WHERE remaining > 0.0000001
        )
        SELECT sales_cte.total_sales, sales_cte.total_cogs, expenses_cte.total_expenses,
               receipts.receipts_cleared, payables.vendor_payments_cleared,
               receivables.open_receivables, all_payables.open_payables
        FROM sales_cte, expenses_cte, receipts, payables, receivables, all_payables
        """,
        (date_from, date_to, total_expenses, date_from, date_to,
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
    # ACC-RULE-038: Sale outstanding balance
    # Returns the current sale receivable amount still due.
    # Uses sale financial summary outstanding state.
    # Supports collection and customer balance workflows.
    summary = get_sale_financial_summary(conn, sale_id)
    return SaleOutstanding(
        sale_id=int(sale_id) if isinstance(sale_id, int) else sale_id,
        outstanding=summary.outstanding,
    )


def _compute_payment_status(
    remaining_due: Decimal, paid_amount: Decimal, applied_credit: Decimal
) -> str:
    # ACC-RULE-039: Sale payment status classifier
    # Classifies sale payment state from remaining due, payments, and credit.
    # Uses receivable balance and applied customer credit amounts.
    # Supports paid, partial, and unpaid sale status decisions.
    if remaining_due <= Decimal("1e-9"):
        return "paid"
    if paid_amount + applied_credit > Decimal("1e-9"):
        return "partial"
    return "unpaid"


def get_sale_payment_status(
    conn: Connection, sale_id: int | str
) -> SalePaymentStatus:
    # ACC-RULE-039: Sale payment status classifier
    # Reads sale receivable state and applies the shared status thresholds.
    # Uses remaining due, paid amount, and applied customer credit.
    # Supports sale payment status display.
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
    # ACC-RULE-040: Persist sale payment status
    # Recomputes sale payment status and writes it to sale headers.
    # Uses the sale payment status rule as the source of truth.
    # Supports payment, credit, and return flows that alter receivable state.
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
    # ACC-RULE-041: Sale return totals
    # Sums returned quantity, return value, and reversed COGS for a sale.
    # Uses sale return snapshots tied to inventory return transactions.
    # Supports sale return summaries and financial displays.
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
    # ACC-RULE-042: Sale return valuation rows
    # Reads stored valuation snapshots for each sale return transaction.
    # Uses returned quantity, sale price, discounts, and allocated order discount.
    # Supports return reports and settlement calculations.
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
    # ACC-RULE-043: Sale return settlement
    # Calculates return settlement due after remaining receivable.
    # Splits settlement into customer cash refund and customer credit.
    # Supports sale returns after payments or credit application.
    from .customer_rules import get_customer_receivable_summary

    fin = get_sale_financial_summary(conn, payload.sale_id)
    pre_net_total = fin.net_total + payload.return_value
    if pre_net_total > fin.net_total:
        row = conn.execute(
            "SELECT total_amount FROM sales WHERE sale_id = ?",
            (payload.sale_id,),
        ).fetchone()
        if row and row["total_amount"] is not None:
            sale_total = Decimal(str(row["total_amount"]))
            if sale_total >= fin.net_total:
                pre_net_total = sale_total
    remaining_due_before = max(
        Decimal("0"),
        pre_net_total - fin.paid_amount - fin.applied_credit,
    )

    prior_credit = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS total "
        "FROM customer_advances WHERE source_type = 'return_credit' AND source_id = ?",
        (payload.sale_id,),
    ).fetchone()["total"]

    advance_applied = fin.applied_credit
    net_advance = max(Decimal("0"), advance_applied - Decimal(str(prior_credit or 0)))

    prop_adv = Decimal("0")
    if pre_net_total > Decimal("1e-9"):
        prop_adv = min(
            (payload.return_value / pre_net_total) * advance_applied,
            net_advance,
        )

    paid_before = fin.paid_amount
    settlement_due = max(Decimal("0"), payload.return_value - remaining_due_before)
    coverage_before = paid_before + advance_applied
    if (
        payload.settlement_cash_refund <= Decimal("0")
        and coverage_before < pre_net_total
    ):
        settlement_due = Decimal("0")
    max_cash = max(Decimal("0"), settlement_due - prop_adv)
    cash_cap = min(settlement_due, paid_before, max_cash)
    requested = payload.settlement_cash_refund
    cash_refund = min(requested, cash_cap)
    credit_amount = max(Decimal("0"), settlement_due - cash_refund)

    if settlement_due > 0:
        if cash_refund > 0:
            # ACC-RULE-044: Sale return cash refund posting
            # Records cash refund as a negative cleared sale payment.
            # Validates refund method and bank metadata before writing.
            # Protects customer refund cash state for returned sales.
            refund_method = payload.refund_method or "Cash"
            refund_instr_type = payload.refund_instrument_type
            if refund_instr_type is None and refund_method == "Cash":
                refund_instr_type = "other"

            # Validate using validate_customer_payment_metadata
            from ..validators import validate_customer_payment_metadata
            from ..dto import CustomerPaymentMetadata

            cust_row = conn.execute("SELECT customer_id FROM sales WHERE sale_id = ?", (payload.sale_id,)).fetchone()
            customer_id = cust_row["customer_id"] if cust_row else 0

            meta = CustomerPaymentMetadata(
                customer_id=customer_id,
                method=refund_method,
                bank_account_id=payload.refund_bank_account_id,
                instrument_type=refund_instr_type,
                instrument_no=payload.refund_instrument_no,
                clearing_state="cleared",
                require_method_details=True,
            )
            validate_customer_payment_metadata(conn, meta)

            conn.execute(
                "INSERT INTO sale_payments (sale_id, date, amount, method, bank_account_id, "
                "instrument_type, instrument_no, clearing_state, cleared_date, notes, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'cleared', ?, ?, ?)",
                (payload.sale_id, payload.date, -float(cash_refund),
                 refund_method, payload.refund_bank_account_id,
                 refund_instr_type, payload.refund_instrument_no,
                 payload.date,
                 payload.notes or "[Return refund]",
                 payload.created_by),
            )
        if credit_amount > 0:
            # ACC-RULE-045: Sale return credit posting
            # Records remaining settlement as customer return credit.
            # Uses customer_advances with source_type return_credit.
            # Supports later use of return value against sale receivables.
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
    # ACC-RULE-046: Customer payment posting
    # Records sale payment cash state with method and clearing metadata.
    # Defaults cleared date when a payment is posted as cleared.
    # Supports customer collections and later overpayment conversion.
    from datetime import date as dt_date

    cs = payload.clearing_state or "posted"
    cleared_date = payload.cleared_date
    if cs == "cleared" and not cleared_date:
        cleared_date = (payload.date or dt_date.today().isoformat())
    payment_date = payload.date or cleared_date or dt_date.today().isoformat()

    cur = conn.execute(
        """
        INSERT INTO sale_payments (sale_id, date, amount, method,
            bank_account_id, instrument_type, instrument_no,
            instrument_date, deposited_date, cleared_date,
            clearing_state, ref_no, notes, created_by,
            overpayment_converted, converted_to_credit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (payload.sale_id, payment_date, float(payload.amount), payload.method,
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
    # ACC-RULE-047: Customer overpayment conversion
    # Converts cleared payment excess into customer deposit credit.
    # Uses total owed, current applied credit, cleared payments, and prior conversions.
    # Protects receivables from showing negative due after overpayment.
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
    # ACC-RULE-048: Customer payment clearing transition
    # Allows payment state changes only from posted or pending states.
    # Updates clearing state/date and reconciles overpayment when cleared.
    # Protects customer payment lifecycle from invalid state jumps.
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
        raise ValueError(
            f"Invalid payment clearing transition: cannot transition from {old} to {clearing_state}"
        )

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
    # ACC-RULE-047: Customer overpayment conversion
    # Converts excess created by clearing an existing payment into credit.
    # Uses total owed, cleared payments, applied credit, and prior conversions.
    # Protects receivables from showing negative due after delayed clearing.
    info = conn.execute(
        "SELECT COALESCE(canonical_total_amount, 0.0) AS total, "
        "COALESCE(srt.advance_payment_applied, 0.0) AS adv, c.customer_id "
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
    # ACC-RULE-049: Customer payment reopen reversal
    # Reopens only cleared or bounced payments and requires a reason.
    # Reverses unconsumed overpayment credit before resetting to pending.
    # Protects customer credit balances when payment state is undone.
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
                f"Cannot reopen payment: converted credit has already been consumed. Balance: {bal:g}."
            )
        conn.execute("SAVEPOINT reopen_customer_payment_credit")
        try:
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
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT reopen_customer_payment_credit")
            conn.execute("RELEASE SAVEPOINT reopen_customer_payment_credit")
            raise
        conn.execute("RELEASE SAVEPOINT reopen_customer_payment_credit")

    conn.execute(
        "UPDATE sale_payments SET clearing_state = 'pending', cleared_date = NULL "
        "WHERE payment_id = ? AND clearing_state = ?",
        (payment_id, old_state),
    )
    return 1


def get_sale_refunds(conn: Connection, sale_id: int | str) -> tuple[CustomerRefundRow, ...]:
    # ACC-RULE-050: Sale refund rows
    # Reads negative sale payments as customer refund amounts.
    # Uses absolute value for refund display while preserving payment sign in storage.
    # Supports customer refund history on sale details.
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


def get_sale_cogs(conn: Connection, sale_id: int | str) -> SaleCogsSummary:
    # ACC-RULE-051: Sale COGS total
    # Sums item cost of goods sold for a sale.
    # Uses sale_item_cogs valuation data.
    # Supports profit and gross margin reporting.
    row = conn.execute(
        "SELECT COALESCE(SUM(CAST(cogs AS REAL)), 0.0) AS total "
        "FROM sale_item_cogs WHERE sale_id = ?",
        (sale_id,),
    ).fetchone()
    return SaleCogsSummary(
        sale_id=sale_id,
        cogs_total=Decimal(str(row["total"] or 0)),
    )


def get_sales_profit_summary(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> SalesProfitSummary:
    # ACC-RULE-052: Sales gross profit
    # Sums revenue and COGS, then calculates gross profit.
    # Uses sale_financial_events with optional date filters.
    # Supports profit reporting for sale activity.
    where = ""
    params: list[object] = []
    if start_date is not None:
        where += " AND event_date >= ?"
        params.append(start_date)
    if end_date is not None:
        where += " AND event_date <= ?"
        params.append(end_date)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CAST(revenue AS REAL)), 0.0) AS rev,
               COALESCE(SUM(CAST(cogs AS REAL)), 0.0) AS cogs
        FROM sale_financial_events WHERE 1=1 {where}
        """,
        params,
    ).fetchone()
    rev = Decimal(str(row["rev"] or 0))
    cogs = Decimal(str(row["cogs"] or 0))
    return SalesProfitSummary(
        total_revenue=rev,
        total_cogs=cogs,
        gross_profit=rev - cogs,
    )


def validate_quotation_conversion(conn: Connection, quotation_id: int | str) -> None:
    # ACC-RULE-053: Quotation conversion eligibility
    # Allows conversion only for quotations in draft or sent status.
    # Uses quotation header status before accepting it as a sale.
    # Protects sales state from converting closed or invalid quotations.
    row = conn.execute(
        "SELECT quotation_status FROM sales WHERE sale_id = ? AND doc_type = 'quotation'",
        (quotation_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Quotation not found: {quotation_id}")
    if row["quotation_status"] not in ("draft", "sent"):
        raise ValueError(
            f"Quotation {quotation_id} has status '{row['quotation_status']}' and cannot be converted."
        )


def record_quotation_conversion_event(
    conn: Connection, payload: QuotationConversionPayload
) -> QuotationConversionResult:
    # ACC-RULE-054: Quotation conversion posting
    # Marks a convertible quotation as accepted.
    # Uses the quotation sale row and returns sale/quotation identifiers.
    # Supports turning approved quotations into sales workflow state.
    validate_quotation_conversion(conn, payload.quotation_id)
    conn.execute(
        "UPDATE sales SET quotation_status = 'accepted' WHERE sale_id = ? AND doc_type = 'quotation'",
        (payload.quotation_id,),
    )
    return QuotationConversionResult(
        sale_id=payload.new_sale_id or payload.quotation_id,
        quotation_id=payload.quotation_id,
    )
