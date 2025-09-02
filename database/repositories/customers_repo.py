from __future__ import annotations
from dataclasses import dataclass
import sqlite3


# Domain-level error the controller can surface directly (e.g., toast/snackbar)
class DomainError(Exception):
    pass


@dataclass
class Customer:
    customer_id: int | None
    name: str
    contact_info: str
    address: str | None


class CustomersRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- Internal helpers -------------------------------------------------

    @staticmethod
    def _normalize_text(s: str | None) -> str | None:
        if s is None:
            return None
        # Gentle normalization: trim surrounding whitespace (no extra assumptions)
        return s.strip()

    @staticmethod
    def _ensure_non_empty(value: str | None, field_label: str) -> None:
        if value is None or value.strip() == "":
            raise DomainError(f"{field_label} cannot be empty.")

    # ---- Queries ----------------------------------------------------------

    def list_customers(self, active_only: bool = True) -> list[Customer]:
        """
        Returns customers. By default, only active rows (is_active=1).
        Set active_only=False to include inactive as well.
        """
        if active_only:
            rows = self.conn.execute(
                "SELECT customer_id, name, contact_info, address "
                "FROM customers "
                "WHERE is_active = 1 "
                "ORDER BY customer_id DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT customer_id, name, contact_info, address "
                "FROM customers "
                "ORDER BY customer_id DESC"
            ).fetchall()
        return [Customer(**r) for r in rows]

    def search(self, term: str, active_only: bool = True) -> list[Customer]:
        """
        Server-side search over id/name/contact/address.
        Matches using LIKE on:
          - CAST(customer_id AS TEXT)
          - name
          - contact_info
          - address
        """
        pattern = f"%{term.strip()}%"
        if active_only:
            rows = self.conn.execute(
                "SELECT customer_id, name, contact_info, address "
                "FROM customers "
                "WHERE is_active = 1 AND ("
                "  CAST(customer_id AS TEXT) LIKE ? OR "
                "  name LIKE ? OR "
                "  contact_info LIKE ? OR "
                "  address LIKE ?"
                ") "
                "ORDER BY customer_id DESC",
                (pattern, pattern, pattern, pattern),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT customer_id, name, contact_info, address "
                "FROM customers "
                "WHERE "
                "  CAST(customer_id AS TEXT) LIKE ? OR "
                "  name LIKE ? OR "
                "  contact_info LIKE ? OR "
                "  address LIKE ? "
                "ORDER BY customer_id DESC",
                (pattern, pattern, pattern, pattern),
            ).fetchall()
        return [Customer(**r) for r in rows]

    def get(self, customer_id: int) -> Customer | None:
        r = self.conn.execute(
            "SELECT customer_id, name, contact_info, address "
            "FROM customers WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        return Customer(**r) if r else None

    # ---- Mutations --------------------------------------------------------

    def create(self, name: str, contact_info: str, address: str | None) -> int:
        """
        Insert a new customer. Soft validation mirrors form checks.
        """
        # validation
        self._ensure_non_empty(name, "Name")
        self._ensure_non_empty(contact_info, "Contact")

        # normalization
        name_n = self._normalize_text(name)
        contact_n = self._normalize_text(contact_info)
        address_n = self._normalize_text(address)

        cur = self.conn.execute(
            "INSERT INTO customers(name, contact_info, address) VALUES (?,?,?)",
            (name_n, contact_n, address_n),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update(self, customer_id: int, name: str, contact_info: str, address: str | None) -> None:
        """
        Update core fields for a customer. Soft validation mirrors form checks.
        """
        # validation
        self._ensure_non_empty(name, "Name")
        self._ensure_non_empty(contact_info, "Contact")

        # normalization
        name_n = self._normalize_text(name)
        contact_n = self._normalize_text(contact_info)
        address_n = self._normalize_text(address)

        self.conn.execute(
            "UPDATE customers SET name=?, contact_info=?, address=? WHERE customer_id=?",
            (name_n, contact_n, address_n, customer_id),
        )
        self.conn.commit()

    def delete(self, customer_id: int) -> None:
        self.conn.execute("DELETE FROM customers WHERE customer_id=?", (customer_id,))
        self.conn.commit()
