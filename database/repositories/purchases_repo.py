from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable, Optional

# For settlements
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
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
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

    def has_vendor_locking_activity(self, purchase_id: str) -> bool:
        row = self.conn.execute(
            """
            SELECT CASE WHEN
              EXISTS (
                SELECT 1 FROM purchase_payments pp
                WHERE pp.purchase_id = ?
              )
              OR EXISTS (
                SELECT 1 FROM vendor_advances va
                WHERE va.source_id = ?
                  AND va.source_type IN ('applied_to_purchase', 'return_credit')
              )
              OR EXISTS (
                SELECT 1 FROM inventory_transactions it
                WHERE it.transaction_type = 'purchase_return'
                  AND it.reference_table = 'purchases'
                  AND it.reference_id = ?
              )
              OR EXISTS (
                SELECT 1 FROM purchase_refunds pr
                WHERE pr.purchase_id = ?
              )
            THEN 1 ELSE 0 END AS locked
            """,
            (purchase_id, purchase_id, purchase_id, purchase_id),
        ).fetchone()
        return bool(row and row["locked"])

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
        Update retained purchase items in place so return transactions keep their
        reference_item_id. Returned lines cannot be removed, switched to another
        product/UoM, or reduced below the quantity already returned.
        """
        items_list = list(items)

        current_header = self.get_header(header.purchase_id)
        if not current_header:
            raise ValueError(f"Unknown purchase_id: {header.purchase_id}")
        if (
            int(current_header["vendor_id"]) != int(header.vendor_id)
            and self.has_vendor_locking_activity(header.purchase_id)
        ):
            raise ValueError(
                "Cannot change the purchase vendor after payments, credits, or returns exist"
            )

        existing_rows = self.conn.execute(
            """
            SELECT
              pi.item_id,
              pi.product_id,
              pi.uom_id,
              COALESCE((
                SELECT SUM(CAST(it.quantity AS REAL))
                FROM inventory_transactions it
                WHERE it.transaction_type='purchase_return'
                  AND it.reference_table='purchases'
                  AND it.reference_id=pi.purchase_id
                  AND it.reference_item_id=pi.item_id
              ), 0.0) AS returned_qty
            FROM purchase_items pi
            WHERE pi.purchase_id=?
            """,
            (header.purchase_id,),
        ).fetchall()
        existing = {int(row["item_id"]): row for row in existing_rows}
        retained_ids: set[int] = set()

        for it in items_list:
            if it.item_id is None:
                continue
            item_id = int(it.item_id)
            if item_id in retained_ids:
                raise ValueError(f"Duplicate purchase item: {item_id}")
            row = existing.get(item_id)
            if row is None:
                raise ValueError(f"Invalid purchase item: {item_id} for purchase {header.purchase_id}")
            retained_ids.add(item_id)

            returned_qty = float(row["returned_qty"])
            if float(it.quantity) + 1e-9 < returned_qty:
                raise ValueError(
                    f"Purchase item {item_id} quantity cannot be below already returned quantity {returned_qty:g}"
                )
            if returned_qty > 1e-9 and (
                int(it.product_id) != int(row["product_id"])
                or int(it.uom_id) != int(row["uom_id"])
            ):
                raise ValueError(f"Cannot change product or UoM for returned purchase item {item_id}")

        for item_id, row in existing.items():
            if item_id not in retained_ids and float(row["returned_qty"]) > 1e-9:
                raise ValueError(f"Cannot remove returned purchase item {item_id}")

        # Totals
        order_disc = float(header.order_discount or 0.0)
        subtotal = 0.0
        for it in items_list:
            line_total = float(it.quantity) * (float(it.purchase_price) - float(it.item_discount or 0.0))
            subtotal += line_total
        total_amount = max(0.0, subtotal - order_disc)

        settlement = self.conn.execute(
            """
            SELECT
              COALESCE((
                SELECT SUM(CAST(pp.amount AS REAL))
                FROM purchase_payments pp
                WHERE pp.purchase_id = ?
                  AND pp.clearing_state = 'cleared'
              ), 0.0) AS cleared_paid,
              COALESCE((
                SELECT SUM(-CAST(va.amount AS REAL))
                FROM vendor_advances va
                WHERE va.source_type = 'applied_to_purchase'
                  AND va.source_id = ?
              ), 0.0) AS advance_applied,
              COALESCE((
                SELECT SUM(CAST(prv.return_value AS REAL))
                FROM purchase_return_valuations prv
                WHERE prv.purchase_id = ?
              ), 0.0) AS returned_value,
              COALESCE((
                SELECT SUM(CAST(pr.amount AS REAL))
                FROM purchase_refunds pr
                WHERE pr.purchase_id = ?
                  AND pr.clearing_state = 'cleared'
              ), 0.0) AS refunded_value,
              COALESCE((
                SELECT SUM(CAST(va.amount AS REAL))
                FROM vendor_advances va
                WHERE va.source_type = 'return_credit'
                  AND va.source_id = ?
              ), 0.0) AS return_credit_value
            """,
            (
                header.purchase_id,
                header.purchase_id,
                header.purchase_id,
                header.purchase_id,
                header.purchase_id,
            ),
        ).fetchone()
        proposed_net_total = max(0.0, total_amount - float(settlement["returned_value"] or 0.0))
        settled_amount = (
            float(settlement["cleared_paid"] or 0.0)
            + float(settlement["advance_applied"] or 0.0)
            - float(settlement["refunded_value"] or 0.0)
            - float(settlement["return_credit_value"] or 0.0)
        )
        if proposed_net_total + 1e-9 < settled_amount:
            raise ValueError(
                "Cannot reduce purchase total below settled amount: "
                f"proposed net total {proposed_net_total:.2f}, "
                f"settled amount {settled_amount:.2f}"
            )

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

        # Rebuild purchase inventory rows while preserving purchase item identity.
        self.conn.execute(
            """
            DELETE FROM inventory_transactions
             WHERE reference_table='purchases'
               AND reference_id=?
               AND transaction_type='purchase'
            """,
            (header.purchase_id,),
        )

        for item_id in set(existing) - retained_ids:
            self.conn.execute(
                "DELETE FROM purchase_items WHERE item_id=? AND purchase_id=?",
                (item_id, header.purchase_id),
            )

        # 4) Next txn_seq for the (possibly new) date
        row = self.conn.execute(
            "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
            (header.date,),
        ).fetchone()
        next_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10

        # Update retained items and insert new items, then rebuild purchase inventory rows.
        for it in items_list:
            it.purchase_id = header.purchase_id
            if it.item_id is None:
                cur = self.conn.execute(
                    """
                    INSERT INTO purchase_items (
                        purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (header.purchase_id, it.product_id, it.quantity, it.uom_id, it.purchase_price, it.sale_price, it.item_discount or 0.0),
                )
                item_id = int(cur.lastrowid)
            else:
                item_id = int(it.item_id)
                self.conn.execute(
                    """
                    UPDATE purchase_items
                       SET product_id=?, quantity=?, uom_id=?, purchase_price=?, sale_price=?, item_discount=?
                     WHERE item_id=? AND purchase_id=?
                    """,
                    (
                        it.product_id, it.quantity, it.uom_id, it.purchase_price,
                        it.sale_price, it.item_discount or 0.0, item_id, header.purchase_id,
                    ),
                )

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

        self.update_header_totals(header.purchase_id)

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
        savepoint = "purchase_return_record"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            self._record_return(
                pid=pid,
                date=date,
                created_by=created_by,
                lines=lines,
                notes=notes,
                settlement=settlement,
            )
            self.update_header_totals(pid)
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    def _record_return(
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
          - Verifies immutable valuation snapshots were captured for every inserted transaction.
          - Computes monetary return value exclusively from those snapshots.
          - Settlement:
              * {'mode':'refund'/'refund_now', ...} => received vendor refund
              * {'mode':'credit_note'} => excess funded amount as vendor credit
        """
        if not lines:
            return

        # Header for vendor_id
        hdr = self.conn.execute("SELECT vendor_id FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
        if not hdr:
            raise ValueError(f"Unknown purchase_id: {pid}")
        vendor_id = int(hdr["vendor_id"] if isinstance(hdr, sqlite3.Row) else hdr[0])

        mode = (settlement.get("mode") or "").lower() if settlement else ""
        if mode == "refund":
            mode = "refund_now"

        # Group requested returns per item to validate batch totals
        requested_per_item: dict[int, float] = {}
        for ln in lines:
            iid = int(ln["item_id"])
            requested_per_item[iid] = requested_per_item.get(iid, 0.0) + float(ln["qty_return"])

        totals_row = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(
                CAST(pi.quantity AS REAL) *
                MAX(0.0, CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL))
              ), 0.0) AS subtotal,
              COALESCE(CAST(p.order_discount AS REAL), 0.0) AS order_discount
            FROM purchases p
            LEFT JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?
            GROUP BY p.purchase_id
            """,
            (pid,),
        ).fetchone()
        purchase_subtotal = float(totals_row["subtotal"] or 0.0) if totals_row else 0.0
        order_discount = float(totals_row["order_discount"] or 0.0) if totals_row else 0.0
        effective_order_discount = min(max(0.0, order_discount), purchase_subtotal)
        return_value_factor = (
            (purchase_subtotal - effective_order_discount) / purchase_subtotal
            if purchase_subtotal > 0.0
            else 0.0
        )
        requested_return_value = 0.0

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
                  pi.product_id, pi.uom_id,
                  CAST(pi.purchase_price AS REAL) AS purchase_price,
                  CAST(pi.item_discount AS REAL) AS item_discount
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

            requested_return_value += batch_qty * return_value_factor * max(
                0.0,
                float(row["purchase_price"] or 0.0)
                - float(row["item_discount"] or 0.0),
            )

            # Additional stock check: ensure return doesn't exceed current on-hand stock
            product_id = int(row["product_id"])
            uom_id = int(row["uom_id"])

            # Get the factor to convert to base units
            factor_row = self.conn.execute(
                """
                SELECT COALESCE(CAST(factor_to_base AS REAL), 1.0) AS factor
                FROM product_uoms
                WHERE product_id=? AND uom_id=?
                """,
                (product_id, uom_id),
            ).fetchone()
            factor = float(factor_row["factor"] if factor_row else 1.0)
            return_qty_base = batch_qty * factor

            # Get current stock from v_stock_on_hand
            stock_row = self.conn.execute(
                "SELECT qty_in_base FROM v_stock_on_hand WHERE product_id=?",
                (product_id,),
            ).fetchone()
            on_hand = float(stock_row["qty_in_base"] if stock_row else 0.0)

            # Check if return would make on-hand stock negative
            if return_qty_base > on_hand + 1e-9:
                raise ValueError(
                    f"Cannot return {batch_qty:g} units for product {product_id}: "
                    f"only {on_hand / factor:.2f} available in stock."
                )

        settlement_amount = 0.0
        if settlement and requested_return_value > 0 and mode in ("refund_now", "credit_note"):
            position = self.conn.execute(
                """
                SELECT
                  COALESCE(pdt.calculated_total_amount, p.total_amount, 0.0) AS net_total,
                  COALESCE((
                    SELECT SUM(CAST(pp.amount AS REAL))
                    FROM purchase_payments pp
                    WHERE pp.purchase_id = p.purchase_id
                      AND pp.clearing_state = 'cleared'
                  ), 0.0) AS direct_paid,
                  COALESCE(p.advance_payment_applied, 0.0) AS advance_applied,
                  COALESCE((
                    SELECT SUM(CAST(va.amount AS REAL))
                    FROM vendor_advances va
                    WHERE va.source_type = 'return_credit'
                      AND va.source_id = p.purchase_id
                  ), 0.0) AS prior_credit_notes,
                  COALESCE((
                    SELECT SUM(CAST(pr.amount AS REAL))
                    FROM purchase_refunds pr
                    WHERE pr.purchase_id = p.purchase_id
                      AND pr.clearing_state = 'cleared'
                  ), 0.0) AS prior_refunds
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt
                  ON pdt.purchase_id = p.purchase_id
                WHERE p.purchase_id = ?
                """,
                (pid,),
            ).fetchone()
            direct_paid = float(position["direct_paid"] or 0.0)
            advance_applied = float(position["advance_applied"] or 0.0)
            funded_amount = direct_paid + advance_applied
            remaining_due = max(0.0, float(position["net_total"] or 0.0) - funded_amount)
            prior_refunds = float(position["prior_refunds"] or 0.0)
            prior_settlement = (
                float(position["prior_credit_notes"] or 0.0) + prior_refunds
            )
            post_return_total = max(
                0.0,
                float(position["net_total"] or 0.0) - requested_return_value,
            )
            settlement_amount = max(
                0.0,
                funded_amount - post_return_total - prior_settlement,
            )

            if mode == "refund_now":
                if remaining_due > 1e-9:
                    raise ValueError(
                        "Refund Now requires a fully settled purchase; "
                        f"remaining due is {remaining_due:.2f}."
                    )
                refundable_direct_payment = max(0.0, direct_paid - prior_refunds)
                if settlement_amount > refundable_direct_payment + 1e-9:
                    raise ValueError(
                        "Refund exceeds the remaining refundable direct payment "
                        f"of {refundable_direct_payment:.2f}."
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

        # Snapshot capture is trigger-driven so direct SQL inserts receive the same protection.
        if inserted_txn_ids:
            placeholders = ",".join("?" for _ in inserted_txn_ids)
            val_row = self.conn.execute(
                f"""
                SELECT COUNT(*) AS snapshot_count,
                       COALESCE(SUM(CAST(return_value AS REAL)), 0.0) AS return_value
                FROM purchase_return_snapshots
                WHERE transaction_id IN ({placeholders})
                """,
                inserted_txn_ids,
            ).fetchone()
            snapshot_count = int(val_row["snapshot_count"] if val_row else 0)
            if snapshot_count != len(inserted_txn_ids):
                raise sqlite3.IntegrityError(
                    "Purchase return valuation snapshot capture failed"
                )
            return_value = float(val_row["return_value"] if val_row else 0.0)
        else:
            return_value = 0.0

        # Settlement handling (no commit here)
        if settlement and return_value > 0:
            if mode in ("refund_now", "credit_note") and settlement_amount > 1e-9:
                if mode == "credit_note":
                    vadv = VendorAdvancesRepo(self.conn)
                    vadv.grant_credit(
                        vendor_id=vendor_id,
                        amount=settlement_amount,
                        date=date,
                        notes=settlement.get("notes") or notes,
                        created_by=created_by,
                        source_id=pid,
                        source_type="return_credit",
                        method=settlement.get("method"),
                        bank_account_id=settlement.get("bank_account_id"),
                        vendor_bank_account_id=settlement.get("vendor_bank_account_id"),
                        instrument_type=settlement.get("instrument_type"),
                        instrument_no=settlement.get("instrument_no"),
                        instrument_date=settlement.get("instrument_date"),
                        deposited_date=settlement.get("deposited_date"),
                        cleared_date=settlement.get("cleared_date"),
                        clearing_state=settlement.get("clearing_state"),
                        ref_no=settlement.get("ref_no"),
                        temp_vendor_bank_name=settlement.get("temp_vendor_bank_name"),
                        temp_vendor_bank_number=settlement.get("temp_vendor_bank_number"),
                    )
                else:
                    cur = self.conn.execute(
                        """
                        INSERT INTO purchase_refunds (
                            purchase_id, vendor_id, date, amount, method,
                            bank_account_id, vendor_bank_account_id,
                            instrument_type, instrument_no, instrument_date,
                            deposited_date, cleared_date, clearing_state, ref_no,
                            temp_vendor_bank_name, temp_vendor_bank_number,
                            notes, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cleared', ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            vendor_id,
                            settlement.get("date") or date,
                            settlement_amount,
                            settlement.get("method") or "Other",
                            settlement.get("bank_account_id"),
                            settlement.get("vendor_bank_account_id"),
                            settlement.get("instrument_type"),
                            settlement.get("instrument_no"),
                            settlement.get("instrument_date"),
                            settlement.get("deposited_date"),
                            settlement.get("cleared_date") or date,
                            settlement.get("ref_no"),
                            settlement.get("temp_vendor_bank_name"),
                            settlement.get("temp_vendor_bank_number"),
                            settlement.get("notes") or notes,
                            created_by,
                        ),
                    )
                    refund_id = int(cur.lastrowid)
                    self.conn.execute(
                        """
                        INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
                        VALUES (?, 'refund', 'purchase_refunds', ?, ?)
                        """,
                        (
                            created_by,
                            refund_id,
                            f"Recorded vendor refund of {settlement_amount:g}. Purchase ID: {pid}",
                        ),
                    )

        # Audit logging for the return
        self.conn.execute(
            """
            INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                created_by,
                "return",
                "purchases",
                pid,
                f"Returned items with total value of {return_value:g}. "
                f"Settlement amount: {settlement_amount:g}. Lines: {len(lines)}",
            ),
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
            """
            SELECT
              p.purchase_id,
              p.date,
              CAST(p.total_amount AS REAL) AS total_amount,
              CAST(COALESCE(pdt.calculated_total_amount, p.total_amount) AS REAL) AS net_total_amount
            """,
            "FROM purchases p",
            "LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id",
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
                out.append(
                    {
                        "purchase_id": r[0],
                        "date": r[1],
                        "total_amount": float(r[2]),
                        "net_total_amount": float(r[3]),
                    }
                )
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
          CAST(qty_returned  AS REAL) AS qty_returned,
          CAST(unit_buy_price AS REAL) AS unit_buy_price,
          CAST(unit_discount  AS REAL) AS unit_discount,
          return_date,
          valuation_status,
          CAST(return_value   AS REAL) AS return_value,
          CAST(return_value   AS REAL) AS line_value,   -- alias for tests
          CAST(return_value   AS REAL) AS value         -- alias for tests
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """
        return self.conn.execute(sql, (purchase_id,)).fetchall()

    def get_returnable_map(self, purchase_id: str) -> dict[int, float]:
        """
        Get the returnable quantity for each item in a purchase.
        """
        sql = """
        SELECT
          pi.item_id,
          CAST(pi.quantity AS REAL) -
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='purchase_return'
              AND it.reference_table='purchases'
              AND it.reference_id = pi.purchase_id
              AND it.reference_item_id = pi.item_id
          ), 0.0) AS returnable
        FROM purchase_items pi
        WHERE pi.purchase_id=?
        """
        rows = self.conn.execute(sql, (purchase_id,)).fetchall()
        return {int(r["item_id"]): float(r["returnable"]) for r in rows}

    def purchase_return_totals(self, purchase_id: str) -> dict:
        """
        Aggregate quantity and value for all recorded returns against a purchase.

        Uses the purchase_return_valuations view to stay consistent with how
        monetary return value is computed in record_return.
        """
        row = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(CAST(qty_returned AS REAL)), 0.0)  AS qty_returned,
              COALESCE(SUM(CAST(return_value  AS REAL)), 0.0) AS value_returned
            FROM purchase_return_valuations
            WHERE purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        if not row:
            return {"qty": 0.0, "value": 0.0}
        return {
            "qty": float(row["qty_returned"] or 0.0),
            "value": float(row["value_returned"] or 0.0),
        }

    def get_payment(self, payment_id: int, purchase_id: str) -> dict | None:
        """
        Get a specific payment by ID and purchase ID.
        """
        sql = """
        SELECT *
        FROM purchase_payments
        WHERE payment_id=? AND purchase_id=?
        """
        return self.conn.execute(sql, (payment_id, purchase_id)).fetchone()

    def fetch_purchase_financials(self, purchase_id: str) -> dict:
        """
        Fetch financial details for a purchase including calculated totals.
        """
        sql = """
        SELECT
          p.total_amount,
          COALESCE(p.paid_amount, 0.0)              AS paid_amount,
          COALESCE(p.advance_payment_applied, 0.0)  AS advance_payment_applied,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount,
          COALESCE((
            SELECT SUM(CAST(pr.amount AS REAL))
            FROM purchase_refunds pr
            WHERE pr.purchase_id = p.purchase_id
              AND pr.clearing_state = 'cleared'
          ), 0.0) AS prior_refunded_amount,
          COALESCE((
            SELECT SUM(CAST(pp.amount AS REAL))
            FROM purchase_payments pp
            WHERE pp.purchase_id = p.purchase_id
              AND pp.clearing_state = 'cleared'
          ), 0.0) AS cleared_direct_payments
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?;
        """
        row = self.conn.execute(sql, (purchase_id,)).fetchone()
        if not row:
            return {
                "total_amount": 0.0,
                "paid_amount": 0.0,
                "advance_payment_applied": 0.0,
                "calculated_total_amount": 0.0,
                "remaining_due": 0.0,
                "is_fully_paid": False,
                "prior_refunded_amount": 0.0,
                "remaining_refundable_amount": 0.0,
            }
        calc = float(row["calculated_total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        adv = float(row["advance_payment_applied"] or 0.0)
        prior_refunded = float(row["prior_refunded_amount"] or 0.0)
        cleared_direct = float(row["cleared_direct_payments"] or 0.0)
        rem = max(0.0, calc - cleared_direct - adv)
        return {
            "total_amount": float(row["total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "calculated_total_amount": calc,
            "remaining_due": rem,
            "is_fully_paid": rem <= 1e-9,
            "prior_refunded_amount": prior_refunded,
            "remaining_refundable_amount": max(0.0, cleared_direct - prior_refunded),
        }

    def get_remaining_due_header(self, purchase_id: str) -> float:
        """
        Calculate the remaining amount due for a purchase.
        Uses calculated_total_amount from purchase_detailed_totals view if available, 
        falling back to purchases.total_amount otherwise.
        """
        sql = """
        SELECT
            COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
            COALESCE(p.paid_amount, 0.0) AS paid_amount,
            COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """
        row = self.conn.execute(sql, (purchase_id,)).fetchone()
        if not row:
            return 0.0
        total = float(row["total_calc"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        applied = float(row["advance_payment_applied"] or 0.0)
        remaining = total - paid - applied
        return max(0.0, remaining)

    def update_header_totals(self, purchase_id: str) -> None:
        """
        Recompute and update the header totals (paid_amount and payment_status) for a purchase
        based on cleared payments.
        """
        # Calculate the cleared paid amount (clamped ≥ 0.0 to mirror DB triggers)
        r_pay = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS cleared_paid
            FROM purchase_payments
            WHERE purchase_id = ?
              AND COALESCE(clearing_state, 'posted') = 'cleared'
            """,
            (purchase_id,),
        ).fetchone()
        cleared_paid = max(0.0, float(r_pay["cleared_paid"] if r_pay and "cleared_paid" in r_pay.keys() else 0.0))

        # Get the calculated total and advance applied
        row = self.conn.execute(
            """
            SELECT
              COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
              COALESCE(p.advance_payment_applied, 0.0) AS adv_applied
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        total_calc = float(row["total_calc"] if row and "total_calc" in row.keys() else 0.0)
        adv_applied = float(row["adv_applied"] if row and "adv_applied" in row.keys() else 0.0)

        remaining = total_calc - cleared_paid - adv_applied
        if remaining <= 1e-9:
            payment_status = "paid"
        elif cleared_paid > 1e-9 or adv_applied > 1e-9:
            payment_status = "partial"
        else:
            payment_status = "unpaid"

        self.conn.execute(
            "UPDATE purchases SET paid_amount = ?, payment_status = ? WHERE purchase_id = ?;",
            (cleared_paid, payment_status, purchase_id),
        )

    def get_open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        """
        Get open purchases (purchases with remaining balance) for a vendor.
        """
        sql = """
        SELECT
            p.purchase_id,
            p.date,
            COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount,
            CAST(p.total_amount AS REAL)    AS total_amount,
            CAST(p.paid_amount AS REAL)     AS paid_amount,
            CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
            (COALESCE(pdt.calculated_total_amount, p.total_amount) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS balance
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.vendor_id = ?
          AND (COALESCE(pdt.calculated_total_amount, p.total_amount) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) > 1e-9
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        return self.conn.execute(sql, (vendor_id,)).fetchall()

    def get_vendor_id_for_purchase(self, purchase_id: str) -> dict | None:
        """
        Get the vendor_id for a given purchase_id.
        """
        return self.conn.execute("SELECT vendor_id FROM purchases WHERE purchase_id=?;", (purchase_id,)).fetchone()

    def get_purchase_remaining_due(self, purchase_id: str) -> dict | None:
        """
        Get the remaining due amount for a purchase.
        """
        sql = """
        SELECT
            COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount,
            CAST(p.paid_amount AS REAL) AS paid_amount,
            CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
            (COALESCE(pdt.calculated_total_amount, p.total_amount) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS remaining_due
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """
        return self.conn.execute(sql, (purchase_id,)).fetchone()

    def get_header_with_vendor(self, purchase_id: str) -> dict | None:
        """
        Get purchase header data joined with vendor information.
        """
        sql = """
        SELECT p.*, v.name AS vendor_name, v.contact_info AS vendor_contact_info, v.address AS vendor_address
        FROM purchases p
        JOIN vendors v ON p.vendor_id = v.vendor_id
        WHERE p.purchase_id = ?
        """
        row = self.conn.execute(sql, (purchase_id,)).fetchone()
        return dict(row) if row else None
