"""Future home for extracted vendor accounting behavior.

These rules will mirror current code first. They are not assumed correct.
"""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import VendorBalance


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _row_value(row: object, key: str, index: int) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (TypeError, KeyError, IndexError):
        return row[index]  # type: ignore[index]


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
