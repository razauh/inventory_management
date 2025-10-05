from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable, Optional

# For settlements
from .sale_payments_repo import SalePaymentsRepo
from .customer_advances_repo import CustomerAdvancesRepo


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
                date, notes, created_by
            )
            VALUES (?, ?, ?, 'sale', 'sales', ?, ?, ?, ?, ?)
            """,
            (product_id, qty, uom_id, sid, item_id, date, notes, created_by),
        )

    def _delete_sale_content(self, sid: str):
        self.conn.execute(
            "DELETE FROM inventory_transactions WHERE reference_table='sales' AND reference_id=?",
            (sid,),
        )
        self.conn.execute("DELETE FROM sale_items WHERE sale_id=?", (sid,))

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

    def update_sale(self, header: SaleHeader, items: Iterable[SaleItem]):
        """
        Update a SALE (doc_type must be 'sale'). Rebuild items & inventory.
        """
        with self.conn:
            # Ensure we’re editing a sale row
            row = self.conn.execute("SELECT doc_type FROM sales WHERE sale_id=?", (header.sale_id,)).fetchone()
            if not row or row["doc_type"] != "sale":
                raise ValueError("update_sale() requires an existing sale (doc_type='sale').")

            self.conn.execute(
                """
                UPDATE sales
                   SET customer_id=?,
                       date=?,
                       total_amount=?,
                       order_discount=?,
                       payment_status=?,      -- maintained by triggers; UI should not hand-edit
                       paid_amount=?,         -- maintained by triggers; UI should not hand-edit
                       advance_payment_applied=?,
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
                    header.payment_status,
                    header.paid_amount,
                    header.advance_payment_applied,
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

    def delete_sale(self, sid: str):
        with self.conn:
            self._delete_sale_content(sid)
            self.conn.execute("DELETE FROM sales WHERE sale_id=?", (sid,))

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
    ):
        with self.conn:
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
            hdr = self.conn.execute("SELECT customer_id FROM sales WHERE sale_id=?", (sid,)).fetchone()
            if not hdr:
                raise ValueError(f"Unknown sale_id: {sid}")
            customer_id = int(hdr["customer_id"])

            # Calculate total return value with proration for order discount
            return_value = 0.0
            for ln in lines:  # {item_id, product_id, uom_id, qty_return}
                # Verify the item exists and matches the sale
                chk = self.conn.execute(
                    "SELECT product_id, uom_id, CAST(unit_price AS REAL) AS unit_price, CAST(item_discount AS REAL) AS item_discount FROM sale_items WHERE item_id=? AND sale_id=?",
                    (ln["item_id"], sid),
                ).fetchone()
                if not chk:
                    raise ValueError(f"Sale item mismatch for item_id {ln['item_id']}")

                unit_price = float(chk["unit_price"])
                item_discount = float(chk["item_discount"])
                qty_return = float(ln["qty_return"])
                
                # Calculate line value (net of item discount)
                line_value = (unit_price - item_discount) * qty_return
                return_value += line_value

            # Apply proration for order discount if needed
            totals = self.get_sale_totals(sid)
            net_subtotal = totals["net_subtotal"]  # Before order discount
            total_after_od = totals["total_after_od"]  # After order discount
            
            order_factor = 1.0
            if net_subtotal > 1e-9:  # Avoid division by zero
                order_factor = total_after_od / net_subtotal
            final_return_value = return_value * order_factor

            # Insert inventory return rows
            for ln in lines:  # {item_id, product_id, uom_id, qty_return}
                # Verify the item exists and matches the sale
                chk = self.conn.execute(
                    "SELECT product_id, uom_id FROM sale_items WHERE item_id=? AND sale_id=?",
                    (ln["item_id"], sid),
                ).fetchone()
                if not chk:
                    raise ValueError(f"Sale item mismatch for item_id {ln['item_id']}")

                self.conn.execute(
                    """
                    INSERT INTO inventory_transactions(
                        product_id, quantity, uom_id, transaction_type,
                        reference_table, reference_id, reference_item_id,
                        date, notes, created_by
                    )
                    VALUES (?, ?, ?, 'sale_return', 'sales', ?, ?, ?, ?, ?)
                    """,
                    (
                        ln["product_id"],
                        ln["qty_return"],
                        ln["uom_id"],
                        sid,
                        ln["item_id"],
                        date,
                        notes,
                        created_by,
                    ),
                )

            # Settlement handling (if applicable)
            if settlement and final_return_value > 0:
                mode = (settlement.get("mode") or "").lower()
                if mode in ("refund", "refund_now"):
                    payments = SalePaymentsRepo(self.conn)
                    payments.record_payment(
                        sale_id=sid,
                        amount=-final_return_value,  # incoming refund (negative)
                        method=settlement.get("method") or "Cash",
                        bank_account_id=settlement.get("bank_account_id"),
                        customer_bank_account_id=settlement.get("customer_bank_account_id"),
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
                    cadv = CustomerAdvancesRepo(self.conn)
                    cadv.grant_credit(
                        customer_id=customer_id,
                        amount=final_return_value,
                        date=date,
                        notes=notes,
                        created_by=created_by,
                        source_id=sid,
                        # Keep return credits explicitly labeled
                        source_type="return_credit",
                    )

    def sale_return_totals(self, sale_id: str) -> dict:
        row = self.conn.execute(
            """
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
            """,
            (sale_id,),
        ).fetchone()
        return {
            "qty": float(row["qty_returned"]),
            "value": float(row["value_returned"]),
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
                   CAST(calculated_total_amount        AS REAL) AS total_after_od
            FROM sale_detailed_totals
            WHERE sale_id = ?
            """,
            (sale_id,),
        ).fetchone()
        return row or {"net_subtotal": 0.0, "total_after_od": 0.0}
