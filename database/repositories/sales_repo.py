from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable

@dataclass
class SaleHeader:
    sale_id: str
    customer_id: int
    date: str
    total_amount: float
    order_discount: float
    payment_status: str
    paid_amount: float
    advance_payment_applied: float
    notes: str | None
    created_by: int | None
    source_type: str = "direct"
    source_id: int | None = None

@dataclass
class SaleItem:
    item_id: int | None
    sale_id: str
    product_id: int
    quantity: float
    uom_id: int
    unit_price: float
    item_discount: float

class SalesRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -------- read ----------
    def list_sales(self) -> list[dict]:
        sql = """
        SELECT s.sale_id, s.date, s.customer_id, c.name AS customer_name,
               CAST(s.total_amount AS REAL) AS total_amount,
               CAST(s.order_discount AS REAL) AS order_discount,
               CAST(s.paid_amount AS REAL) AS paid_amount,
               s.payment_status, s.notes
        FROM sales s
        JOIN customers c ON c.customer_id = s.customer_id
        ORDER BY DATE(s.date) DESC, s.sale_id DESC
        """
        return self.conn.execute(sql).fetchall()

    def search_sales(self, query: str = "", date: str | None = None) -> list[dict]:
        """
        Flexible finder for returns UI: filter by sale_id/customer name and/or exact date.
        """
        where = []
        params: list = []
        if query:
            where.append("(s.sale_id LIKE ? OR c.name LIKE ?)")
            params += [f"%{query}%", f"%{query}%"]
        if date:
            where.append("DATE(s.date) = DATE(?)")
            params.append(date)
        sql = """
          SELECT s.sale_id, s.date, c.name AS customer_name,
                 CAST(s.total_amount AS REAL) AS total_amount,
                 CAST(s.paid_amount AS REAL) AS paid_amount, s.payment_status
          FROM sales s JOIN customers c ON c.customer_id=s.customer_id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY DATE(s.date) DESC, s.sale_id DESC"
        return self.conn.execute(sql, params).fetchall()

    def get_header(self, sid: str) -> dict | None:
        return self.conn.execute("SELECT * FROM sales WHERE sale_id=?", (sid,)).fetchone()

    def list_items(self, sid: str) -> list[dict]:
        sql = """
        SELECT si.item_id, si.sale_id, si.product_id, p.name AS product_name,
               CAST(si.quantity AS REAL) AS quantity, si.uom_id,
               u.unit_name, CAST(si.unit_price AS REAL) AS unit_price,
               CAST(si.item_discount AS REAL) AS item_discount
        FROM sale_items si
        JOIN products p ON p.product_id = si.product_id
        JOIN uoms u     ON u.uom_id     = si.uom_id
        WHERE si.sale_id = ?
        ORDER BY si.item_id
        """
        return self.conn.execute(sql, (sid,)).fetchall()

    # -------- write ----------
    def _insert_header(self, h: SaleHeader):
        self.conn.execute("""
            INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount,
                              payment_status, paid_amount, advance_payment_applied,
                              notes, created_by, source_type, source_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (h.sale_id, h.customer_id, h.date, h.total_amount, h.order_discount,
             h.payment_status, h.paid_amount, h.advance_payment_applied,
             h.notes, h.created_by, h.source_type, h.source_id))

    def _insert_item(self, it: SaleItem) -> int:
        cur = self.conn.execute("""
            INSERT INTO sale_items(sale_id, product_id, quantity, uom_id, unit_price, item_discount)
            VALUES (?,?,?,?,?,?)""",
            (it.sale_id, it.product_id, it.quantity, it.uom_id, it.unit_price, it.item_discount))
        return int(cur.lastrowid)

    def _insert_inventory_sale(self, *, item_id: int, product_id: int, uom_id: int, qty: float,
                               sid: str, date: str, created_by: int | None, notes: str | None):
        self.conn.execute("""
            INSERT INTO inventory_transactions(product_id, quantity, uom_id, transaction_type,
                                               reference_table, reference_id, reference_item_id,
                                               date, notes, created_by)
            VALUES (?, ?, ?, 'sale', 'sales', ?, ?, ?, ?, ?)""",
            (product_id, qty, uom_id, sid, item_id, date, notes, created_by))

    def _delete_sale_content(self, sid: str):
        self.conn.execute("DELETE FROM inventory_transactions WHERE reference_table='sales' AND reference_id=?", (sid,))
        self.conn.execute("DELETE FROM sale_items WHERE sale_id=?", (sid,))

    def create_sale(self, header: SaleHeader, items: Iterable[SaleItem]):
        with self.conn:
            self._insert_header(header)
            for it in items:
                it.sale_id = header.sale_id
                item_id = self._insert_item(it)
                self._insert_inventory_sale(
                    item_id=item_id, product_id=it.product_id, uom_id=it.uom_id, qty=it.quantity,
                    sid=header.sale_id, date=header.date, created_by=header.created_by, notes=header.notes)

    def update_sale(self, header: SaleHeader, items: Iterable[SaleItem]):
        with self.conn:
            self.conn.execute("""
                UPDATE sales
                   SET customer_id=?, date=?, total_amount=?, order_discount=?,
                       payment_status=?, paid_amount=?, advance_payment_applied=?,
                       notes=?, created_by=?, source_type=?, source_id=?
                 WHERE sale_id=?""",
                (header.customer_id, header.date, header.total_amount, header.order_discount,
                 header.payment_status, header.paid_amount, header.advance_payment_applied,
                 header.notes, header.created_by, header.source_type, header.source_id,
                 header.sale_id))
            self._delete_sale_content(header.sale_id)
            for it in items:
                it.sale_id = header.sale_id
                item_id = self._insert_item(it)
                self._insert_inventory_sale(
                    item_id=item_id, product_id=it.product_id, uom_id=it.uom_id, qty=it.quantity,
                    sid=header.sale_id, date=header.date, created_by=header.created_by, notes=header.notes)

    def delete_sale(self, sid: str):
        with self.conn:
            self._delete_sale_content(sid)
            self.conn.execute("DELETE FROM sales WHERE sale_id=?", (sid,))

    # -------- returns ----------
    def record_return(self, *, sid: str, date: str, created_by: int | None, lines: list[dict], notes: str | None):
        with self.conn:
            for ln in lines:  # {item_id, product_id, uom_id, qty_return}
                self.conn.execute("""
                    INSERT INTO inventory_transactions(product_id, quantity, uom_id, transaction_type,
                        reference_table, reference_id, reference_item_id, date, notes, created_by)
                    VALUES (?, ?, ?, 'sale_return', 'sales', ?, ?, ?, ?, ?)""",
                    (ln["product_id"], ln["qty_return"], ln["uom_id"], sid, ln["item_id"], date, notes, created_by))

    def sale_return_totals(self, sale_id: str) -> dict:
        row = self.conn.execute("""
            SELECT
              COALESCE(SUM(CAST(it.quantity AS REAL)), 0.0) AS qty_returned,
              COALESCE(SUM(
                CAST(it.quantity AS REAL) *
                (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL))
              ), 0.0) AS value_returned
            FROM inventory_transactions it
            JOIN sale_items si ON si.item_id = it.reference_item_id
            WHERE it.reference_table='sales'
              AND it.reference_id=? AND it.transaction_type='sale_return'
        """, (sale_id,)).fetchone()
        return {"qty": float(row["qty_returned"]), "value": float(row["value_returned"])}

    # -------- payments ----------
    def apply_payment(self, *, sid: str, amount: float):
        r = self.conn.execute("SELECT total_amount, paid_amount FROM sales WHERE sale_id=?", (sid,)).fetchone()
        if not r: return
        paid = float(r["paid_amount"]) + float(amount)
        total = float(r["total_amount"])
        status = "paid" if paid >= total else ("partial" if paid > 0 else "unpaid")
        with self.conn:
            self.conn.execute("UPDATE sales SET paid_amount=?, payment_status=? WHERE sale_id=?", (paid, status, sid))

    def apply_refund(self, *, sid: str, amount: float):
        """
        Reduce paid_amount by 'amount' (not below zero) and update payment_status accordingly.
        Useful when issuing a cash refund instead of store credit.
        """
        row = self.conn.execute(
            "SELECT CAST(paid_amount AS REAL) AS paid, CAST(total_amount AS REAL) AS total FROM sales WHERE sale_id=?",
            (sid,)
        ).fetchone()
        if not row: 
            return
        new_paid = max(0.0, float(row["paid"]) - float(amount))
        status = "paid" if new_paid >= float(row["total"]) else ("partial" if new_paid > 0 else "unpaid")
        with self.conn:
            self.conn.execute("UPDATE sales SET paid_amount=?, payment_status=? WHERE sale_id=?", (new_paid, status, sid))

    # add inside class SalesRepo
    def get_sale_totals(self, sale_id: str) -> dict:
        """
        Returns subtotal_before_order_discount and calculated_total_amount
        from the 'sale_detailed_totals' view for correct proration.
        """
        row = self.conn.execute("""
            SELECT CAST(subtotal_before_order_discount AS REAL) AS net_subtotal,
                CAST(calculated_total_amount        AS REAL) AS total_after_od
            FROM sale_detailed_totals
            WHERE sale_id = ?
        """, (sale_id,)).fetchone()
        return row or {"net_subtotal": 0.0, "total_after_od": 0.0}
