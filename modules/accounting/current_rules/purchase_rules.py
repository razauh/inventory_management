"""Current purchase accounting behavior, preserved before cleanup."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    PurchaseOutstanding,
    PurchasePaymentRow,
    PurchasePaymentStatus,
    PurchasePaymentSummary,
    PurchaseReturnEffect,
    PurchaseReturnPreviewPayload,
    PurchaseReturnTotals,
    PurchaseReturnValue,
    PurchaseTotalInputLine,
    PurchaseTotals,
)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def preview_purchase_total(
    items: tuple[PurchaseTotalInputLine, ...],
    order_discount: Decimal,
) -> PurchaseTotals:
    subtotal = sum(
        line.quantity * (line.purchase_price - line.item_discount) for line in items
    )
    order_discount = max(Decimal("0"), order_discount)
    net_total = max(Decimal("0"), subtotal - order_discount)
    return PurchaseTotals(
        purchase_id=None,
        subtotal_before_order_discount=subtotal,
        order_discount=order_discount,
        returned_value=Decimal("0"),
        net_total=net_total,
    )


def preview_purchase_return_effect(
    payload: PurchaseReturnPreviewPayload,
) -> PurchaseReturnEffect:
    subtotal = sum(
        line.quantity * max(Decimal("0"), line.purchase_price - line.item_discount)
        for line in payload.lines
    )
    order_discount = max(Decimal("0"), payload.order_discount)
    if subtotal > Decimal("0"):
        order_discount = min(order_discount, subtotal)
        value_factor = (subtotal - order_discount) / subtotal
    else:
        value_factor = Decimal("0")
    line_values = tuple(
        max(
            Decimal("0"),
            line.return_qty
            * max(Decimal("0"), line.purchase_price - line.item_discount)
            * value_factor,
        )
        for line in payload.lines
    )
    return PurchaseReturnEffect(
        value_factor=value_factor,
        total_qty=sum((line.return_qty for line in payload.lines), Decimal("0")),
        total_value=sum(line_values, Decimal("0")),
        line_values=line_values,
    )


def get_purchase_return_values(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[PurchaseReturnValue, ...]:
    rows = conn.execute(
        """
        SELECT
          transaction_id,
          item_id,
          CAST(qty_returned  AS REAL) AS qty_returned,
          CAST(unit_buy_price AS REAL) AS unit_buy_price,
          CAST(unit_discount  AS REAL) AS unit_discount,
          return_date,
          valuation_status,
          CAST(return_value   AS REAL) AS return_value
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """,
        (purchase_id,),
    ).fetchall()
    return tuple(
        PurchaseReturnValue(
            transaction_id=int(row["transaction_id"]),
            item_id=row["item_id"],
            qty_returned=_decimal(row["qty_returned"]),
            unit_buy_price=_decimal(row["unit_buy_price"]),
            unit_discount=_decimal(row["unit_discount"]),
            return_date=row["return_date"],
            valuation_status=row["valuation_status"],
            return_value=_decimal(row["return_value"]),
        )
        for row in rows
    )


def get_purchase_return_totals(
    conn: Connection,
    purchase_id: int | str,
) -> PurchaseReturnTotals:
    values = get_purchase_return_values(conn, purchase_id)
    return PurchaseReturnTotals(
        qty=sum((value.qty_returned for value in values), Decimal("0")),
        value=sum((value.return_value for value in values), Decimal("0")),
    )


def get_purchase_totals(conn: Connection, purchase_id: int | str) -> PurchaseTotals:
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          CAST(p.total_amount AS REAL) AS stored_total,
          COALESCE(CAST(pdt.order_discount AS REAL), CAST(p.order_discount AS REAL), 0.0)
            AS order_discount,
          COALESCE(CAST(pdt.subtotal_before_order_discount AS REAL), CAST(p.total_amount AS REAL), 0.0)
            AS subtotal_before_order_discount,
          COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL), 0.0)
            AS net_total,
          COALESCE((
            SELECT SUM(CAST(prv.return_value AS REAL))
            FROM purchase_return_valuations prv
            WHERE prv.purchase_id = p.purchase_id
          ), 0.0) AS returned_value
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")
    return PurchaseTotals(
        purchase_id=row["purchase_id"],
        subtotal_before_order_discount=_decimal(row["subtotal_before_order_discount"]),
        order_discount=_decimal(row["order_discount"]),
        returned_value=_decimal(row["returned_value"]),
        net_total=_decimal(row["net_total"]),
        stored_total=_decimal(row["stored_total"]),
    )


def get_purchase_outstanding(
    conn: Connection,
    purchase_id: int | str,
    *,
    clamp: bool = False,
) -> PurchaseOutstanding:
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
          COALESCE(p.paid_amount, 0.0) AS paid_amount,
          COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")

    outstanding = (
        _decimal(row["total_calc"])
        - _decimal(row["paid_amount"])
        - _decimal(row["advance_payment_applied"])
    )
    if clamp:
        outstanding = max(Decimal("0"), outstanding)
    return PurchaseOutstanding(purchase_id=row["purchase_id"], outstanding=outstanding)


def get_purchase_payment_status(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentStatus:
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
          COALESCE((
            SELECT SUM(CAST(amount AS REAL))
            FROM purchase_payments
            WHERE purchase_id = p.purchase_id
              AND COALESCE(clearing_state, 'posted') = 'cleared'
          ), 0.0) AS cleared_paid,
          COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")

    paid = max(Decimal("0"), _decimal(row["cleared_paid"]))
    applied_credit = _decimal(row["advance_payment_applied"])
    remaining_due = _decimal(row["total_calc"]) - paid - applied_credit
    if remaining_due <= Decimal("0.000000001"):
        status = "paid"
    elif paid > Decimal("0.000000001") or applied_credit > Decimal("0.000000001"):
        status = "partial"
    else:
        status = "unpaid"
    return PurchasePaymentStatus(
        purchase_id=row["purchase_id"],
        status=status,
        paid_amount=paid,
        applied_credit=applied_credit,
        remaining_due=remaining_due,
    )


def recalculate_purchase_payment_status(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentStatus:
    status = get_purchase_payment_status(conn, purchase_id)
    conn.execute(
        "UPDATE purchases SET paid_amount = ?, payment_status = ? WHERE purchase_id = ?",
        (float(status.paid_amount), status.status, purchase_id),
    )
    return status


def _payment_row(row: object) -> PurchasePaymentRow:
    return PurchasePaymentRow(
        payment_id=int(row["payment_id"]),
        purchase_id=row["purchase_id"],
        date=row["date"],
        amount=_decimal(row["amount"]),
        method=row["method"],
        bank_account_id=row["bank_account_id"],
        vendor_bank_account_id=row["vendor_bank_account_id"],
        instrument_type=row["instrument_type"],
        instrument_no=row["instrument_no"],
        instrument_date=row["instrument_date"],
        deposited_date=row["deposited_date"],
        cleared_date=row["cleared_date"],
        clearing_state=row["clearing_state"],
        ref_no=row["ref_no"],
        notes=row["notes"],
        created_by=row["created_by"],
        bank_account_label=row["bank_account_label"],
        vendor_bank_account_label=row["vendor_bank_account_label"],
    )


def get_purchase_payment_history(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[PurchasePaymentRow, ...]:
    rows = conn.execute(
        """
        SELECT
          pp.payment_id,
          pp.purchase_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.instrument_type,
          pp.instrument_no,
          pp.instrument_date,
          pp.deposited_date,
          pp.cleared_date,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.created_by,
          ca.label AS bank_account_label,
          va.label AS vendor_bank_account_label
        FROM purchase_payments pp
        LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
        LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
        WHERE pp.purchase_id = ?
        ORDER BY DATE(pp.date) ASC, pp.payment_id ASC
        """,
        (purchase_id,),
    ).fetchall()
    return tuple(_payment_row(row) for row in rows)


def get_purchase_payment_summary(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentSummary:
    status = get_purchase_payment_status(conn, purchase_id)
    latest = conn.execute(
        """
        SELECT
          pp.payment_id,
          pp.purchase_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.instrument_type,
          pp.instrument_no,
          pp.instrument_date,
          pp.deposited_date,
          pp.cleared_date,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.created_by,
          ca.label AS bank_account_label,
          va.label AS vendor_bank_account_label
        FROM purchase_payments pp
        LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
        LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
        WHERE pp.purchase_id = ?
        ORDER BY DATE(pp.date) DESC, pp.payment_id DESC
        LIMIT 1
        """,
        (purchase_id,),
    ).fetchone()
    overpayment = conn.execute(
        """
        SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS overpay
        FROM vendor_advances
        WHERE source_type='deposit'
          AND source_id=?
          AND notes LIKE 'Excess payment converted to vendor credit%'
        """,
        (purchase_id,),
    ).fetchone()
    return PurchasePaymentSummary(
        purchase_id=status.purchase_id,
        latest_payment=_payment_row(latest) if latest else None,
        paid_amount=status.paid_amount,
        applied_credit=status.applied_credit,
        remaining_due=status.remaining_due,
        status=status.status,
        overpayment_credited=_decimal(overpayment["overpay"] if overpayment else 0),
    )
