from __future__ import annotations
from dataclasses import dataclass
import sqlite3
from typing import Iterable, Optional

# For settlements
from ...modules.accounting import AccountingService
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...database.repositories.inventory_repo import rebuild_dirty_valuations


PURCHASE_ITEM_PRICE_RULE_MESSAGE = "Sale price must be greater than purchase price."


def _ensure_purchase_item_prices(purchase_price: float, sale_price: float) -> None:
    if purchase_price < 0:
        raise ValueError("Purchase price cannot be negative.")
    if sale_price < 0:
        raise ValueError("Sale price cannot be negative.")
    if sale_price <= purchase_price:
        raise ValueError(PURCHASE_ITEM_PRICE_RULE_MESSAGE)


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
    DEFAULT_LIST_LIMIT = 200

    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn
        self.accounting = AccountingService(conn)

    def _with_purchase_totals(self, row: sqlite3.Row | dict) -> dict:
        data = dict(row)
        totals = self.accounting.get_purchase_totals(data["purchase_id"])
        data["total_amount"] = float(totals.stored_total or 0.0)
        data["order_discount"] = float(totals.order_discount)
        data["returned_value"] = float(totals.returned_value)
        data["calculated_total_amount"] = float(totals.net_total)
        if "remaining_due" in data:
            data["remaining_due"] = float(
                self.accounting.get_purchase_remaining_due_header(
                    data["purchase_id"]
                ).outstanding
            )
        if "payment_status" in data or "paid_amount" in data:
            status = self.accounting.get_purchase_payment_status(data["purchase_id"])
            data["payment_status"] = status.status
            data["paid_amount"] = float(status.paid_amount)
            data["advance_payment_applied"] = float(status.applied_credit)
        return data

    # ---------- Query ----------
    def _purchase_list_select_sql(self) -> str:
        return """
        SELECT p.purchase_id, p.date, p.vendor_id, v.name AS vendor_name,
               CAST(p.total_amount AS REAL) AS total_amount,
               COALESCE(CAST(pr.returned_value AS REAL), 0.0) AS returned_value,
               COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) AS calculated_total_amount,
               CAST(p.order_discount AS REAL) AS order_discount,
               p.payment_status, CAST(p.paid_amount AS REAL) AS paid_amount,
               CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
               COALESCE(CAST(rc.return_credit_amount AS REAL), 0.0) AS return_credit_amount,
               MAX(
                   0.0,
                   COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))
                   - COALESCE(CAST(p.paid_amount AS REAL), 0.0)
                   - COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
               ) AS remaining_due,
               p.notes
        FROM purchases p
        JOIN vendors v ON v.vendor_id = p.vendor_id
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        LEFT JOIN (
            SELECT purchase_id, SUM(CAST(return_value AS REAL)) AS returned_value
            FROM purchase_return_valuations
            GROUP BY purchase_id
        ) pr ON pr.purchase_id = p.purchase_id
        LEFT JOIN (
            SELECT source_id AS purchase_id, SUM(CAST(amount AS REAL)) AS return_credit_amount
            FROM vendor_advances
            WHERE source_type = 'return_credit'
            GROUP BY source_id
        ) rc ON rc.purchase_id = p.purchase_id
        """

    def list_purchases(self, limit: int = DEFAULT_LIST_LIMIT) -> list[dict]:
        sql = """
        """ + self._purchase_list_select_sql() + """
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        params: list[object] = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [
            self._with_purchase_totals(row)
            for row in self.conn.execute(sql, params).fetchall()
        ]

    def search_purchases(
        self,
        query: str = "",
        search_field: str = "all",
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return self.list_purchases(limit=limit)

        field = (search_field or "all").strip().lower()
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        contains_like = f"%{escaped.lower()}%"
        status_expr = """
            CASE
                WHEN MAX(
                    0.0,
                    COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))
                    - COALESCE(CAST(p.paid_amount AS REAL), 0.0)
                    - COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
                ) <= 1e-9 THEN 'paid'
                WHEN COALESCE(CAST(p.paid_amount AS REAL), 0.0) > 1e-9
                  OR COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0) > 1e-9 THEN 'partial'
                ELSE 'unpaid'
            END
        """
        where_sql = ""
        params: list[object] = []

        if field == "id":
            where_sql = " WHERE LOWER(COALESCE(p.purchase_id, '')) LIKE ? ESCAPE '\\'"
            params.append(contains_like)
        elif field == "vendor":
            where_sql = " WHERE LOWER(COALESCE(v.name, '')) LIKE ? ESCAPE '\\'"
            params.append(contains_like)
        elif field == "status":
            where_sql = f" WHERE LOWER({status_expr}) LIKE ? ESCAPE '\\'"
            params.append(contains_like)
        elif field == "date":
            where_sql = " WHERE LOWER(COALESCE(p.date, '')) LIKE ? ESCAPE '\\'"
            params.append(contains_like)
        else:
            where_sql = f"""
            WHERE (
                LOWER(COALESCE(p.purchase_id, '')) LIKE ? ESCAPE '\\'
                OR LOWER(COALESCE(p.date, '')) LIKE ? ESCAPE '\\'
                OR LOWER(COALESCE(v.name, '')) LIKE ? ESCAPE '\\'
                OR LOWER({status_expr}) LIKE ? ESCAPE '\\'
            )
            """
            params.extend([contains_like, contains_like, contains_like, contains_like])

        sql = self._purchase_list_select_sql() + where_sql + """
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [
            self._with_purchase_totals(row)
            for row in self.conn.execute(sql, params).fetchall()
        ]

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

    def get_purchase_detail_snapshot(self, purchase_id: str) -> dict:
        header = self.conn.execute(
            """
            SELECT
              p.purchase_id,
              p.date,
              p.vendor_id,
              v.name AS vendor_name,
              CAST(p.total_amount AS REAL) AS total_amount,
              CAST(p.order_discount AS REAL) AS order_discount,
              p.payment_status,
              CAST(p.paid_amount AS REAL) AS paid_amount,
              CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
              p.notes,
              COALESCE(CAST(pr.qty_returned AS REAL), 0.0) AS returned_qty,
              COALESCE(CAST(pr.value_returned AS REAL), 0.0) AS returned_value,
              COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) AS calculated_total_amount,
              MAX(
                  0.0,
                  COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))
                  - COALESCE(CAST(p.paid_amount AS REAL), 0.0)
                  - COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0)
              ) AS remaining_due
            FROM purchases p
            JOIN vendors v ON v.vendor_id = p.vendor_id
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            LEFT JOIN (
                SELECT purchase_id,
                       SUM(CAST(qty_returned AS REAL)) AS qty_returned,
                       SUM(CAST(return_value AS REAL)) AS value_returned
                FROM purchase_return_valuations
                GROUP BY purchase_id
            ) pr ON pr.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        if not header:
            return {}

        header_row = self._with_purchase_totals(header)
        payment_summary = self.accounting.get_purchase_payment_summary(
            purchase_id
        ).to_detail_payload()

        return {
            "row": header_row,
            "items": [dict(row) for row in self.list_items(purchase_id)],
            "payment_summary": payment_summary,
        }

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
        _ensure_purchase_item_prices(float(it.purchase_price), float(it.sale_price))
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
            _ensure_purchase_item_prices(float(it.purchase_price), float(it.sale_price))
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
        rebuild_dirty_valuations(self.conn)

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
            _ensure_purchase_item_prices(float(it.purchase_price), float(it.sale_price))
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
        rebuild_dirty_valuations(self.conn)

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

            rebuild_dirty_valuations(self.conn, product_id)
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

        # Always run position math if requested_return_value > 0
        direct_paid = 0.0
        advance_applied = 0.0
        funded_amount = 0.0
        remaining_due = 0.0
        prior_refunds = 0.0
        prior_credit_notes = 0.0
        prior_settlement = 0.0
        post_return_total = 0.0
        settlement_amount = 0.0
        prop_adv = 0.0

        if requested_return_value > 0:
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
            if position:
                direct_paid = float(position["direct_paid"] or 0.0)
                advance_applied = float(position["advance_applied"] or 0.0)
                prior_credit_notes = float(position["prior_credit_notes"] or 0.0)
                prior_refunds = float(position["prior_refunds"] or 0.0)
                net_total_before = float(position["net_total"] or 0.0)

                funded_amount = direct_paid + advance_applied
                remaining_due = max(0.0, net_total_before - funded_amount)
                prior_settlement = prior_credit_notes + prior_refunds
                post_return_total = max(0.0, net_total_before - requested_return_value)
                settlement_amount = max(0.0, funded_amount - post_return_total - prior_settlement)

                # Calculate proportional advance to reinstate
                net_advance_applied = max(0.0, advance_applied - prior_credit_notes)
                if net_total_before > 1e-9:
                    prop_adv = (requested_return_value / net_total_before) * advance_applied
                    prop_adv = min(prop_adv, net_advance_applied)
                else:
                    prop_adv = 0.0

            if settlement and mode == "refund_now":
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
        rebuild_dirty_valuations(self.conn)

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
        if return_value > 0 and settlement_amount > 1e-9:
            mode = settlement.get("mode") if settlement else None
            if mode == "refund":
                mode = "refund_now"

            if mode == "refund_now":
                refundable_direct_payment = max(0.0, direct_paid - prior_refunds)
                cash_refund_amount = min(max(0.0, settlement_amount - prop_adv), refundable_direct_payment)
                credit_amount = max(0.0, settlement_amount - cash_refund_amount)
            else:
                # Default to credit note if not explicitly refund_now
                cash_refund_amount = 0.0
                credit_amount = settlement_amount

            if credit_amount > 1e-9:
                vadv = VendorAdvancesRepo(self.conn)
                vadv.grant_credit(
                    vendor_id=vendor_id,
                    amount=credit_amount,
                    date=date,
                    notes=settlement.get("notes") or notes if settlement else notes,
                    created_by=created_by,
                    source_id=pid,
                    source_type="return_credit",
                    method=settlement.get("method") if settlement else None,
                    bank_account_id=settlement.get("bank_account_id") if settlement else None,
                    vendor_bank_account_id=settlement.get("vendor_bank_account_id") if settlement else None,
                    instrument_type=settlement.get("instrument_type") if settlement else None,
                    instrument_no=settlement.get("instrument_no") if settlement else None,
                    instrument_date=settlement.get("instrument_date") if settlement else None,
                    deposited_date=settlement.get("deposited_date") if settlement else None,
                    cleared_date=settlement.get("cleared_date") if settlement else None,
                    clearing_state=settlement.get("clearing_state") if settlement else None,
                    ref_no=settlement.get("ref_no") if settlement else None,
                    temp_vendor_bank_name=settlement.get("temp_vendor_bank_name") if settlement else None,
                    temp_vendor_bank_number=settlement.get("temp_vendor_bank_number") if settlement else None,
                )

            if cash_refund_amount > 1e-9:
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
                        settlement.get("date") or date if settlement else date,
                        cash_refund_amount,
                        settlement.get("method") or "Other" if settlement else "Other",
                        settlement.get("bank_account_id") if settlement else None,
                        settlement.get("vendor_bank_account_id") if settlement else None,
                        settlement.get("instrument_type") if settlement else None,
                        settlement.get("instrument_no") if settlement else None,
                        settlement.get("instrument_date") if settlement else None,
                        settlement.get("deposited_date") if settlement else None,
                        settlement.get("cleared_date") or date if settlement else date,
                        settlement.get("ref_no") if settlement else None,
                        settlement.get("temp_vendor_bank_name") if settlement else None,
                        settlement.get("temp_vendor_bank_number") if settlement else None,
                        settlement.get("notes") or notes if settlement else notes,
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
                        f"Recorded vendor refund of {cash_refund_amount:g}. Purchase ID: {pid}",
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
        rebuild_dirty_valuations(self.conn)

    # ---------- Vendor-scoped listings & summaries ----------
    def list_purchases_by_vendor(
        self,
        vendor_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        return list(
            self.accounting.list_vendor_purchases(vendor_id, date_from, date_to)
        )

    def get_purchase_totals_for_vendor(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        totals = self.accounting.get_vendor_purchase_totals(
            vendor_id,
            date_from,
            date_to,
        )
        return {
            "purchases_total": float(totals.purchases_total),
            "paid_total": float(totals.paid_total),
            "advance_applied_total": float(totals.advance_applied_total),
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
          COALESCE((
            SELECT SUM(CAST(va.amount AS REAL))
            FROM vendor_advances va
            WHERE va.source_id = p.purchase_id
              AND va.source_type = 'return_credit'
          ), 0.0) AS return_credit_amount,
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
                "return_credit_amount": 0.0,
                "calculated_total_amount": 0.0,
                "remaining_due": 0.0,
                "is_fully_paid": False,
                "prior_refunded_amount": 0.0,
                "remaining_refundable_amount": 0.0,
            }
        calc = float(row["calculated_total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        adv = float(row["advance_payment_applied"] or 0.0)
        return_credit = float(row["return_credit_amount"] or 0.0)
        prior_refunded = float(row["prior_refunded_amount"] or 0.0)
        cleared_direct = float(row["cleared_direct_payments"] or 0.0)
        rem = max(0.0, calc - cleared_direct - adv)
        return {
            "total_amount": float(row["total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "return_credit_amount": return_credit,
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
        try:
            outstanding = self.accounting.get_purchase_remaining_due_header(purchase_id)
        except ValueError:
            return 0.0
        return float(outstanding.outstanding)

    def update_header_totals(self, purchase_id: str) -> None:
        """
        Recompute and update the header totals (paid_amount and payment_status) for a purchase
        based on cleared payments.
        """
        self.accounting.recalculate_purchase_payment_status(purchase_id)

    def get_open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        """
        Get open purchases (purchases with remaining balance) for a vendor.
        """
        return [
            {
                "purchase_id": row.purchase_id,
                "date": row.purchase_date,
                "calculated_total_amount": float(row.calculated_total_amount),
                "total_amount": float(row.total_amount),
                "paid_amount": float(row.paid_amount),
                "advance_payment_applied": float(row.advance_payment_applied),
                "balance": float(row.outstanding),
            }
            for row in self.accounting.get_vendor_open_purchases(vendor_id)
        ]

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
        row = self.conn.execute(sql, (purchase_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["remaining_due"] = float(
            self.accounting.get_purchase_outstanding(purchase_id).outstanding
        )
        return data

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
