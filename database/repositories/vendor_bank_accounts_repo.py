from __future__ import annotations
import sqlite3
from typing import Any, Dict, Iterable, Optional


class VendorBankAccountsRepo:
    """
    Repository for vendor_bank_accounts.

    Table (per schema):
        vendor_bank_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id              INTEGER NOT NULL,
        label                  TEXT NOT NULL,
        bank_name              TEXT,
        account_no             TEXT,
        iban                   TEXT,
        routing_no             TEXT,
        is_primary             INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
        is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))

    Index/constraints:
        - UNIQUE(vendor_id, label)
        - Partial UNIQUE one primary per vendor (WHERE is_primary = 1)
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -------------------------
    # Query
    # -------------------------
    def list(self, vendor_id: int, active_only: bool = True) -> list[dict]:
        """
        List bank accounts for a vendor. By default, only active accounts.
        Ordered with primaries first, then by creation/id for stable results.
        """
        sql_parts = [
            """
            SELECT vendor_bank_account_id, vendor_id, label, bank_name, account_no,
                   iban, routing_no, is_primary, is_active
              FROM vendor_bank_accounts
             WHERE vendor_id = ?
            """
        ]
        params = [vendor_id]
        if active_only:
            sql_parts.append("AND is_active = 1")
        # Primary first, then by id asc for a stable order
        sql_parts.append("ORDER BY is_primary DESC, vendor_bank_account_id ASC")

        rows = self.conn.execute("\n".join(sql_parts), params).fetchall()

        # Return plain dicts regardless of row_factory
        out: list[dict] = []
        for r in rows:
            if isinstance(r, sqlite3.Row):
                out.append(dict(r))
            else:
                out.append({
                    "vendor_bank_account_id": r[0],
                    "vendor_id": r[1],
                    "label": r[2],
                    "bank_name": r[3],
                    "account_no": r[4],
                    "iban": r[5],
                    "routing_no": r[6],
                    "is_primary": r[7],
                    "is_active": r[8],
                })
        return out

    # Convenience alias if you prefer a less overloaded name from callers
    def list_accounts(self, vendor_id: int, active_only: bool = True) -> list[dict]:
        return self.list(vendor_id, active_only)

    # -------------------------
    # Create / Update
    # -------------------------
    def create(self, vendor_id: int, data: Dict[str, Any]) -> int:
        """
        Create a bank account for the vendor.

        Expected keys in `data`:
            label (required), bank_name, account_no, iban, routing_no,
            is_primary (optional bool/int), is_active (optional bool/int; defaults 1)

        NOTE: This method performs a direct insert and does NOT normalize primaries.
              Use set_primary(...) for a safe single-primary toggle. If you insert
              multiple rows with is_primary=1, the partial UNIQUE index may raise
              IntegrityError depending on your schema/indexes.
        """
        label = (data.get("label") or "").strip()
        if not label:
            raise ValueError("label is required")

        bank_name = data.get("bank_name")
        account_no = data.get("account_no")
        iban = data.get("iban")
        routing_no = data.get("routing_no")
        is_primary = 1 if data.get("is_primary") in (True, 1, "1") else 0
        is_active = 0 if data.get("is_active") in (False, 0, "0") else 1

        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO vendor_bank_accounts (
                    vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active),
            )
            return int(cur.lastrowid)

    def update(self, account_id: int, data: Dict[str, Any]) -> int:
        """
        Update fields for an existing vendor bank account.

        Updatable keys:
            label, bank_name, account_no, iban, routing_no, is_primary, is_active

        RAW update: this method does NOT normalize primaries or unset others.
        If you set is_primary=1 while another account for the same vendor is
        already primary, the partial UNIQUE index should raise IntegrityError.
        Use set_primary(...) to safely toggle a single primary.
        """
        allowed = {"label", "bank_name", "account_no", "iban", "routing_no", "is_primary", "is_active"}
        update_data = {k: v for k, v in data.items() if k in allowed}
        if not update_data:
            return 0

        # Normalize boolean-ish fields to ints, but do NOT touch other rows
        if "is_primary" in update_data:
            update_data["is_primary"] = 1 if update_data["is_primary"] in (True, 1, "1") else 0
        if "is_active" in update_data:
            update_data["is_active"] = 0 if update_data["is_active"] in (False, 0, "0") else 1

        # Build dynamic UPDATE
        sets = []
        params: list[Any] = []
        for k, v in update_data.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(account_id)

        sql = f"UPDATE vendor_bank_accounts SET {', '.join(sets)} WHERE vendor_bank_account_id = ?"
        with self.conn:
            cur = self.conn.execute(sql, params)
            return cur.rowcount

    # -------------------------
    # Deactivate / Primary
    # -------------------------
    def deactivate(self, account_id: int) -> int:
        """
        Deactivate an account. If it is not referenced elsewhere, it may be deleted;
        otherwise it will be marked is_active = 0.

        Returns number of affected rows (1 if updated/deleted, 0 if no such row).
        """
        # Check references via COUNT for clarity (functionally same as EXISTS)
        row = self.conn.execute(
            "SELECT COUNT(1) FROM purchase_payments WHERE vendor_bank_account_id = ?",
            (account_id,),
        ).fetchone()
        referenced = (row[0] if row else 0) > 0

        with self.conn:
            if referenced:
                cur = self.conn.execute(
                    "UPDATE vendor_bank_accounts SET is_active = 0 WHERE vendor_bank_account_id = ?",
                    (account_id,),
                )
                return cur.rowcount
            else:
                # Safe to hard-delete
                cur = self.conn.execute(
                    "DELETE FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
                    (account_id,),
                )
                # If nothing deleted (id not found), return 0
                return cur.rowcount

    def set_primary(self, vendor_id: int, account_id: int) -> int:
        """
        Make `account_id` the primary account for the vendor, unsetting others.
        Partial UNIQUE index (WHERE is_primary=1) enforces the single-primary rule.

        Returns number of rows updated (at least 1 if the account exists).
        """
        with self.conn:
            # Clear others
            self.conn.execute(
                "UPDATE vendor_bank_accounts SET is_primary = 0 WHERE vendor_id = ?",
                (vendor_id,),
            )
            # Set this one (ensure active as well)
            cur = self.conn.execute(
                """
                UPDATE vendor_bank_accounts
                   SET is_primary = 1, is_active = 1
                 WHERE vendor_bank_account_id = ? AND vendor_id = ?
                """,
                (account_id, vendor_id),
            )
            return cur.rowcount
