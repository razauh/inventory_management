"""Current purchase accounting behavior, preserved before cleanup."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import PurchaseTotalInputLine, PurchaseTotals


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
