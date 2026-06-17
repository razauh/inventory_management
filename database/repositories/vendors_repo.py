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

    def _vendor_search_clause(self, search: str | None) -> tuple[str, list[object]]:
        text = (search or "").strip()
        if not text:
            return "", []
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped.lower()}%"
        return (
            """
            WHERE LOWER(CAST(v.vendor_id AS TEXT)) LIKE ? ESCAPE '\\'
               OR LOWER(COALESCE(v.name, '')) LIKE ? ESCAPE '\\'
               OR LOWER(COALESCE(v.contact_info, '')) LIKE ? ESCAPE '\\'
               OR LOWER(COALESCE(v.address, '')) LIKE ? ESCAPE '\\'
            """,
            [pattern, pattern, pattern, pattern],
        )

    def count_vendors(self, search: str | None = None) -> int:
        where_sql, params = self._vendor_search_clause(search)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM vendors v {where_sql}",
            params,
        ).fetchone()
        return int(row["c"] if row else 0)

    def list_vendors(
        self,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Vendor]:
        where_sql, params = self._vendor_search_clause(search)
        limit_sql = ""
        if limit is not None and int(limit) > 0:
            limit_sql = "LIMIT ? OFFSET ?"
            params.extend([int(limit), max(0, int(offset))])
        rows = self.conn.execute(
            f"""
            SELECT
              v.vendor_id,
              v.name,
              v.contact_info,
              v.address
            FROM vendors v
            {where_sql}
            ORDER BY v.vendor_id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [Vendor(**dict(r)) for r in rows]

    def vendor_balances(self, vendor_ids: list[int]) -> dict[int, float]:
        ids = [int(vendor_id) for vendor_id in vendor_ids if vendor_id is not None]
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"""
            SELECT v.vendor_id, COALESCE(b.balance, 0.0) AS balance
            FROM vendors v
            LEFT JOIN v_vendor_advance_balance b ON b.vendor_id = v.vendor_id
            WHERE v.vendor_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        return {int(row["vendor_id"]): float(row["balance"] or 0.0) for row in rows}

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
