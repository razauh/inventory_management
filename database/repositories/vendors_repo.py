from dataclasses import dataclass
import sqlite3

@dataclass
class Vendor:
    vendor_id: int | None
    name: str
    contact_info: str
    address: str | None

class VendorsRepo:
    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn

    def list_vendors(self) -> list[Vendor]:
        rows = self.conn.execute(
            "SELECT vendor_id, name, contact_info, address FROM vendors ORDER BY vendor_id DESC"
        ).fetchall()
        return [Vendor(**dict(r)) for r in rows]

    def get(self, vendor_id: int) -> Vendor | None:
        r = self.conn.execute(
            "SELECT vendor_id, name, contact_info, address FROM vendors WHERE vendor_id=?",
            (vendor_id,)
        ).fetchone()
        return Vendor(**dict(r)) if r else None

    def create(self, name: str, contact_info: str, address: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO vendors(name, contact_info, address) VALUES (?, ?, ?)",
            (name, contact_info, address)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update(self, vendor_id: int, name: str, contact_info: str, address: str | None):
        self.conn.execute(
            "UPDATE vendors SET name=?, contact_info=?, address=? WHERE vendor_id=?",
            (name, contact_info, address, vendor_id)
        )
        self.conn.commit()

    # def delete(self, vendor_id: int):
    #     self.conn.execute("DELETE FROM vendors WHERE vendor_id=?", (vendor_id,))
    #     self.conn.commit()
