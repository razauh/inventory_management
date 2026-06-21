"""Future home for extracted vendor accounting behavior.

These rules will mirror current code first. They are not assumed correct.
"""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import VendorBalance, VendorOpenPurchase, VendorPurchaseTotals


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _row_value(row: object, key: str, index: int) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (TypeError, KeyError, IndexError):
        return row[index]  # type: ignore[index]


def _row_dict(row: object, keys: tuple[str, ...]) -> dict:
    if hasattr(row, "keys"):
        return dict(row)  # type: ignore[arg-type]
    return {key: row[index] for index, key in enumerate(keys)}  # type: ignore[index]


def get_vendor_advance_balance(conn: Connection, vendor_id: int) -> VendorBalance:
    row = conn.execute(
        "SELECT balance FROM v_vendor_advance_balance WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    balance = _decimal(_row_value(row, "balance", 0) if row else 0)
    return VendorBalance(vendor_id=int(vendor_id), balance=balance)


def get_vendor_advance_balances(
    conn: Connection,
    vendor_ids: tuple[int, ...],
) -> dict[int, VendorBalance]:
    ids = tuple(int(vendor_id) for vendor_id in vendor_ids if vendor_id is not None)
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT v.vendor_id, COALESCE(b.balance, 0.0) AS balance
        FROM vendors v
        LEFT JOIN v_vendor_advance_balance b ON b.vendor_id = v.vendor_id
        WHERE v.vendor_id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {
        int(_row_value(row, "vendor_id", 0)): VendorBalance(
            vendor_id=int(_row_value(row, "vendor_id", 0)),
            balance=_decimal(_row_value(row, "balance", 1)),
        )
        for row in rows
    }


def list_vendor_purchases(
    conn: Connection,
    vendor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[dict, ...]:
    sql = [
        """
        SELECT
          p.purchase_id,
          p.date,
          CAST(p.total_amount AS REAL) AS total_amount,
          CAST(COALESCE(pdt.calculated_total_amount, p.total_amount) AS REAL) AS net_total_amount
        """,
        "FROM purchases p",
        "LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id",
        "WHERE p.vendor_id = ?",
    ]
    params: list[object] = [vendor_id]
    if date_from:
        sql.append("AND DATE(p.date) >= DATE(?)")
        params.append(date_from)
    if date_to:
        sql.append("AND DATE(p.date) <= DATE(?)")
        params.append(date_to)
    sql.append("ORDER BY DATE(p.date) ASC, p.purchase_id ASC")

    rows = conn.execute("\n".join(sql), params).fetchall()
    keys = ("purchase_id", "date", "total_amount", "net_total_amount")
    return tuple(_row_dict(row, keys) for row in rows)


def get_vendor_purchase_totals(
    conn: Connection,
    vendor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> VendorPurchaseTotals:
    row = conn.execute(
        "\n".join(
            [
                """
                SELECT
                  COALESCE(SUM(CAST(p.total_amount AS REAL)), 0.0)           AS purchases_total,
                  COALESCE(SUM(CAST(p.paid_amount AS REAL)), 0.0)             AS paid_total,
                  COALESCE(SUM(CAST(p.advance_payment_applied AS REAL)), 0.0) AS advance_applied_total
                FROM purchases p
                WHERE p.vendor_id = ?
                """,
                "AND DATE(p.date) >= DATE(?)" if date_from else "",
                "AND DATE(p.date) <= DATE(?)" if date_to else "",
            ]
        ),
        (
            [vendor_id]
            + ([date_from] if date_from else [])
            + ([date_to] if date_to else [])
        ),
    ).fetchone()
    return VendorPurchaseTotals(
        vendor_id=int(vendor_id),
        purchases_total=_decimal(_row_value(row, "purchases_total", 0)),
        paid_total=_decimal(_row_value(row, "paid_total", 1)),
        advance_applied_total=_decimal(_row_value(row, "advance_applied_total", 2)),
    )


def get_vendor_open_purchases(
    conn: Connection,
    vendor_id: int,
) -> tuple[VendorOpenPurchase, ...]:
    rows = conn.execute(
        """
        SELECT
            p.purchase_id,
            p.date,
            COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount,
            CAST(p.total_amount AS REAL)    AS total_amount,
            CAST(p.paid_amount AS REAL)     AS paid_amount,
            CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
            (COALESCE(pdt.calculated_total_amount, p.total_amount) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS balance
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.vendor_id = ?
          AND (COALESCE(pdt.calculated_total_amount, p.total_amount) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) > 1e-9
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """,
        (vendor_id,),
    ).fetchall()
    out: list[VendorOpenPurchase] = []
    for row in rows:
        purchase_id = _row_value(row, "purchase_id", 0)
        date = _row_value(row, "date", 1)
        calculated_total = _decimal(_row_value(row, "calculated_total_amount", 2))
        total = _decimal(_row_value(row, "total_amount", 3))
        paid = _decimal(_row_value(row, "paid_amount", 4))
        applied = _decimal(_row_value(row, "advance_payment_applied", 5))
        balance = _decimal(_row_value(row, "balance", 6))
        out.append(
            VendorOpenPurchase(
                purchase_id=purchase_id,
                vendor_id=int(vendor_id),
                purchase_date=date,
                reference=str(purchase_id),
                net_total=calculated_total,
                outstanding=balance,
                total_amount=total,
                paid_amount=paid,
                advance_payment_applied=applied,
                calculated_total_amount=calculated_total,
            )
        )
    return tuple(out)
