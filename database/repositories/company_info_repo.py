from __future__ import annotations

import sqlite3
from typing import Any


# Central invoice fallback when no active company profile exists.
DEFAULT_COMPANY_INFO = {
    "company_id": None,
    "name": "Your Company Name",
    "company_name": "Your Company Name",
    "logo_path": None,
    "address_lines": [],
    "contact_lines": [],
    "tax_number": None,
    "invoice_footer_note": "",
    "terms_text": "",
    "bank_accounts": [],
}


class CompanyInfoRepo:
    def __init__(self, conn: sqlite3.Connection):
        conn.row_factory = sqlite3.Row
        self.conn = conn

    def get(self) -> dict | None:
        row = self.conn.execute(
            """
            SELECT company_id, company_name, address, logo_path, address_line1,
                   address_line2, city, state_region, postal_code, country,
                   phone, email, website, tax_number, invoice_footer_note,
                   terms_text, is_active
            FROM company_info
            WHERE company_id = 1
            """
        ).fetchone()
        return dict(row) if row else None

    def save(self, data: dict[str, Any]) -> None:
        name = (data.get("company_name") or data.get("name") or "").strip()
        if not name:
            raise ValueError("Company name is required.")
        values = {
            "company_name": name,
            "address": (data.get("address") or data.get("address_line1") or "").strip() or None,
            "logo_path": (data.get("logo_path") or "").strip() or None,
            "address_line1": (data.get("address_line1") or "").strip() or None,
            "address_line2": (data.get("address_line2") or "").strip() or None,
            "city": (data.get("city") or "").strip() or None,
            "state_region": (data.get("state_region") or "").strip() or None,
            "postal_code": (data.get("postal_code") or "").strip() or None,
            "country": (data.get("country") or "").strip() or None,
            "phone": (data.get("phone") or "").strip() or None,
            "email": (data.get("email") or "").strip() or None,
            "website": (data.get("website") or "").strip() or None,
            "tax_number": (data.get("tax_number") or "").strip() or None,
            "invoice_footer_note": (data.get("invoice_footer_note") or "").strip() or None,
            "terms_text": (data.get("terms_text") or "").strip() or None,
            "is_active": 1 if data.get("is_active", 1) in (True, 1, "1") else 0,
        }
        self.conn.execute(
            """
            INSERT INTO company_info (
                company_id, company_name, address, logo_path, address_line1,
                address_line2, city, state_region, postal_code, country,
                phone, email, website, tax_number, invoice_footer_note,
                terms_text, is_active
            ) VALUES (
                1, :company_name, :address, :logo_path, :address_line1,
                :address_line2, :city, :state_region, :postal_code, :country,
                :phone, :email, :website, :tax_number, :invoice_footer_note,
                :terms_text, :is_active
            )
            ON CONFLICT(company_id) DO UPDATE SET
                company_name=excluded.company_name,
                address=excluded.address,
                logo_path=excluded.logo_path,
                address_line1=excluded.address_line1,
                address_line2=excluded.address_line2,
                city=excluded.city,
                state_region=excluded.state_region,
                postal_code=excluded.postal_code,
                country=excluded.country,
                phone=excluded.phone,
                email=excluded.email,
                website=excluded.website,
                tax_number=excluded.tax_number,
                invoice_footer_note=excluded.invoice_footer_note,
                terms_text=excluded.terms_text,
                is_active=excluded.is_active
            """,
            values,
        )
        self.conn.commit()

    def delete(self) -> None:
        refs = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM sale_payments WHERE bank_account_id IS NOT NULL) +
              (SELECT COUNT(*) FROM purchase_payments WHERE bank_account_id IS NOT NULL) +
              (SELECT COUNT(*) FROM purchase_refunds WHERE bank_account_id IS NOT NULL) +
              (SELECT COUNT(*) FROM vendor_advances WHERE bank_account_id IS NOT NULL) +
              (SELECT COUNT(*) FROM customer_advances WHERE bank_account_id IS NOT NULL) AS c
            """
        ).fetchone()
        if refs and int(refs["c"] or 0) > 0:
            raise sqlite3.IntegrityError("Company info has bank accounts used by payments.")
        self.conn.execute("DELETE FROM company_info WHERE company_id = 1")
        self.conn.commit()

    def list_bank_accounts(self, active_only: bool = False) -> list[dict]:
        sql = """
            SELECT account_id, company_id, label, bank_name, account_no, iban,
                   routing_no, branch_name, swift_code, notes, is_primary, is_active
            FROM company_bank_accounts
            WHERE company_id = 1
        """
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY is_active DESC, is_primary DESC, label"
        return [dict(row) for row in self.conn.execute(sql).fetchall()]

    def get_bank_account(self, account_id: int) -> dict | None:
        row = self.conn.execute(
            """
            SELECT account_id, company_id, label, bank_name, account_no, iban,
                   routing_no, branch_name, swift_code, notes, is_primary, is_active
            FROM company_bank_accounts
            WHERE company_id = 1 AND account_id = ?
            """,
            (account_id,),
        ).fetchone()
        return dict(row) if row else None

    def save_bank_account(self, data: dict[str, Any], account_id: int | None = None) -> int:
        label = (data.get("label") or data.get("account_title") or "").strip()
        if not label:
            raise ValueError("Account title is required.")
        values = {
            "label": label,
            "bank_name": (data.get("bank_name") or "").strip() or None,
            "account_no": (data.get("account_no") or data.get("account_number") or "").strip() or None,
            "iban": (data.get("iban") or "").strip() or None,
            "routing_no": (data.get("routing_no") or data.get("routing_swift_code") or "").strip() or None,
            "branch_name": (data.get("branch_name") or "").strip() or None,
            "swift_code": (data.get("swift_code") or "").strip() or None,
            "notes": (data.get("notes") or "").strip() or None,
            "is_primary": 1 if data.get("is_primary") in (True, 1, "1") else 0,
            "is_active": 0 if data.get("is_active") in (False, 0, "0") else 1,
        }
        if values["is_primary"] and not values["is_active"]:
            raise ValueError("Primary bank account must be active.")
        with self.conn:
            if values["is_primary"]:
                self.conn.execute("UPDATE company_bank_accounts SET is_primary = 0 WHERE company_id = 1")
            if account_id is None:
                cur = self.conn.execute(
                    """
                    INSERT INTO company_bank_accounts (
                        company_id, label, bank_name, account_no, iban, routing_no,
                        branch_name, swift_code, notes, is_primary, is_active
                    ) VALUES (1, :label, :bank_name, :account_no, :iban, :routing_no,
                              :branch_name, :swift_code, :notes, :is_primary, :is_active)
                    """,
                    values,
                )
                return int(cur.lastrowid)
            self.conn.execute(
                """
                UPDATE company_bank_accounts
                SET label=:label, bank_name=:bank_name, account_no=:account_no,
                    iban=:iban, routing_no=:routing_no, branch_name=:branch_name,
                    swift_code=:swift_code, notes=:notes, is_primary=:is_primary,
                    is_active=:is_active
                WHERE company_id = 1 AND account_id = :account_id
                """,
                {**values, "account_id": account_id},
            )
            return int(account_id)

    def delete_bank_account(self, account_id: int) -> None:
        refs = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM sale_payments WHERE bank_account_id = ?) +
              (SELECT COUNT(*) FROM purchase_payments WHERE bank_account_id = ?) +
              (SELECT COUNT(*) FROM purchase_refunds WHERE bank_account_id = ?) +
              (SELECT COUNT(*) FROM vendor_advances WHERE bank_account_id = ?) +
              (SELECT COUNT(*) FROM customer_advances WHERE bank_account_id = ?) AS c
            """,
            (account_id, account_id, account_id, account_id, account_id),
        ).fetchone()
        if refs and int(refs["c"] or 0) > 0:
            self.conn.execute(
                "UPDATE company_bank_accounts SET is_active = 0, is_primary = 0 WHERE account_id = ?",
                (account_id,),
            )
        else:
            self.conn.execute("DELETE FROM company_bank_accounts WHERE company_id = 1 AND account_id = ?", (account_id,))
        self.conn.commit()

    def set_primary_bank_account(self, account_id: int) -> None:
        row = self.get_bank_account(account_id)
        if not row or not int(row.get("is_active") or 0):
            raise ValueError("Primary bank account must be active.")
        with self.conn:
            self.conn.execute("UPDATE company_bank_accounts SET is_primary = 0 WHERE company_id = 1")
            self.conn.execute(
                "UPDATE company_bank_accounts SET is_primary = 1 WHERE company_id = 1 AND account_id = ?",
                (account_id,),
            )

    def invoice_context(self) -> dict:
        row = self.get()
        if not row or not int(row.get("is_active") or 0):
            return dict(DEFAULT_COMPANY_INFO)
        address_lines = [
            row.get("address_line1") or row.get("address"),
            row.get("address_line2"),
            " ".join(part for part in [row.get("city"), row.get("state_region"), row.get("postal_code")] if part),
            row.get("country"),
        ]
        contact_lines = [
            f"Phone: {row['phone']}" if row.get("phone") else None,
            f"Email: {row['email']}" if row.get("email") else None,
            f"Website: {row['website']}" if row.get("website") else None,
            f"Tax No: {row['tax_number']}" if row.get("tax_number") else None,
        ]
        return {
            **row,
            "name": row.get("company_name") or DEFAULT_COMPANY_INFO["name"],
            "address_lines": [line for line in address_lines if line],
            "contact_lines": [line for line in contact_lines if line],
            "bank_accounts": self.list_bank_accounts(active_only=True),
        }


def get_invoice_company_context(conn: sqlite3.Connection | None) -> dict:
    if conn is None:
        return dict(DEFAULT_COMPANY_INFO)
    try:
        return CompanyInfoRepo(conn).invoice_context()
    except Exception:
        return dict(DEFAULT_COMPANY_INFO)
