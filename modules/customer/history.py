from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class CustomerHistoryService:
    """
    Presenter/service for assembling customer financial history for the UI.

    Pulls data from:
      - sales (doc_type='sale') + sale_items (+ products, uoms) and sale_detailed_totals view
      - sale_payments
      - customer_advances (+ v_customer_advance_balance)

    Returns structured dictionaries to keep the UI layer simple.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    @staticmethod
    def _rowdict(row: sqlite3.Row | None) -> Dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _rowsdict(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        return [dict(r) for r in rows]

    @staticmethod
    def _clamp_non_negative(x: float) -> float:
        return x if x > 0 else 0.0

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def sales_with_items(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Returns sales for the customer with header totals (both header + calc view),
        computed remaining due, and an embedded list of line items.

        remaining_due formula:
            remaining_due = calculated_total_amount - paid_amount - advance_payment_applied   (clamped at >= 0)
        """
        with self._connect() as con:
            sales = con.execute(
                """
                SELECT
                    s.sale_id,
                    s.customer_id,
                    s.date,
                    s.total_amount,
                    s.paid_amount,
                    s.advance_payment_applied,
                    s.payment_status,
                    s.order_discount,
                    s.notes,
                    s.created_by,
                    s.source_type,
                    s.source_id,
                    COALESCE(sdt.subtotal_before_order_discount, 0.0) AS subtotal_before_order_discount,
                    COALESCE(sdt.calculated_total_amount, s.total_amount) AS calculated_total_amount
                FROM sales s
                LEFT JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
                WHERE s.customer_id = ?
                  AND s.doc_type = 'sale'
                ORDER BY s.date ASC, s.sale_id ASC;
                """,
                (customer_id,),
            ).fetchall()

            if not sales:
                return []

            sale_ids = [row["sale_id"] for row in sales]
            # Build a parameterized IN clause safely
            placeholders = ",".join(["?"] * len(sale_ids))

            items = con.execute(
                f"""
                SELECT
                    si.item_id,
                    si.sale_id,
                    si.product_id,
                    p.name AS product_name,
                    si.quantity,
                    si.uom_id,
                    u.unit_name AS uom_name,
                    si.unit_price,
                    si.item_discount
                FROM sale_items si
                JOIN products p ON p.product_id = si.product_id
                JOIN uoms u     ON u.uom_id     = si.uom_id
                WHERE si.sale_id IN ({placeholders})
                ORDER BY si.sale_id ASC, si.item_id ASC;
                """,
                sale_ids,
            ).fetchall()

        # Group items by sale_id
        items_by_sale: Dict[str, List[Dict[str, Any]]] = {}
        for r in items:
            items_by_sale.setdefault(r["sale_id"], []).append(dict(r))

        # Compute remaining due using calculated_total_amount - paid_amount - advance_payment_applied
        result: List[Dict[str, Any]] = []
        for s in sales:
            calc_total = float(s["calculated_total_amount"] or 0.0)
            paid = float(s["paid_amount"] or 0.0)
            adv_applied = float(s["advance_payment_applied"] or 0.0)
            remaining_due = self._clamp_non_negative(calc_total - paid - adv_applied)
            header_total = float(s["total_amount"] or 0.0)
            result.append(
                {
                    **dict(s),
                    "items": items_by_sale.get(s["sale_id"], []),
                    "remaining_due": remaining_due,
                    "header_vs_calc_delta": round(header_total - calc_total, 6),
                }
            )
        return result

    def sale_payments(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Returns sale payments for all sales of the given customer (chronological).
        """
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    sp.payment_id,
                    sp.sale_id,
                    sp.date,
                    sp.amount,
                    sp.method,
                    sp.bank_account_id,
                    sp.instrument_type,
                    sp.instrument_no,
                    sp.instrument_date,
                    sp.deposited_date,
                    sp.cleared_date,
                    sp.clearing_state,
                    sp.ref_no,
                    sp.notes,
                    sp.created_by
                FROM sale_payments sp
                JOIN sales s ON s.sale_id = sp.sale_id
                WHERE s.customer_id = ?
                ORDER BY sp.date ASC, sp.payment_id ASC;
                """,
                (customer_id,),
            ).fetchall()
        return self._rowsdict(rows)

    def advances_ledger(self, customer_id: int) -> Dict[str, Any]:
        """
        Returns:
          - 'entries': the raw customer_advances entries for the customer
          - 'balance': current balance from v_customer_advance_balance
        """
        with self._connect() as con:
            entries = con.execute(
                """
                SELECT
                    tx_id,
                    customer_id,
                    tx_date,
                    amount,
                    source_type,
                    source_id,
                    notes,
                    created_by
                FROM customer_advances
                WHERE customer_id = ?
                ORDER BY tx_date ASC, tx_id ASC;
                """,
                (customer_id,),
            ).fetchall()

            bal_row = con.execute(
                """
                SELECT balance
                FROM v_customer_advance_balance
                WHERE customer_id = ?;
                """,
                (customer_id,),
            ).fetchone()

        return {
            "entries": self._rowsdict(entries),
            "balance": float(bal_row["balance"]) if bal_row is not None else 0.0,
        }

    def timeline(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Builds a unified chronological timeline of financial events for the customer:
          - 'sale'            (amount = calculated_total_amount, remaining_due included)
          - 'receipt'         (sale payment; amount = payment amount > 0)
          - 'advance'         (customer deposit/credit; amount = +ve)
          - 'advance_applied' (credit applied to sale; amount = negative)
        """
        sales = self.sales_with_items(customer_id)
        payments = self.sale_payments(customer_id)
        advances = self.advances_ledger(customer_id)

        events: List[Dict[str, Any]] = []

        for s in sales:
            events.append(
                {
                    "kind": "sale",
                    "date": s["date"],
                    "id": s["sale_id"],
                    "sale_id": s["sale_id"],
                    "amount": float(s["calculated_total_amount"] or 0.0),
                    "remaining_due": float(s["remaining_due"] or 0.0),
                    "payment_status": s["payment_status"],
                    "items": s["items"],
                    "notes": s.get("notes"),
                }
            )

        for p in payments:
            events.append(
                {
                    "kind": "receipt",
                    "date": p["date"],
                    "id": p["payment_id"],
                    "sale_id": p["sale_id"],
                    "amount": float(p["amount"] or 0.0),  # > 0 under current business rules
                    "method": p["method"],
                    "clearing_state": p["clearing_state"],
                    "instrument_no": p["instrument_no"],
                    "notes": p.get("notes"),
                }
            )

        for a in advances["entries"]:
            kind = "advance_applied" if a["source_type"] == "applied_to_sale" else "advance"
            events.append(
                {
                    "kind": kind,
                    "date": a["tx_date"],
                    "id": a["tx_id"],
                    "sale_id": a.get("source_id"),
                    "amount": float(a["amount"] or 0.0),  # +ve deposit, -ve application
                    "notes": a.get("notes"),
                }
            )

        # chronological sort; for same day, put sale first, then receipts, then advances, then applications
        order = {"sale": 0, "receipt": 1, "advance": 2, "advance_applied": 3}
        events.sort(key=lambda e: (e["date"] or "", order.get(e["kind"], 99), str(e.get("id", ""))))
        return events

    def overview(self, customer_id: int) -> Dict[str, Any]:
        """
        High-level snapshot for the UI:
          - balance (credit) from v_customer_advance_balance
          - sales count & open due sum (based on calculated totals)
          - last activity dates
        """
        sales = self.sales_with_items(customer_id)
        advances = self.advances_ledger(customer_id)
        payments = self.sale_payments(customer_id)

        open_due_sum = sum(float(s["remaining_due"] or 0.0) for s in sales)
        last_sale_date = sales[-1]["date"] if sales else None
        last_payment_date = payments[-1]["date"] if payments else None
        last_advance_date = advances["entries"][-1]["tx_date"] if advances["entries"] else None

        return {
            "customer_id": customer_id,
            "credit_balance": float(advances["balance"]),
            "sales_count": len(sales),
            "open_due_sum": open_due_sum,
            "last_sale_date": last_sale_date,
            "last_payment_date": last_payment_date,
            "last_advance_date": last_advance_date,
        }

    def full_history(self, customer_id: int) -> Dict[str, Any]:
        """
        Complete payload for UI screens:
          - sales (with items & remaining due)
          - payments
          - advances (+balance)
          - timeline (merged)
          - overview
        """
        sales = self.sales_with_items(customer_id)
        payments = self.sale_payments(customer_id)
        advances = self.advances_ledger(customer_id)
        timeline = self.timeline(customer_id)
        summary = self.overview(customer_id)

        return {
            "summary": summary,
            "sales": sales,
            "payments": payments,
            "advances": advances,
            "timeline": timeline,
        }


# Convenience factory
def get_customer_history_service(db_path: str | Path) -> CustomerHistoryService:
    return CustomerHistoryService(db_path)
