"""Current bank metadata validation behavior."""

from __future__ import annotations

from sqlite3 import Connection


def validate_company_bank_account_active(
    conn: Connection,
    bank_account_id: int | None,
) -> None:
    if bank_account_id is None:
        return
    row = conn.execute(
        "SELECT is_active FROM company_bank_accounts WHERE account_id = ?",
        (bank_account_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Company bank account not found: {bank_account_id}")
    if int(row["is_active"]) != 1:
        raise ValueError(
            "Selected company bank account is inactive and cannot be used for new transactions."
        )


def validate_vendor_bank_account(
    conn: Connection,
    *,
    vendor_id: int,
    vendor_bank_account_id: int | None,
    vendor_label: str,
) -> None:
    if vendor_bank_account_id is None:
        return
    row = conn.execute(
        """
        SELECT vendor_id, is_active
        FROM vendor_bank_accounts
        WHERE vendor_bank_account_id = ?
        """,
        (vendor_bank_account_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Vendor bank account not found: {vendor_bank_account_id}")
    if int(row["vendor_id"]) != int(vendor_id):
        raise ValueError(f"Vendor bank account does not belong to the {vendor_label} vendor")
    if int(row["is_active"]) != 1:
        raise ValueError(
            "Selected vendor bank account is inactive and cannot be used for new transactions."
        )
