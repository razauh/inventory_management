"""Current purchase accounting behavior, preserved before cleanup."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    PurchaseOutstanding,
    PurchasePaymentStatus,
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
