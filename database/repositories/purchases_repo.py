from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import sqlite3
from typing import Iterable, Optional

# For settlements
from ...modules.accounting import (
    AccountingService,
    PurchaseInventoryLine,
    PurchaseInventoryPayload,
    PurchaseReturnPayload,
)


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

        inventory_lines: list[PurchaseInventoryLine] = []
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

            inventory_lines.append(
                PurchaseInventoryLine(
                    item_id=item_id,
                    product_id=it.product_id,
                    quantity=Decimal(str(it.quantity)),
                    uom_id=it.uom_id,
                )
            )
        self.accounting.record_purchase_inventory_event(
            PurchaseInventoryPayload(
                purchase_id=header.purchase_id,
                date=header.date,
                created_by=header.created_by,
                lines=tuple(inventory_lines),
                notes=header.notes,
            )
        )

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
              CAST(pi.quantity AS REAL) AS quantity
            FROM purchase_items pi
            WHERE pi.purchase_id=?
            """,
            (header.purchase_id,),
        ).fetchall()
        existing = {int(row["item_id"]): row for row in existing_rows}
        returnable = self.accounting.get_purchase_returnable_quantities(
            header.purchase_id
        )
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

            returned_qty = float(row["quantity"]) - float(returnable.get(item_id, 0))
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
            returned_qty = float(row["quantity"]) - float(returnable.get(item_id, 0))
            if item_id not in retained_ids and returned_qty > 1e-9:
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

        for item_id in set(existing) - retained_ids:
            self.conn.execute(
                "DELETE FROM purchase_items WHERE item_id=? AND purchase_id=?",
                (item_id, header.purchase_id),
            )

        # Update retained items and insert new items, then rebuild purchase inventory rows.
        inventory_lines: list[PurchaseInventoryLine] = []
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

            inventory_lines.append(
                PurchaseInventoryLine(
                    item_id=item_id,
                    product_id=it.product_id,
                    quantity=Decimal(str(it.quantity)),
                    uom_id=it.uom_id,
                )
            )

        self.update_header_totals(header.purchase_id)
        self.accounting.record_purchase_inventory_event(
            PurchaseInventoryPayload(
                purchase_id=header.purchase_id,
                date=header.date,
                created_by=header.created_by,
                lines=tuple(inventory_lines),
                notes=header.notes,
                replace_existing=True,
            )
        )

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
        self.accounting.record_purchase_return_event(
            PurchaseReturnPayload(
                purchase_id=pid,
                date=date,
                created_by=created_by,
                lines=tuple(lines),
                notes=notes,
                settlement=settlement,
            )
        )

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
        Backward-compatible return entry point.

        No commit here; caller controls the transaction boundary.
        """
        self.accounting.record_purchase_return_event(
            PurchaseReturnPayload(
                purchase_id=pid,
                date=date,
                created_by=created_by,
                lines=tuple(lines),
                notes=notes,
                settlement=settlement,
            )
        )

    # ---------- Hard delete ----------
    def _delete_purchase_content(self, pid: str):
        # remove inventory rows first (FK safety)
        self.accounting.record_purchase_inventory_event(
            PurchaseInventoryPayload(
                purchase_id=pid,
                date=None,
                created_by=None,
                replace_existing=True,
                delete_transaction_types=None,
            )
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
        return [
            {
                "transaction_id": value.transaction_id,
                "item_id": value.item_id,
                "qty_returned": float(value.qty_returned),
                "unit_buy_price": float(value.unit_buy_price),
                "unit_discount": float(value.unit_discount),
                "return_date": value.return_date,
                "valuation_status": value.valuation_status,
                "return_value": float(value.return_value),
                "line_value": float(value.return_value),
                "value": float(value.return_value),
            }
            for value in self.accounting.get_purchase_return_values(purchase_id)
        ]

    def get_returnable_map(self, purchase_id: str) -> dict[int, float]:
        """
        Get the returnable quantity for each item in a purchase.
        """
        return {
            item_id: float(qty)
            for item_id, qty in self.accounting.get_purchase_returnable_quantities(
                purchase_id
            ).items()
        }

    def purchase_return_totals(self, purchase_id: str) -> dict:
        """
        Aggregate quantity and value for all recorded returns against a purchase.

        Uses the purchase_return_valuations view to stay consistent with how
        monetary return value is computed in record_return.
        """
        totals = self.accounting.get_purchase_return_totals(purchase_id)
        return {"qty": float(totals.qty), "value": float(totals.value)}

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
        financials = self.accounting.get_purchase_financials(purchase_id)
        return {
            "total_amount": float(financials.total_amount),
            "paid_amount": float(financials.paid_amount),
            "advance_payment_applied": float(financials.applied_credit),
            "return_credit_amount": float(financials.return_credit_amount),
            "calculated_total_amount": float(financials.net_total),
            "remaining_due": float(financials.outstanding),
            "is_fully_paid": financials.is_fully_paid,
            "prior_refunded_amount": float(financials.refunded_amount),
            "remaining_refundable_amount": float(financials.remaining_refundable_amount),
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
        try:
            financials = self.accounting.get_purchase_financials(purchase_id)
        except ValueError:
            return None
        return {
            "calculated_total_amount": float(financials.net_total),
            "paid_amount": float(financials.paid_amount),
            "advance_payment_applied": float(financials.applied_credit),
            "remaining_due": float(financials.outstanding),
        }

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
