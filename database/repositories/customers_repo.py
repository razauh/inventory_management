from __future__ import annotations
from dataclasses import dataclass
import sqlite3

@dataclass
class Customer:
    customer_id: int | None
    name: str
    contact_info: str
    address: str | None

class CustomersRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- Queries ----
    def list_customers(self) -> list[Customer]:
        rows = self.conn.execute(
            "SELECT customer_id, name, contact_info, address "
            "FROM customers ORDER BY customer_id DESC"
        ).fetchall()
        return [Customer(**r) for r in rows]

    def get(self, customer_id: int) -> Customer | None:
        r = self.conn.execute(
            "SELECT customer_id, name, contact_info, address "
            "FROM customers WHERE customer_id=?",
            (customer_id,)
        ).fetchone()
        return Customer(**r) if r else None

    # ---- Mutations ----
    def create(self, name: str, contact_info: str, address: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO customers(name, contact_info, address) VALUES (?,?,?)",
            (name, contact_info, address)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update(self, customer_id: int, name: str, contact_info: str, address: str | None):
        self.conn.execute(
            "UPDATE customers SET name=?, contact_info=?, address=? WHERE customer_id=?",
            (name, contact_info, address, customer_id)
        )
        self.conn.commit()

    def delete(self, customer_id: int):
        self.conn.execute("DELETE FROM customers WHERE customer_id=?", (customer_id,))
        self.conn.commit()
