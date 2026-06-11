from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable, Optional

from .inventory_repo import next_inventory_txn_seq, rebuild_dirty_valuations


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
    """
    Sales + Quotations repository.

    Key behavior:
      - SALES are rows with sales.doc_type='sale' and carry inventory postings.
      - QUOTATIONS are rows with sales.doc_type='quotation'; they have items but NO inventory,
        and must keep (payment_status='unpaid', paid_amount=0, advance_payment_applied=0).
      - Payments roll-up (paid_amount/payment_status) comes from sale_payments triggers.
        Header math helpers are deprecated and must not be used from UI.
    """

    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn

    # ---------------------------------------------------------------------
    # READ — SALES
    # ---------------------------------------------------------------------
    def list_sales(self) -> list[dict]:
        """
        List only real SALES (doc_type='sale').
        """
        sql = """
        SELECT s.sale_id, s.date, s.customer_id, c.name AS customer_name,
               CAST(s.total_amount AS REAL)   AS total_amount,
               CAST(s.order_discount AS REAL) AS order_discount,
               CAST(s.paid_amount AS REAL)    AS paid_amount,
               s.payment_status, s.notes
        FROM sales s
        JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.doc_type = 'sale'
        ORDER BY DATE(s.date) DESC, s.sale_id DESC
        """
        return self.conn.execute(sql).fetchall()

    def search_sales(
        self,
        query: str = "",
        date: str | None = None,
        *,
        doc_type: str = "sale",   # 'sale' (default) or 'quotation'
    ) -> list[dict]:
        """
        Search within SALES by default.
        Pass doc_type='quotation' to search quotations.
        """
        where = ["s.doc_type = ?"]
        params: list = [doc_type]

        if query:
            where.append("(s.sale_id LIKE ? OR c.name LIKE ?)")
            params += [f"%{query}%", f"%{query}%"]

        if date:
            where.append("DATE(s.date) = DATE(?)")
            params.append(date)

        sql = """
          SELECT s.sale_id, s.date, c.name AS customer_name,
                 CAST(s.total_amount AS REAL) AS total_amount,
                 CAST(s.paid_amount AS REAL)  AS paid_amount,
                 s.payment_status
          FROM sales s
          JOIN customers c ON c.customer_id = s.customer_id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY DATE(s.date) DESC, s.sale_id DESC"

        return self.conn.execute(sql, params).fetchall()

    def get_header(self, sid: str) -> dict | None:
        return self.conn.execute("SELECT * FROM sales WHERE sale_id=?", (sid,)).fetchone()

    def has_customer_locking_activity(self, sale_id: str) -> bool:
        row = self.conn.execute(
            """
            SELECT CASE WHEN
              EXISTS (
                SELECT 1 FROM sale_payments sp
                WHERE sp.sale_id = ?
              )
              OR EXISTS (
                SELECT 1 FROM customer_advances ca
                WHERE ca.source_id = ?
                  AND ca.source_type IN ('applied_to_sale', 'return_credit')
              )
              OR EXISTS (
                SELECT 1 FROM inventory_transactions it
                WHERE it.transaction_type = 'sale_return'
                  AND it.reference_table = 'sales'
                  AND it.reference_id = ?
              )
            THEN 1 ELSE 0 END AS locked
            """,
            (sale_id, sale_id, sale_id),
        ).fetchone()
        return bool(row and row["locked"])

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

    # ---------------------------------------------------------------------
    # READ — QUOTATIONS
    # ---------------------------------------------------------------------
    def list_quotations(self) -> list[dict]:
        """
        List only QUOTATIONS (doc_type='quotation').
        """
        sql = """
        SELECT s.sale_id, s.date, s.customer_id, c.name AS customer_name,
               CAST(s.total_amount AS REAL)   AS total_amount,
               CAST(s.order_discount AS REAL) AS order_discount,
               s.quotation_status,
               s.notes
        FROM sales s
        JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.doc_type = 'quotation'
        ORDER BY DATE(s.date) DESC, s.sale_id DESC
        """
        return self.conn.execute(sql).fetchall()

    # ---------------------------------------------------------------------
    # INTERNAL WRITES
    # ---------------------------------------------------------------------
    def _insert_header(self, h: SaleHeader):
        """
        Insert a SALE header (doc_type defaults to 'sale' in schema).
        """
        self.conn.execute(
            """
            INSERT INTO sales (
                sale_id, customer_id, date,
                total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied,
                notes, created_by, source_type, source_id
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                h.sale_id,
                h.customer_id,
                h.date,
                h.total_amount,
                h.order_discount,
                h.payment_status,
                h.paid_amount,
                h.advance_payment_applied,
                h.notes,
                h.created_by,
                h.source_type,
                h.source_id,
            ),
        )

    def _insert_item(self, it: SaleItem) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO sale_items (
                sale_id, product_id, quantity, uom_id, unit_price, item_discount
            ) VALUES (?,?,?,?,?,?)
            """,
            (it.sale_id, it.product_id, it.quantity, it.uom_id, it.unit_price, it.item_discount),
        )
        return int(cur.lastrowid)

    def _insert_inventory_sale(
        self,
        *,
        item_id: int,
        product_id: int,
        uom_id: int,
        qty: float,
        sid: str,
        date: str,
        created_by: int | None,
        notes: str | None,
    ):
        self.conn.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id,
                date, txn_seq, notes, created_by
            )
            VALUES (?, ?, ?, 'sale', 'sales', ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                qty,
                uom_id,
                sid,
                item_id,
                date,
                next_inventory_txn_seq(self.conn, date),
                notes,
                created_by,
            ),
        )

    def _delete_sale_content(self, sid: str):
        self.conn.execute(
            "DELETE FROM inventory_transactions WHERE reference_table='sales' AND reference_id=?",
            (sid,),
        )
        self.conn.execute("DELETE FROM sale_items WHERE sale_id=?", (sid,))

    def _refresh_sale_payment_status(self, sid: str) -> None:
        self.conn.execute(
            """
            UPDATE sales
               SET payment_status = CASE
                 WHEN COALESCE((
                   SELECT remaining_due
                   FROM sale_receivable_totals
                   WHERE sale_id = sales.sale_id
                 ), 0.0) <= 1e-9 THEN 'paid'
                 WHEN COALESCE(CAST(paid_amount AS REAL), 0.0)
                      + COALESCE(CAST(advance_payment_applied AS REAL), 0.0) > 1e-9 THEN 'partial'
                 ELSE 'unpaid'
               END
             WHERE sale_id = ? AND doc_type = 'sale'
            """,
            (sid,),
        )

    # ---------------------------------------------------------------------
    # WRITE — SALES (doc_type='sale')
    # ---------------------------------------------------------------------
    def create_sale(self, header: SaleHeader, items: Iterable[SaleItem]):
        """
        Create a SALE (doc_type='sale') and post inventory for each item.
        Payments must be recorded via SalePaymentsRepo (not header math).
        """
        with self.conn:
            self._insert_header(header)
            for it in items:
                it.sale_id = header.sale_id
                item_id = self._insert_item(it)
                self._insert_inventory_sale(
                    item_id=item_id,
                    product_id=it.product_id,
                    uom_id=it.uom_id,
                    qty=it.quantity,
                    sid=header.sale_id,
                    date=header.date,
                    created_by=header.created_by,
                    notes=header.notes,
                )
            self._refresh_sale_payment_status(header.sale_id)
            rebuild_dirty_valuations(self.conn)

    def update_sale(self, header: SaleHeader, items: Iterable[SaleItem]):
        """
        Update a SALE (doc_type must be 'sale'). Rebuild items & inventory.
        """
        with self.conn:
            # Ensure we’re editing a sale row
            row = self.conn.execute(
                "SELECT doc_type, customer_id FROM sales WHERE sale_id=?",
                (header.sale_id,),
            ).fetchone()
            if not row or row["doc_type"] != "sale":
                raise ValueError("update_sale() requires an existing sale (doc_type='sale').")
            if self.conn.execute(
                """
                SELECT 1 FROM inventory_transactions
                WHERE transaction_type='sale_return'
                  AND reference_table='sales'
                  AND reference_id=?
                LIMIT 1
                """,
                (header.sale_id,),
            ).fetchone():
                raise ValueError("Cannot edit a sale after returns exist")
            if (
                int(row["customer_id"]) != int(header.customer_id)
                and self.has_customer_locking_activity(header.sale_id)
            ):
                raise ValueError(
                    "Cannot change the sale customer after payments, credits, or returns exist"
                )

            self.conn.execute(
                """
                UPDATE sales
                   SET customer_id=?,
                       date=?,
                       total_amount=?,
                       order_discount=?,
                       notes=?,
                       created_by=?,
                       source_type=?,
                       source_id=?
                 WHERE sale_id=?
                """,
                (
                    header.customer_id,
                    header.date,
                    header.total_amount,
                    header.order_discount,
                    header.notes,
                    header.created_by,
                    header.source_type,
                    header.source_id,
                    header.sale_id,
                ),
            )

            self._delete_sale_content(header.sale_id)
            for it in items:
                it.sale_id = header.sale_id
                item_id = self._insert_item(it)
                self._insert_inventory_sale(
                    item_id=item_id,
                    product_id=it.product_id,
                    uom_id=it.uom_id,
                    qty=it.quantity,
                    sid=header.sale_id,
                    date=header.date,
                    created_by=header.created_by,
                    notes=header.notes,
                )
            self._refresh_sale_payment_status(header.sale_id)
            rebuild_dirty_valuations(self.conn)

    def delete_sale(self, sid: str):
        with self.conn:
            self._delete_sale_content(sid)
            self.conn.execute("DELETE FROM sales WHERE sale_id=?", (sid,))
            rebuild_dirty_valuations(self.conn)

    # ---------------------------------------------------------------------
    # WRITE — QUOTATIONS (doc_type='quotation')
    # ---------------------------------------------------------------------
    def create_quotation(
        self,
        header: SaleHeader,
        items: Iterable[SaleItem],
        *,
        quotation_status: str = "draft",
        expiry_date: Optional[str] = None,  # keep optional; schema allows
    ) -> None:
        """
        Create a QUOTATION: insert sales row with doc_type='quotation', quotation_status,
        zeroed payment fields, and items — NO inventory postings.
        """
        with self.conn:
            # Insert header explicitly as quotation (enforce payment fields per schema)
            self.conn.execute(
                """
                INSERT INTO sales (
                    sale_id, customer_id, date,
                    total_amount, order_discount,
                    payment_status, paid_amount, advance_payment_applied,
                    notes, created_by, source_type, source_id,
                    doc_type, quotation_status, expiry_date
                )
                VALUES (?, ?, ?, ?, ?, 'unpaid', 0.0, 0.0, ?, ?, 'quotation', ?, 'quotation', ?, ?)
                """,
                (
                    header.sale_id,
                    header.customer_id,
                    header.date,
                    header.total_amount,
                    header.order_discount,
                    header.notes,
                    header.created_by,
                    header.source_id,         # keep source_id if you link drafts; else None
                    quotation_status,         # must be one of: draft/sent/accepted/expired/cancelled
                    expiry_date,
                ),
            )

            # Insert items only (no inventory for quotations)
            for it in items:
                it.sale_id = header.sale_id
                self._insert_item(it)

    def update_quotation(
        self,
        header: SaleHeader,
        items: Iterable[SaleItem],
        *,
        quotation_status: Optional[str] = None,
        expiry_date: Optional[str] = None,
    ) -> None:
        """
        Update a QUOTATION: rebuild items; keep doc_type='quotation';
        enforce payment fields to zero/unpaid.
        """
        with self.conn:
            row = self.conn.execute("SELECT doc_type FROM sales WHERE sale_id=?", (header.sale_id,)).fetchone()
            if not row or row["doc_type"] != "quotation":
                raise ValueError("update_quotation() requires an existing quotation (doc_type='quotation').")

            self.conn.execute(
                """
                UPDATE sales
                   SET customer_id=?,
                       date=?,
                       total_amount=?,
                       order_discount=?,
                       payment_status='unpaid',
                       paid_amount=0.0,
                       advance_payment_applied=0.0,
                       notes=?,
                       created_by=?,
                       source_type=?,           -- you may set 'direct' or keep previous
                       source_id=?,             -- optional linkage while in quotation phase
                       quotation_status=COALESCE(?, quotation_status),
                       expiry_date=COALESCE(?, expiry_date)
                 WHERE sale_id=? AND doc_type='quotation'
                """,
                (
                    header.customer_id,
                    header.date,
                    header.total_amount,
                    header.order_discount,
                    header.notes,
                    header.created_by,
                    header.source_type,
                    header.source_id,
                    quotation_status,
                    expiry_date,
                    header.sale_id,
                ),
            )

            # Rebuild items (no inventory)
            self.conn.execute("DELETE FROM sale_items WHERE sale_id=?", (header.sale_id,))
            for it in items:
                it.sale_id = header.sale_id
                self._insert_item(it)

    # ---------------------------------------------------------------------
    # CONVERSION — QUOTATION ➜ SALE
    # ---------------------------------------------------------------------
    def convert_quotation_to_sale(
        self,
        qo_id: str,
        new_so_id: str,
        date: str,
        created_by: Optional[int],
    ) -> None:
        """
        Create a SALE from an existing QUOTATION:
          - Insert new sales row (doc_type='sale', source_type='quotation', source_id=qo_id)
          - Copy items from quotation to new sale
          - Post inventory for each new sale item
          - Mark quotation as converted (quotation_status='accepted')
        """
        with self.conn:
            # Fetch quotation header
            qh = self.conn.execute(
                "SELECT * FROM sales WHERE sale_id=? AND doc_type='quotation'",
                (qo_id,),
            ).fetchone()
            if not qh:
                raise ValueError(f"Quotation not found: {qo_id}")

            # Optionally re-derive totals from view; fallback to header values
            tot = self.conn.execute(
                """
                SELECT CAST(calculated_total_amount AS REAL) AS total_after_od
                FROM sale_detailed_totals WHERE sale_id=?
                """,
                (qo_id,),
            ).fetchone()
            total_amount = float(tot["total_after_od"]) if tot and tot["total_after_od"] is not None else float(qh["total_amount"])

            # Insert new SALE header (doc_type defaults to 'sale')
            self.conn.execute(
                """
                INSERT INTO sales (
                    sale_id, customer_id, date,
                    total_amount, order_discount,
                    payment_status, paid_amount, advance_payment_applied,
                    notes, created_by, source_type, source_id
                )
                VALUES (?, ?, ?, ?, ?, 'unpaid', 0.0, 0.0, ?, ?, 'quotation', ?)
                """,
                (
                    new_so_id,
                    int(qh["customer_id"]),
                    date,
                    total_amount,
                    float(qh["order_discount"] or 0.0),
                    qh["notes"],
                    created_by,
                    qo_id,
                ),
            )

            # Copy items from quotation
            q_items = self.conn.execute(
                """
                SELECT product_id,
                       CAST(quantity AS REAL)      AS quantity,
                       uom_id,
                       CAST(unit_price AS REAL)    AS unit_price,
                       CAST(item_discount AS REAL) AS item_discount
                  FROM sale_items
                 WHERE sale_id=?
                 ORDER BY item_id
                """,
                (qo_id,),
            ).fetchall()

            # Insert items for the new sale + inventory postings
            for qi in q_items:
                cur = self.conn.execute(
                    """
                    INSERT INTO sale_items (
                        sale_id, product_id, quantity, uom_id, unit_price, item_discount
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_so_id,
                        int(qi["product_id"]),
                        float(qi["quantity"]),
                        int(qi["uom_id"]),
                        float(qi["unit_price"]),
                        float(qi["item_discount"]),
                    ),
                )
                new_item_id = int(cur.lastrowid)

                # Inventory posting for SALE
                self._insert_inventory_sale(
                    item_id=new_item_id,
                    product_id=int(qi["product_id"]),
                    uom_id=int(qi["uom_id"]),
                    qty=float(qi["quantity"]),
                    sid=new_so_id,
                    date=date,
                    created_by=created_by,
                    notes=f"Converted from quotation {qo_id}",
                )

            # Mark quotation as converted
            self.conn.execute(
                """
                UPDATE sales
                   SET quotation_status='accepted'
                 WHERE sale_id=? AND doc_type='quotation'
                """,
                (qo_id,),
            )

    # ---------------------------------------------------------------------
    # RETURNS (with settlement)
    # ---------------------------------------------------------------------
    def record_return(
        self,
        *,
        sid: str,
        date: str,
        created_by: int | None,
        lines: list[dict],
        notes: str | None,
        settlement: dict | None = None,
    ) -> dict:
        with self.conn:
            if not lines:
                raise ValueError("At least one return line is required")
            settlement_data = settlement or {}
            position_before = self.get_receivable_position(sid)
            remaining_due_before = position_before["remaining_due"]

            # Group requested returns per item to validate batch totals
            requested_per_item: dict[int, float] = {}
            for ln in lines:
                iid = int(ln["item_id"])
                requested_per_item[iid] = requested_per_item.get(iid, 0.0) + float(ln["qty_return"])

            # Validate against sold - already returned
            for item_id, batch_qty in requested_per_item.items():
                row = self.conn.execute(
                    """
                    SELECT
                      CAST(si.quantity AS REAL) AS sold_qty,
                      COALESCE((
                        SELECT SUM(CAST(it.quantity AS REAL))
                        FROM inventory_transactions it
                        WHERE it.transaction_type = 'sale_return'
                          AND it.reference_table = 'sales'
                          AND it.reference_id = ?
                          AND it.reference_item_id = si.item_id
                      ), 0.0) AS returned_so_far
                    FROM sale_items si
                    WHERE si.item_id = ? AND si.sale_id = ?
                    """,
                    (sid, item_id, sid),
                ).fetchone()
                if not row:
                    raise ValueError(f"Invalid sale item: {item_id} for sale {sid}")

                sold_qty = float(row["sold_qty"])
                returned_so_far = float(row["returned_so_far"])
                remaining = sold_qty - returned_so_far
                if batch_qty > remaining + 1e-9:
                    raise ValueError(
                        f"Return qty exceeds remaining for item {item_id}: requested {batch_qty:g}, remaining {remaining:g}"
                    )

            # Header for customer_id
            hdr = self.conn.execute(
                "SELECT customer_id, CAST(paid_amount AS REAL) AS paid_amount FROM sales WHERE sale_id=?",
                (sid,),
            ).fetchone()
            if not hdr:
                raise ValueError(f"Unknown sale_id: {sid}")
            customer_id = int(hdr["customer_id"])

            for ln in lines:
                chk = self.conn.execute(
                    "SELECT product_id, uom_id, CAST(unit_price AS REAL) AS unit_price, CAST(item_discount AS REAL) AS item_discount FROM sale_items WHERE item_id=? AND sale_id=?",
                    (ln["item_id"], sid),
                ).fetchone()
                if not chk:
                    raise ValueError(f"Sale item mismatch for item_id {ln['item_id']}")

            seq = next_inventory_txn_seq(self.conn, date)
            return_transaction_ids: list[int] = []

            # Insert inventory return rows
            for ln in lines:  # {item_id, product_id, uom_id, qty_return}
                # Verify the item exists and matches the sale
                chk = self.conn.execute(
                    "SELECT product_id, uom_id FROM sale_items WHERE item_id=? AND sale_id=?",
                    (ln["item_id"], sid),
                ).fetchone()
                if not chk:
                    raise ValueError(f"Sale item mismatch for item_id {ln['item_id']}")

                cur = self.conn.execute(
                    """
                    INSERT INTO inventory_transactions(
                        product_id, quantity, uom_id, transaction_type,
                        reference_table, reference_id, reference_item_id,
                        date, txn_seq, notes, created_by
                    )
                    VALUES (?, ?, ?, 'sale_return', 'sales', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ln["product_id"],
                        ln["qty_return"],
                        ln["uom_id"],
                        sid,
                        ln["item_id"],
                        date,
                        seq,
                        notes,
                        created_by,
                    ),
                )
                return_transaction_ids.append(int(cur.lastrowid))
                seq += 10
            rebuild_dirty_valuations(self.conn)

            placeholders = ",".join("?" for _ in return_transaction_ids)
            value_row = self.conn.execute(
                f"""
                SELECT COUNT(*) AS snapshot_count,
                       COALESCE(SUM(CAST(return_value AS REAL)), 0.0) AS return_value
                FROM sale_return_snapshots
                WHERE transaction_id IN ({placeholders})
                """,
                return_transaction_ids,
            ).fetchone()
            if int(value_row["snapshot_count"] or 0) != len(return_transaction_ids):
                raise sqlite3.IntegrityError("Sale return snapshot capture failed")
            final_return_value = float(value_row["return_value"] or 0.0)

            settlement_due = max(0.0, final_return_value - remaining_due_before)
            paid_before = float(hdr["paid_amount"] or 0.0)
            cash_cap = min(settlement_due, paid_before)
            requested_cash = float(settlement_data.get("cash_refund") or 0.0)
            if requested_cash < 0:
                raise ValueError("Cash refund cannot be negative.")
            cash_refund = min(requested_cash, cash_cap)
            credit_amount = max(0.0, settlement_due - cash_refund)

            if settlement_due > 0:

                if cash_refund > 0:
                    self.conn.execute(
                        """
                        INSERT INTO sale_payments (
                            sale_id, date, amount, method, instrument_type,
                            clearing_state, notes, created_by
                        ) VALUES (?, ?, ?, 'Cash', 'other', 'cleared', ?, ?)
                        """,
                        (
                            sid,
                            date,
                            -cash_refund,
                            settlement_data.get("refund_notes") or "[Return refund]",
                            created_by,
                        ),
                    )

                if credit_amount > 0:
                    self.conn.execute(
                        """
                        INSERT INTO customer_advances (
                            customer_id, tx_date, amount, source_type,
                            source_id, notes, created_by
                        ) VALUES (?, ?, ?, 'return_credit', ?, ?, ?)
                        """,
                        (
                            customer_id,
                            date,
                            credit_amount,
                            sid,
                            settlement_data.get("credit_notes") or "[Return credit]",
                            created_by,
                        ),
                    )

            self._refresh_sale_payment_status(sid)
            position_after = self.get_receivable_position(sid)
            status_row = self.conn.execute(
                "SELECT payment_status FROM sales WHERE sale_id=?",
                (sid,),
            ).fetchone()
            return {
                "return_value": final_return_value,
                "remaining_due_before_return": remaining_due_before,
                "settlement_due": settlement_due,
                "cash_refund_cap": cash_cap,
                "cash_refund": cash_refund,
                "credit_amount": credit_amount,
                "net_total_amount": position_after["net_total_amount"],
                "remaining_due_after_return": position_after["remaining_due"],
                "payment_status": status_row["payment_status"] if status_row else None,
            }

    def sale_return_totals(self, sale_id: str) -> dict:
        row = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(CAST(it.quantity AS REAL)), 0.0) AS qty_returned,
              COALESCE(SUM(CAST(srs.return_value AS REAL)), 0.0) AS value_returned
            FROM inventory_transactions it
            JOIN sale_return_snapshots srs ON srs.transaction_id = it.transaction_id
            WHERE it.reference_table='sales'
              AND it.reference_id=? AND it.transaction_type='sale_return'
            """,
            (sale_id,),
        ).fetchone()
        return {
            "qty": float(row["qty_returned"]),
            "value": float(row["value_returned"]),
        }

    def get_receivable_position(self, sale_id: str, return_value: float = 0.0) -> dict:
        row = self.conn.execute(
            """
            SELECT
              CAST(sdt.calculated_total_amount AS REAL) AS gross_total_amount,
              CAST(sdt.returned_value AS REAL) AS returned_value,
              CAST(sdt.net_total_amount AS REAL) AS net_total_amount,
              CAST(srt.paid_amount AS REAL) AS paid_amount,
              CAST(srt.advance_payment_applied AS REAL) AS advance_payment_applied,
              CAST(srt.remaining_due AS REAL) AS remaining_due
            FROM sale_detailed_totals sdt
            JOIN sale_receivable_totals srt ON srt.sale_id = sdt.sale_id
            WHERE sdt.sale_id = ?
            """,
            (sale_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown sale_id: {sale_id}")
        remaining = float(row["remaining_due"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        prospective_return = max(0.0, float(return_value or 0.0))
        settlement_due = max(0.0, prospective_return - remaining)
        return {
            "gross_total_amount": float(row["gross_total_amount"] or 0.0),
            "returned_value": float(row["returned_value"] or 0.0),
            "net_total_amount": float(row["net_total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": float(row["advance_payment_applied"] or 0.0),
            "remaining_due": remaining,
            "settlement_due": settlement_due,
            "cash_refund_cap": min(settlement_due, paid),
        }

    # ---------------------------------------------------------------------
    # PAYMENTS — HEADER MATH DEPRECATED
    # ---------------------------------------------------------------------
    def apply_payment(self, *, sid: str, amount: float):
        """
        Deprecated: Do not use.
        Use SalePaymentsRepo.record_payment(...) to insert receipts.
        Header roll-up is maintained by DB triggers on sale_payments.
        """
        raise NotImplementedError(
            "apply_payment is deprecated. Use SalePaymentsRepo.record_payment(...) instead."
        )

    def apply_refund(self, *, sid: str, amount: float):
        """
        Deprecated: Do not use.
        Cash refunds via returns should be represented by the agreed flow
        (e.g., adjust via business rules + payments model when enabled).
        """
        raise NotImplementedError(
            "apply_refund is deprecated. Use the payments/returns flow per policy."
        )

    # ---------------------------------------------------------------------
    # SAFE TOTALS — for OD proration in returns UI
    # ---------------------------------------------------------------------
    def get_sale_totals(self, sale_id: str) -> dict:
        """
        Returns subtotal_before_order_discount and calculated_total_amount
        from the 'sale_detailed_totals' view for correct proration.
        """
        row = self.conn.execute(
            """
            SELECT CAST(subtotal_before_order_discount AS REAL) AS net_subtotal,
                   CAST(calculated_total_amount AS REAL) AS total_after_od,
                   CAST(calculated_total_amount AS REAL) AS calculated_total_amount,
                   CAST(returned_value AS REAL) AS returned_value,
                   CAST(net_total_amount AS REAL) AS net_total_amount
            FROM sale_detailed_totals
            WHERE sale_id = ?
            """,
            (sale_id,),
        ).fetchone()
        return row or {
            "net_subtotal": 0.0,
            "total_after_od": 0.0,
            "calculated_total_amount": 0.0,
            "returned_value": 0.0,
            "net_total_amount": 0.0,
        }

    def list_by_customer(self, customer_id: int, doc_type: str = 'sale') -> list[sqlite3.Row]:
        """
        Return all sales for a given customer.
        """
        with self.conn:  # Ensure consistent connection handling
            cur = self.conn.execute(
                """
                SELECT s.sale_id,
                       srt.canonical_total_amount AS total_amount,
                       srt.paid_amount,
                       s.payment_status,
                       srt.advance_payment_applied,
                       srt.remaining_due
                  FROM sales s
                  JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
                 WHERE s.customer_id = ? AND s.doc_type = ?
                 ORDER BY s.date ASC, s.sale_id ASC;
                """,
                (customer_id, doc_type),
            )
            return cur.fetchall()

    def get_header_with_customer(self, sale_id: str) -> dict | None:
        """
        Get sale header with customer information joined.
        Returns a dictionary with sale fields and customer fields aliased with customer_ prefix.
        """
        sql = """
        SELECT s.*,
               c.name AS customer_name,
               c.contact_info AS customer_contact_info,
               c.address AS customer_address
          FROM sales s
          JOIN customers c ON c.customer_id = s.customer_id
         WHERE s.sale_id = ?
        """
        row = self.conn.execute(sql, (sale_id,)).fetchone()
        return dict(row) if row else None
