from __future__ import annotations
from dataclasses import dataclass
import sqlite3

from modules.accounting import AccountingService


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
        self.accounting = AccountingService(conn)
        conn.row_factory = sqlite3.Row
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

    def _customer_search_clause(self, search: str | None) -> tuple[str, list[object]]:
        term = (search or "").strip()
        if not term:
            return "", []
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped.lower()}%"
        return (
            "WHERE "
            "  LOWER(CAST(customer_id AS TEXT)) LIKE ? ESCAPE '\\' OR "
            "  LOWER(COALESCE(name, '')) LIKE ? ESCAPE '\\' OR "
            "  LOWER(COALESCE(contact_info, '')) LIKE ? ESCAPE '\\' OR "
            "  LOWER(COALESCE(address, '')) LIKE ? ESCAPE '\\' ",
            [pattern, pattern, pattern, pattern],
        )

    def count_customers(self, search: str | None = None) -> int:
        where_sql, params = self._customer_search_clause(search)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM customers {where_sql}",
            params,
        ).fetchone()
        return int(row["c"] if row else 0)

    def list_customers(
        self,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Customer]:
        """
        Returns customers ordered newest first.
        """
        where_sql, params = self._customer_search_clause(search)
        limit_sql = ""
        if limit is not None and int(limit) > 0:
            limit_sql = "LIMIT ? OFFSET ?"
            params.extend([int(limit), max(0, int(offset))])
        rows = self.conn.execute(
            f"""
            SELECT customer_id, name, contact_info, address
            FROM customers
            {where_sql}
            ORDER BY customer_id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [Customer(**dict(r)) for r in rows]

    def search(self, term: str) -> list[Customer]:
        """
        Server-side search over id/name/contact/address.
        Matches using LIKE on:
          - CAST(customer_id AS TEXT)
          - name
          - contact_info
          - address
        """
        return self.list_customers(search=term)

    def get_detail_snapshot(self, customer_id: int) -> dict | None:
        row = self.conn.execute(
            """
            SELECT customer_id, name, contact_info, address
              FROM customers
             WHERE customer_id = ?
            """,
            (customer_id,),
        ).fetchone()
        if not row:
            return None
        fin = self.accounting.get_customer_receivable_summary(customer_id)
        balance = self.accounting.get_customer_balance(customer_id)
        return {
            **dict(row),
            "balance": float(balance.balance),
            "credit_balance": float(fin.credit_balance),
            "sales_count": fin.sales_count,
            "open_due_sum": float(fin.open_due_sum),
            "last_sale_date": fin.last_sale_date,
            "last_payment_date": fin.last_payment_date,
            "last_advance_date": fin.last_advance_date,
        }

    def get(self, customer_id: int) -> Customer | None:
        r = self.conn.execute(
            "SELECT customer_id, name, contact_info, address "
            "FROM customers WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        return Customer(**dict(r)) if r else None

    def has_duplicate_name(self, name: str, current_id: int | None = None) -> bool:
        row = self.conn.execute(
            """
            SELECT customer_id
              FROM customers
             WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
               AND (? IS NULL OR customer_id != ?)
             LIMIT 1
            """,
            (name, current_id, current_id),
        ).fetchone()
        return row is not None

    # ---- Mutations --------------------------------------------------------

    def create(self, name: str, contact_info: str, address: str | None) -> int:
        """
        Insert a new customer. Soft validation mirrors form checks.
        """
        was_in_transaction = self.conn.in_transaction
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
        if not was_in_transaction:
            self.conn.commit()
        return int(cur.lastrowid)

    def update(self, customer_id: int, name: str, contact_info: str, address: str | None) -> None:
        """
        Update core fields for a customer. Soft validation mirrors form checks.
        """
        was_in_transaction = self.conn.in_transaction
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
        if not was_in_transaction:
            self.conn.commit()

    # def delete(self, customer_id: int) -> None:
    #     self.conn.execute("DELETE FROM customers WHERE customer_id=?", (customer_id,))
    #     self.conn.commit()
