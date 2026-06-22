from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.accounting import AccountingService


class CustomerHistoryService:
    """
    Presenter/service for assembling customer financial history for the UI.

    Pulls data from:
      - sales (doc_type='sale') + sale_items (+ products, uoms) and sale_detailed_totals view
      - inventory_transactions (transaction_type='sale_return')
      - sale_payments
      - customer_advances (+ v_customer_advance_balance)

    Returns structured dictionaries to keep the UI layer simple.
    """

    def __init__(self, db_path: str | Path, accounting: AccountingService | None = None):
        self.db_path = str(db_path)
        self._accounting = accounting

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
        if self._accounting is not None:
            return self._accounting.get_customer_sales_with_items(customer_id)
        with self._connect() as con:
            sales = con.execute(
                """
                SELECT
                    s.sale_id, s.customer_id, c.name AS customer_name,
                    s.date, s.total_amount, s.paid_amount,
                    s.advance_payment_applied, s.payment_status,
                    s.order_discount, s.notes, s.created_by,
                    s.source_type, s.source_id,
                    COALESCE(sdt.subtotal_before_order_discount, 0.0) AS subtotal_before_order_discount,
                    srt.canonical_total_amount AS calculated_total_amount,
                    srt.remaining_due AS remaining_due
                FROM sales s
                JOIN customers c ON c.customer_id = s.customer_id
                JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
                JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
                WHERE s.customer_id = ? AND s.doc_type = 'sale'
                ORDER BY s.date ASC, s.sale_id ASC
                """,
                (customer_id,),
            ).fetchall()
            if not sales:
                return []
            sale_ids = [row["sale_id"] for row in sales]
            ph = ",".join("?" * len(sale_ids))
            items = con.execute(
                f"SELECT si.item_id, si.sale_id, si.product_id, p.name AS product_name, "
                f"si.quantity, si.uom_id, u.unit_name AS uom_name, si.unit_price, si.item_discount "
                f"FROM sale_items si JOIN products p ON p.product_id = si.product_id "
                f"JOIN uoms u ON u.uom_id = si.uom_id WHERE si.sale_id IN ({ph}) "
                f"ORDER BY si.sale_id ASC, si.item_id ASC",
                sale_ids,
            ).fetchall()
        items_by_sale: Dict[str, List[Dict[str, Any]]] = {}
        for r in items:
            items_by_sale.setdefault(r["sale_id"], []).append(dict(r))
        result: List[Dict[str, Any]] = []
        for s in sales:
            calc_total = float(s["calculated_total_amount"] or 0.0)
            remaining_due = float(s["remaining_due"] or 0.0)
            header_total = float(s["total_amount"] or 0.0)
            result.append({**dict(s), "items": items_by_sale.get(s["sale_id"], []),
                           "remaining_due": remaining_due,
                           "header_vs_calc_delta": round(header_total - calc_total, 6)})
        return result

    def sale_payments(self, customer_id: int) -> List[Dict[str, Any]]:
        if self._accounting is not None:
            return [dict(r) for r in self._accounting.get_customer_payment_history(customer_id)]
        with self._connect() as con:
            rows = con.execute(
                "SELECT sp.payment_id, sp.sale_id, sp.date, sp.amount, sp.method, "
                "sp.bank_account_id, sp.instrument_type, sp.instrument_no, "
                "sp.instrument_date, sp.deposited_date, sp.cleared_date, "
                "sp.clearing_state, sp.ref_no, sp.notes, sp.created_by "
                "FROM sale_payments sp JOIN sales s ON s.sale_id = sp.sale_id "
                "WHERE s.customer_id = ? ORDER BY sp.date ASC, sp.payment_id ASC",
                (customer_id,),
            ).fetchall()
        return self._rowsdict(rows)

    def sale_returns(self, customer_id: int) -> List[Dict[str, Any]]:
        if self._accounting is not None:
            return self._accounting.get_customer_history(customer_id)["timeline"]
        with self._connect() as con:
            rows = con.execute(
                "SELECT it.transaction_id, srs.sale_id, srs.item_id, srs.return_date AS date, "
                "it.posted_at, it.txn_seq, srs.product_id, p.name AS product_name, "
                "CAST(srs.returned_quantity AS REAL) AS quantity, "
                "srs.uom_id, u.unit_name AS uom_name, "
                "CAST(srs.unit_sale_price AS REAL) AS unit_price, "
                "CAST(srs.unit_discount AS REAL) AS item_discount, "
                "CAST(srs.net_unit_price AS REAL) AS net_unit_price, "
                "CAST(srs.allocated_order_discount AS REAL) AS allocated_order_discount, "
                "-CAST(srs.return_value AS REAL) AS amount, "
                "CAST(srs.cogs_reversal_value AS REAL) AS cogs_reversal_value, it.notes "
                "FROM inventory_transactions it "
                "JOIN sale_return_snapshots srs ON srs.transaction_id = it.transaction_id "
                "JOIN sales s ON s.sale_id = srs.sale_id "
                "JOIN products p ON p.product_id = srs.product_id "
                "JOIN uoms u ON u.uom_id = srs.uom_id "
                "WHERE s.customer_id = ? AND s.doc_type = 'sale' "
                "AND it.transaction_type = 'sale_return' "
                "AND it.reference_table = 'sales' AND it.reference_id = srs.sale_id "
                "ORDER BY srs.return_date ASC, it.txn_seq ASC, it.transaction_id ASC",
                (customer_id,),
            ).fetchall()
        return self._rowsdict(rows)

    def advances_ledger(self, customer_id: int) -> Dict[str, Any]:
        if self._accounting is not None:
            return self._accounting.get_customer_history(customer_id)["advances"]
        with self._connect() as con:
            entries = con.execute(
                "SELECT tx_id, customer_id, tx_date, amount, source_type, source_id, "
                "method, bank_account_id, reference_no, notes, created_by "
                "FROM customer_advances WHERE customer_id = ? "
                "ORDER BY tx_date ASC, tx_id ASC",
                (customer_id,),
            ).fetchall()
            bal_row = con.execute(
                "SELECT balance FROM v_customer_advance_balance WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
        return {"entries": self._rowsdict(entries),
                "balance": float(bal_row["balance"]) if bal_row else 0.0}

    def timeline(self, customer_id: int) -> List[Dict[str, Any]]:
        if self._accounting is not None:
            return self._accounting.get_customer_history(customer_id)["timeline"]
        sales = self.sales_with_items(customer_id)
        returns = self.sale_returns(customer_id)
        payments = self.sale_payments(customer_id)
        advances = self.advances_ledger(customer_id)
        events: List[Dict[str, Any]] = []
        for s in sales:
            events.append({"kind": "sale", "date": s["date"], "id": s["sale_id"],
                "sale_id": s["sale_id"], "amount": float(s["calculated_total_amount"] or 0.0),
                "remaining_due": float(s["remaining_due"] or 0.0),
                "payment_status": s["payment_status"], "description": "Sale issued",
                "items": s["items"], "notes": s.get("notes")})
        for r in returns:
            qty = float(r["quantity"] or 0.0)
            events.append({"kind": "sale_return", "date": r["date"], "id": r["transaction_id"],
                "sale_id": r["sale_id"], "amount": float(r["amount"] or 0.0),
                "product_name": r["product_name"], "quantity": qty,
                "uom_name": r.get("uom_name") or "",
                "description": f'{r["product_name"]}: {qty:g} {r.get("uom_name") or ""}'.strip(),
                "notes": r.get("notes")})
        for p in payments:
            amt = float(p["amount"] or 0.0)
            events.append({"kind": "refund" if amt < 0 else "receipt", "date": p["date"],
                "id": p["payment_id"], "sale_id": p["sale_id"], "amount": amt,
                "method": p["method"], "clearing_state": p["clearing_state"],
                "instrument_no": p["instrument_no"], "reference": p["instrument_no"],
                "description": f"{p['method']} {'refund' if amt < 0 else 'payment'}"
                              f"{' - ' + str(p.get('notes', '')) if p.get('notes') else ''}",
                "notes": p.get("notes")})
        for a in advances["entries"]:
            kind = "advance_applied" if a["source_type"] == "applied_to_sale" else "advance"
            events.append({"kind": kind, "date": a["tx_date"], "id": a["tx_id"],
                "sale_id": a.get("source_id"), "amount": float(a["amount"] or 0.0),
                "method": a.get("method"), "reference": a.get("reference_no"),
                "description": (f"Applied customer credit to sale {a.get('source_id')}"
                    if kind == "advance_applied"
                    else f"Customer credit received by {a.get('method') or 'unspecified method'}"),
                "notes": a.get("notes")})
        order = {"sale": 0, "sale_return": 1, "receipt": 2, "refund": 2,
                 "advance": 3, "advance_applied": 4}
        events.sort(key=lambda e: (e["date"] or "", order.get(e["kind"], 99), str(e.get("id", ""))))
        return events

    def overview(self, customer_id: int) -> Dict[str, Any]:
        if self._accounting is not None:
            return self._accounting.get_customer_history(customer_id)["summary"]
        sales = self.sales_with_items(customer_id)
        advances = self.advances_ledger(customer_id)
        payments = self.sale_payments(customer_id)
        open_due_sum = sum(float(s["remaining_due"] or 0.0) for s in sales)
        customer_name = None
        if sales:
            customer_name = sales[0].get("customer_name")
        if customer_name is None:
            with self._connect() as con:
                row = con.execute("SELECT name FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
                customer_name = row["name"] if row else None
        return {"customer_id": customer_id, "customer_name": customer_name,
                "credit_balance": float(advances["balance"]), "sales_count": len(sales),
                "open_due_sum": open_due_sum,
                "last_sale_date": sales[-1]["date"] if sales else None,
                "last_payment_date": payments[-1]["date"] if payments else None,
                "last_advance_date": advances["entries"][-1]["tx_date"] if advances["entries"] else None}

    def full_history(self, customer_id: int) -> Dict[str, Any]:
        if self._accounting is not None:
            return self._accounting.get_customer_history(customer_id)
        sales = self.sales_with_items(customer_id)
        payments = self.sale_payments(customer_id)
        advances = self.advances_ledger(customer_id)
        timeline = self.timeline(customer_id)
        summary = self.overview(customer_id)
        return {"summary": summary, "sales": sales, "payments": payments,
                "advances": advances, "timeline": timeline}


# Convenience factory
def get_customer_history_service(db_path: str | Path) -> CustomerHistoryService:
    return CustomerHistoryService(db_path)
