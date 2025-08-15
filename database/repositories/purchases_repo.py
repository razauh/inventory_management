from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable, Optional

# For settlements
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo


@dataclass
class PurchaseHeader:
    purchase_id: str
    vendor_id: int
    date: str
    total_amount: float
    order_discount: float
    payment_status: str
    paid_amount: float
    advance_payment_applied: float
    notes: str | None
    created_by: int | None


@dataclass
class PurchaseItem:
    item_id: int | None
    purchase_id: str
    product_id: int
    quantity: float
    uom_id: int
    purchase_price: float
    sale_price: float
    item_discount: float


class PurchasesRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- Query ----------
    def list_purchases(self) -> list[dict]:
        sql = """
        SELECT p.purchase_id, p.date, p.vendor_id, v.name AS vendor_name,
               CAST(p.total_amount AS REAL) AS total_amount,
               CAST(p.order_discount AS REAL) AS order_discount,
               p.payment_status, CAST(p.paid_amount AS REAL) AS paid_amount,
               CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
               p.notes
        FROM purchases p
        JOIN vendors v ON v.vendor_id = p.vendor_id
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        return self.conn.execute(sql).fetchall()

    def get_header(self, pid: str) -> dict | None:
        return self.conn.execute("SELECT * FROM purchases WHERE purchase_id=?", (pid,)).fetchone()

    def list_items(self, pid: str) -> list[dict]:
        sql = """
        SELECT pi.item_id, pi.purchase_id, pi.product_id, pr.name AS product_name,
               CAST(pi.quantity AS REAL) AS quantity, u.unit_name,
               pi.uom_id, CAST(pi.purchase_price AS REAL) AS purchase_price,
               CAST(pi.sale_price AS REAL) AS sale_price,
               CAST(pi.item_discount AS REAL) AS item_discount
        FROM purchase_items pi
        JOIN products pr ON pr.product_id = pi.product_id
        JOIN uoms u ON u.uom_id = pi.uom_id
        WHERE pi.purchase_id=?
        ORDER BY pi.item_id
        """
        return self.conn.execute(sql, (pid,)).fetchall()

    def get_returnable_for_items(self, purchase_id: str) -> list[dict]:
        """
        For each purchase_items row in a purchase, return:
          purchased_qty, returned_qty, remaining_returnable
        """
        sql = """
        SELECT
          pi.item_id,
          pi.product_id,
          pi.uom_id,
          CAST(SUM(pi.quantity) AS REAL) AS purchased_qty,
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='purchase_return'
              AND it.reference_table='purchases'
              AND it.reference_id = pi.purchase_id
              AND it.reference_item_id = pi.item_id
          ), 0.0) AS returned_qty
        FROM purchase_items pi
        WHERE pi.purchase_id = ?
        GROUP BY pi.item_id, pi.product_id, pi.uom_id, pi.purchase_id
        ORDER BY pi.item_id
        """
        rows = self.conn.execute(sql, (purchase_id,)).fetchall()
        out: list[dict] = []
        for r in rows:
            purchased = float(r["purchased_qty"])
            returned = float(r["returned_qty"])
            remaining = max(0.0, purchased - returned)
            out.append({
                "item_id": int(r["item_id"]),
                "product_id": int(r["product_id"]),
                "uom_id": int(r["uom_id"]),
                "purchased_qty": purchased,
                "returned_qty": returned,
                "remaining_returnable": remaining,
            })
        return out

    # ---------- Low-level inserts ----------
    def _insert_header(self, h: PurchaseHeader):
        self.conn.execute(
            """
            INSERT INTO purchases(
                purchase_id, vendor_id, date, total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied, notes, created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                h.purchase_id, h.vendor_id, h.date, h.total_amount, h.order_discount,
                h.payment_status, h.paid_amount, h.advance_payment_applied, h.notes, h.created_by,
            ),
        )

    def _insert_item(self, it: PurchaseItem) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO purchase_items(
                purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (it.purchase_id, it.product_id, it.quantity, it.uom_id, it.purchase_price, it.sale_price, it.item_discount),
        )
        return int(cur.lastrowid)

    def _insert_inventory_purchase(
        self, *, item_id: int, product_id: int, uom_id: int, qty: float,
        pid: str, date: str, created_by: int | None, notes: str | None,
    ):
        # Legacy helper (unused by the deterministic seq flow)
        self.conn.execute(
            """
            INSERT INTO inventory_transactions(
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id, date, notes, created_by
            )
            VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?, ?)
            """,
            (product_id, qty, uom_id, pid, item_id, date, notes, created_by),
        )

    # ---------- Create / Update ----------
    def create_purchase(self, header: PurchaseHeader, items: Iterable[PurchaseItem]):
        """
        - Recalculate totals (per-unit discount), minus order_discount.
        - Insert header with payment_status='unpaid', paid_amount=0, advance_payment_applied=0.
        - Insert purchase_items.
        - Insert inventory_transactions rows (transaction_type='purchase') with sequential txn_seq (10, 20, ...).
        - No commit here; caller controls the transaction boundary.
        """
        items_list = list(items)

        # 1) Totals
        order_disc = float(header.order_discount or 0.0)
        subtotal = 0.0
        for it in items_list:
            line_total = float(it.quantity) * (float(it.purchase_price) - float(it.item_discount or 0.0))
            subtotal += line_total
        total_amount = max(0.0, subtotal - order_disc)

        # 2) Header
        self.conn.execute(
            """
            INSERT INTO purchases (
                purchase_id, vendor_id, date, total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied, notes, created_by
            ) VALUES (?, ?, ?, ?, ?, 'unpaid', 0, 0, ?, ?)
            """,
            (header.purchase_id, header.vendor_id, header.date, total_amount, order_disc, header.notes, header.created_by),
        )

        # 3) Next txn_seq for this date
        row = self.conn.execute(
            "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
            (header.date,),
        ).fetchone()
        max_seq = (row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) or 0
        next_seq = int(max_seq) + 10

        # 4) Items + inventory rows
        for it in items_list:
            it.purchase_id = header.purchase_id
            cur = self.conn.execute(
                """
                INSERT INTO purchase_items(
                    purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (header.purchase_id, it.product_id, it.quantity, it.uom_id, it.purchase_price, it.sale_price, it.item_discount or 0.0),
            )
            item_id = int(cur.lastrowid)

            self.conn.execute(
                """
                INSERT INTO inventory_transactions (
                    product_id, quantity, uom_id, transaction_type,
                    reference_table, reference_id, reference_item_id,
                    date, txn_seq, notes, created_by
                )
                VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.product_id, it.quantity, it.uom_id,
                    header.purchase_id, item_id,
                    header.date, next_seq,
                    header.notes, header.created_by,
                ),
            )
            next_seq += 10

    def update_purchase(self, header: PurchaseHeader, items: Iterable[PurchaseItem]):
        """
        Modify behavior:
          - Recompute totals from provided items.
          - Update header fields (vendor_id, date, order_discount, notes, total_amount).
          - Delete ONLY inventory_transactions for this purchase with transaction_type='purchase'.
          - Delete and re-insert purchase_items.
          - Re-insert corresponding inventory_transactions with new sequential txn_seq.
          - Do NOT commit here. Do NOT touch 'purchase_return' rows.
        """
        items_list = list(items)

        # Totals
        order_disc = float(header.order_discount or 0.0)
        subtotal = 0.0
        for it in items_list:
            line_total = float(it.quantity) * (float(it.purchase_price) - float(it.item_discount or 0.0))
            subtotal += line_total
        total_amount = max(0.0, subtotal - order_disc)

        # 1) Update header
        self.conn.execute(
            """
            UPDATE purchases
               SET vendor_id=?,
                   date=?,
                   order_discount=?,
                   notes=?,
                   total_amount=?
             WHERE purchase_id=?
            """,
            (header.vendor_id, header.date, order_disc, header.notes, total_amount, header.purchase_id),
        )

        # 2) Remove ONLY purchase-line inventory rows (keep returns)
        self.conn.execute(
            """
            DELETE FROM inventory_transactions
             WHERE reference_table='purchases'
               AND reference_id=?
               AND transaction_type='purchase'
            """,
            (header.purchase_id,),
        )

        # 3) Delete items (full rebuild)
        self.conn.execute("DELETE FROM purchase_items WHERE purchase_id=?", (header.purchase_id,))

        # 4) Next txn_seq for the (possibly new) date
        row = self.conn.execute(
            "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
            (header.date,),
        ).fetchone()
        next_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10

        # 5) Re-insert items + inventory rows
        for it in items_list:
            it.purchase_id = header.purchase_id
            cur = self.conn.execute(
                """
                INSERT INTO purchase_items (
                    purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (header.purchase_id, it.product_id, it.quantity, it.uom_id, it.purchase_price, it.sale_price, it.item_discount or 0.0),
            )
            item_id = int(cur.lastrowid)

            self.conn.execute(
                """
                INSERT INTO inventory_transactions (
                    product_id, quantity, uom_id, transaction_type,
                    reference_table, reference_id, reference_item_id,
                    date, txn_seq, notes, created_by
                )
                VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.product_id, it.quantity, it.uom_id,
                    header.purchase_id, item_id,
                    header.date, next_seq,
                    header.notes, header.created_by,
                ),
            )
            next_seq += 10

    # ---------- Returns ----------
    def record_return(
        self,
        *,
        pid: str,
        date: str,
        created_by: Optional[int],
        lines: list[dict],
        notes: Optional[str],
        settlement: Optional[dict] = None,
    ):
        """
        Enhanced returns (no implicit commit):
          - Validates qty_return per line: qty_return <= (purchased - returned_so_far).
          - Inserts inventory_transactions with transaction_type='purchase_return' using a high txn_seq bucket
            (100, 110, ... for that date).
          - Computes monetary return value via purchase_return_valuations for inserted txns.
          - Settlement:
              * {'mode':'refund', ...} => negative purchase_payment
              * {'mode':'credit_note'} => vendor credit (return_credit)
        """
        if not lines:
            return

        # Header for vendor_id
        hdr = self.conn.execute("SELECT vendor_id FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
        if not hdr:
            raise ValueError(f"Unknown purchase_id: {pid}")
        vendor_id = int(hdr["vendor_id"] if isinstance(hdr, sqlite3.Row) else hdr[0])

        # Group requested returns per item to validate batch totals
        requested_per_item: dict[int, float] = {}
        for ln in lines:
            iid = int(ln["item_id"])
            requested_per_item[iid] = requested_per_item.get(iid, 0.0) + float(ln["qty_return"])

        # Validate against purchased - already returned
        for item_id, batch_qty in requested_per_item.items():
            row = self.conn.execute(
                """
                SELECT
                  CAST(pi.quantity AS REAL) AS purchased_qty,
                  COALESCE((
                    SELECT SUM(CAST(it.quantity AS REAL))
                    FROM inventory_transactions it
                    WHERE it.transaction_type = 'purchase_return'
                      AND it.reference_table = 'purchases'
                      AND it.reference_id = ?
                      AND it.reference_item_id = pi.item_id
                  ), 0.0) AS returned_so_far,
                  pi.product_id, pi.uom_id
                FROM purchase_items pi
                WHERE pi.item_id = ? AND pi.purchase_id = ?
                """,
                (pid, item_id, pid),
            ).fetchone()
            if not row:
                raise ValueError(f"Invalid purchase item: {item_id} for purchase {pid}")

            purchased_qty = float(row["purchased_qty"])
            returned_so_far = float(row["returned_so_far"])
            remaining = purchased_qty - returned_so_far
            if batch_qty > remaining + 1e-9:
                raise ValueError(
                    f"Return qty exceeds remaining for item {item_id}: requested {batch_qty:g}, remaining {remaining:g}"
                )

        # Determine starting txn_seq for the date; bump to at least 100
        row = self.conn.execute(
            "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
            (date,),
        ).fetchone()
        start_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10
        if start_seq < 100:
            start_seq = 100
        seq = start_seq

        # Insert return rows
        inserted_txn_ids: list[int] = []
        for ln in lines:
            chk = self.conn.execute(
                "SELECT product_id, uom_id FROM purchase_items WHERE item_id=? AND purchase_id=?",
                (ln["item_id"], pid),
            ).fetchone()
            if not chk:
                raise ValueError(f"Purchase item mismatch for item_id {ln['item_id']}")

            prod_id = int(chk["product_id"] if isinstance(chk, sqlite3.Row) else chk[0])
            uom_id = int(chk["uom_id"] if isinstance(chk, sqlite3.Row) else chk[1])

            cur = self.conn.execute(
                """
                INSERT INTO inventory_transactions(
                    product_id, quantity, uom_id, transaction_type,
                    reference_table, reference_id, reference_item_id,
                    date, txn_seq, notes, created_by
                )
                VALUES (?, ?, ?, 'purchase_return', 'purchases', ?, ?, ?, ?, ?, ?)
                """,
                (prod_id, float(ln["qty_return"]), uom_id, pid, int(ln["item_id"]), date, seq, notes, created_by),
            )
            inserted_txn_ids.append(int(cur.lastrowid))
            seq += 10

        # Compute return monetary value using the view for the inserted txns
        if inserted_txn_ids:
            placeholders = ",".join("?" for _ in inserted_txn_ids)
            val_row = self.conn.execute(
                f"""
                SELECT COALESCE(SUM(return_value), 0.0)
                FROM purchase_return_valuations
                WHERE transaction_id IN ({placeholders})
                """,
                inserted_txn_ids,
            ).fetchone()
            return_value = float(val_row[0] if val_row else 0.0)
        else:
            return_value = 0.0

        # Settlement handling (no commit here)
        if settlement and return_value > 0:
            mode = (settlement.get("mode") or "").lower()

            if mode in ("refund", "refund_now"):
                payments = PurchasePaymentsRepo(self.conn)
                payments.record_payment(
                    purchase_id=pid,
                    amount=-return_value,  # incoming refund
                    method=settlement.get("method") or "Cash",
                    bank_account_id=settlement.get("bank_account_id"),
                    vendor_bank_account_id=settlement.get("vendor_bank_account_id"),
                    instrument_type=settlement.get("instrument_type"),
                    instrument_no=settlement.get("instrument_no"),
                    instrument_date=settlement.get("instrument_date"),
                    deposited_date=settlement.get("deposited_date"),
                    cleared_date=settlement.get("cleared_date"),
                    clearing_state=settlement.get("clearing_state"),
                    ref_no=settlement.get("ref_no"),
                    notes=settlement.get("notes") or notes,
                    date=date,
                    created_by=created_by,
                )

            elif mode == "credit_note":
                vadv = VendorAdvancesRepo(self.conn)
                vadv.grant_credit(
                    vendor_id=vendor_id,
                    amount=return_value,
                    date=date,
                    notes=notes,
                    created_by=created_by,
                    source_id=pid,
                )

    # ---------- Hard delete ----------
    def _delete_purchase_content(self, pid: str):
        # remove inventory rows first (FK safety)
        self.conn.execute(
            "DELETE FROM inventory_transactions WHERE reference_table='purchases' AND reference_id=?",
            (pid,),
        )
        self.conn.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))

    def delete_purchase(self, pid: str):
        # no implicit commit; caller controls transaction
        self._delete_purchase_content(pid)
        self.conn.execute("DELETE FROM purchases WHERE purchase_id=?", (pid,))

    # ---------- Vendor-scoped listings & summaries ----------
    def list_purchases_by_vendor(
        self,
        vendor_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        sql = [
            "SELECT p.purchase_id, p.date, CAST(p.total_amount AS REAL) AS total_amount",
            "FROM purchases p",
            "WHERE p.vendor_id = ?",
        ]
        params: list[object] = [vendor_id]
        if date_from:
            sql.append("AND DATE(p.date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql.append("AND DATE(p.date) <= DATE(?)")
            params.append(date_to)
        sql.append("ORDER BY DATE(p.date) ASC, p.purchase_id ASC")

        cur = self.conn.execute("\n".join(sql), params)
        rows = cur.fetchall()
        out: list[dict] = []
        for r in rows:
            if isinstance(r, sqlite3.Row):
                out.append(dict(r))
            else:
                out.append({"purchase_id": r[0], "date": r[1], "total_amount": float(r[2])})
        return out

    def get_purchase_totals_for_vendor(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        row = self.conn.execute(
            "\n".join(
                [
                    """
                    SELECT
                      COALESCE(SUM(CAST(p.total_amount AS REAL)), 0.0)           AS purchases_total,
                      COALESCE(SUM(CAST(p.paid_amount AS REAL)), 0.0)             AS paid_total,
                      COALESCE(SUM(CAST(p.advance_payment_applied AS REAL)), 0.0) AS advance_applied_total
                    FROM purchases p
                    WHERE p.vendor_id = ?
                    """,
                    "AND DATE(p.date) >= DATE(?)" if date_from else "",
                    "AND DATE(p.date) <= DATE(?)" if date_to else "",
                ]
            ),
            ([vendor_id] + ([date_from] if date_from else []) + ([date_to] if date_to else [])),
        ).fetchone()

        return {
            "purchases_total": float(row["purchases_total"] if isinstance(row, sqlite3.Row) else row[0]),
            "paid_total": float(row["paid_total"] if isinstance(row, sqlite3.Row) else row[1]),
            "advance_applied_total": float(row["advance_applied_total"] if isinstance(row, sqlite3.Row) else row[2]),
        }

    def list_return_values_by_purchase(self, purchase_id: str) -> list[dict]:
        sql = """
        SELECT
          transaction_id,
          item_id,
          CAST(qty_returned AS REAL)  AS qty_returned,
          CAST(unit_buy_price AS REAL) AS unit_buy_price,
          CAST(unit_discount AS REAL)  AS unit_discount,
          CAST(return_value AS REAL)   AS return_value
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """
        return self.conn.execute(sql, (purchase_id,)).fetchall()
