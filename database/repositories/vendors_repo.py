from dataclasses import dataclass
import sqlite3


class DomainError(Exception):
    pass

@dataclass
class Vendor:
    vendor_id: int | None
    name: str
    contact_info: str
    address: str | None
    balance: float | None = None

class VendorsRepo:
    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @staticmethod
    def _ensure_non_empty(value: str | None, field_label: str) -> None:
        if value is None or value.strip() == "":
            raise DomainError(f"{field_label} cannot be empty.")

    def list_vendors(self) -> list[Vendor]:
        rows = self.conn.execute(
            """
            SELECT
              v.vendor_id,
              v.name,
              v.contact_info,
              v.address,
              COALESCE(b.balance, 0.0) AS balance
            FROM vendors v
            LEFT JOIN v_vendor_advance_balance b ON b.vendor_id = v.vendor_id
            ORDER BY v.vendor_id DESC
            """
        ).fetchall()
        return [Vendor(**dict(r)) for r in rows]

    def get(self, vendor_id: int) -> Vendor | None:
        r = self.conn.execute(
            "SELECT vendor_id, name, contact_info, address FROM vendors WHERE vendor_id=?",
            (vendor_id,)
        ).fetchone()
        return Vendor(**dict(r)) if r else None

    def create(self, name: str, contact_info: str, address: str | None) -> int:
        was_in_transaction = self.conn.in_transaction
        self._ensure_non_empty(name, "Name")
        self._ensure_non_empty(contact_info, "Contact")
        name_n = self._normalize_text(name)
        contact_n = self._normalize_text(contact_info)
        address_n = self._normalize_text(address)
        cur = self.conn.execute(
            "INSERT INTO vendors(name, contact_info, address) VALUES (?, ?, ?)",
            (name_n, contact_n, address_n)
        )
        if not was_in_transaction:
            self.conn.commit()
        return int(cur.lastrowid)

    def update(self, vendor_id: int, name: str, contact_info: str, address: str | None):
        was_in_transaction = self.conn.in_transaction
        self._ensure_non_empty(name, "Name")
        self._ensure_non_empty(contact_info, "Contact")
        name_n = self._normalize_text(name)
        contact_n = self._normalize_text(contact_info)
        address_n = self._normalize_text(address)
        self.conn.execute(
            "UPDATE vendors SET name=?, contact_info=?, address=? WHERE vendor_id=?",
            (name_n, contact_n, address_n, vendor_id)
        )
        if not was_in_transaction:
            self.conn.commit()

    # def delete(self, vendor_id: int):
    #     self.conn.execute("DELETE FROM vendors WHERE vendor_id=?", (vendor_id,))
    #     self.conn.commit()
