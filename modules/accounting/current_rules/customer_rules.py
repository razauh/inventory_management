"""Current-rule wrappers for customer statement/history reads."""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from sqlite3 import Connection, Row as SqliteRow
from typing import Any

from typing import Any

from ..dto import (
    CustomerAgingReport,
    CustomerCreditApplicationPayload,
    CustomerCreditApplicationResult,
    CustomerCreditLedgerRow,
    CustomerCreditPayload,
    CustomerCreditResult,
    CustomerRefundRow,
    CustomerReceivableSummary,
    CustomerStatement,
    CustomerStatementEntry,
    SalePaymentRow,
)


def _collect_headers(rows: list[dict]) -> list[str]:
    headers: list[str] = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                headers.append(k)
    return headers


def get_customer_sales_with_items(conn: Connection, customer_id: int) -> list[dict[str, Any]]:
    sales = conn.execute(
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
    sale_ids = [r["sale_id"] for r in sales]
    ph = ",".join("?" * len(sale_ids))
    items = conn.execute(
        f"""
        SELECT si.item_id, si.sale_id, si.product_id, p.name AS product_name,
               si.quantity, si.uom_id, u.unit_name AS uom_name,
               si.unit_price, si.item_discount
        FROM sale_items si
        JOIN products p ON p.product_id = si.product_id
        JOIN uoms u ON u.uom_id = si.uom_id
        WHERE si.sale_id IN ({ph})
        ORDER BY si.sale_id ASC, si.item_id ASC
        """,
        sale_ids,
    ).fetchall()
    items_by_sale: dict[str, list[dict]] = {}
    for r in items:
        items_by_sale.setdefault(r["sale_id"], []).append(dict(r))
    result = []
    for s in sales:
        calc_total = float(s["calculated_total_amount"] or 0.0)
        header_total = float(s["total_amount"] or 0.0)
        ds = dict(s)
        ds["items"] = items_by_sale.get(s["sale_id"], [])
        ds["remaining_due"] = float(s["remaining_due"] or 0.0)
        ds["header_vs_calc_delta"] = round(header_total - calc_total, 6)
        result.append(ds)
    return result


def _sale_payments(conn: Connection, customer_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sp.payment_id, sp.sale_id, sp.date, sp.amount, sp.method,
               sp.bank_account_id, sp.instrument_type, sp.instrument_no,
               sp.instrument_date, sp.deposited_date, sp.cleared_date,
               sp.clearing_state, sp.ref_no, sp.notes, sp.created_by
        FROM sale_payments sp
        JOIN sales s ON s.sale_id = sp.sale_id
        WHERE s.customer_id = ?
        ORDER BY sp.date ASC, sp.payment_id ASC
        """,
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _sale_returns(conn: Connection, customer_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT it.transaction_id, srs.sale_id, srs.item_id, srs.return_date AS date,
               it.posted_at, it.txn_seq, srs.product_id, p.name AS product_name,
               CAST(srs.returned_quantity AS REAL) AS quantity,
               srs.uom_id, u.unit_name AS uom_name,
               CAST(srs.unit_sale_price AS REAL) AS unit_price,
               CAST(srs.unit_discount AS REAL) AS item_discount,
               CAST(srs.net_unit_price AS REAL) AS net_unit_price,
               CAST(srs.allocated_order_discount AS REAL) AS allocated_order_discount,
               -CAST(srs.return_value AS REAL) AS amount,
               CAST(srs.cogs_reversal_value AS REAL) AS cogs_reversal_value,
               it.notes
        FROM inventory_transactions it
        JOIN sale_return_snapshots srs ON srs.transaction_id = it.transaction_id
        JOIN sales s ON s.sale_id = srs.sale_id
        JOIN products p ON p.product_id = srs.product_id
        JOIN uoms u ON u.uom_id = srs.uom_id
        WHERE s.customer_id = ? AND s.doc_type = 'sale'
          AND it.transaction_type = 'sale_return'
          AND it.reference_table = 'sales'
          AND it.reference_id = srs.sale_id
        ORDER BY srs.return_date ASC, it.txn_seq ASC, it.transaction_id ASC
        """,
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _advances_ledger(conn: Connection, customer_id: int) -> dict[str, Any]:
    entries = conn.execute(
        """
        SELECT tx_id, customer_id, tx_date, amount, source_type, source_id,
               method, bank_account_id, reference_no, notes, created_by
        FROM customer_advances
        WHERE customer_id = ?
        ORDER BY tx_date ASC, tx_id ASC
        """,
        (customer_id,),
    ).fetchall()
    bal_row = conn.execute(
        "SELECT balance FROM v_customer_advance_balance WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    return {
        "entries": [dict(r) for r in entries],
        "balance": float(bal_row["balance"]) if bal_row else 0.0,
    }


def _timeline(conn: Connection, customer_id: int) -> list[dict[str, Any]]:
    sales = get_customer_sales_with_items(conn, customer_id)
    returns = _sale_returns(conn, customer_id)
    payments = _sale_payments(conn, customer_id)
    advances = _advances_ledger(conn, customer_id)

    events: list[dict[str, Any]] = []

    for s in sales:
        events.append({
            "kind": "sale",
            "date": s["date"],
            "id": s["sale_id"],
            "sale_id": s["sale_id"],
            "amount": float(s["calculated_total_amount"] or 0.0),
            "remaining_due": float(s["remaining_due"] or 0.0),
            "payment_status": s["payment_status"],
            "description": "Sale issued",
            "items": s["items"],
            "notes": s.get("notes"),
        })

    for r in returns:
        qty = float(r["quantity"] or 0.0)
        uom = r.get("uom_name") or ""
        events.append({
            "kind": "sale_return",
            "date": r["date"],
            "id": r["transaction_id"],
            "sale_id": r["sale_id"],
            "amount": float(r["amount"] or 0.0),
            "product_name": r["product_name"],
            "quantity": qty,
            "uom_name": uom,
            "description": f'{r["product_name"]}: {qty:g} {uom}'.strip(),
            "notes": r.get("notes"),
        })

    for p in payments:
        amt = float(p["amount"] or 0.0)
        events.append({
            "kind": "refund" if amt < 0 else "receipt",
            "date": p["date"],
            "id": p["payment_id"],
            "sale_id": p["sale_id"],
            "amount": amt,
            "method": p["method"],
            "clearing_state": p["clearing_state"],
            "instrument_no": p["instrument_no"],
            "reference": p["instrument_no"],
            "description": (
                f"{p['method']} {'refund' if amt < 0 else 'payment'}"
                + (f" - {p.get('notes')}" if p.get("notes") else "")
            ),
            "notes": p.get("notes"),
        })

    for a in advances["entries"]:
        kind = "advance_applied" if a["source_type"] == "applied_to_sale" else "advance"
        events.append({
            "kind": kind,
            "date": a["tx_date"],
            "id": a["tx_id"],
            "sale_id": a.get("source_id"),
            "amount": float(a["amount"] or 0.0),
            "method": a.get("method"),
            "reference": a.get("reference_no"),
            "description": (
                f"Applied customer credit to sale {a.get('source_id')}"
                if kind == "advance_applied"
                else f"Customer credit received by {a.get('method') or 'unspecified method'}"
            ),
            "notes": a.get("notes"),
        })

    order = {
        "sale": 0, "sale_return": 1, "receipt": 2, "refund": 2,
        "advance": 3, "advance_applied": 4,
    }
    events.sort(key=lambda e: (e["date"] or "", order.get(e["kind"], 99), str(e.get("id", ""))))
    return events


def _overview(conn: Connection, customer_id: int) -> dict[str, Any]:
    sales = get_customer_sales_with_items(conn, customer_id)
    advances = _advances_ledger(conn, customer_id)
    payments = _sale_payments(conn, customer_id)

    open_due_sum = sum(float(s["remaining_due"] or 0.0) for s in sales)
    last_sale_date = sales[-1]["date"] if sales else None
    last_payment_date = payments[-1]["date"] if payments else None
    last_advance_date = advances["entries"][-1]["tx_date"] if advances["entries"] else None

    customer_name = None
    if sales:
        customer_name = sales[0].get("customer_name")
    if not customer_name:
        row = conn.execute(
            "SELECT name FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        customer_name = row["name"] if row else None

    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "credit_balance": float(advances["balance"]),
        "sales_count": len(sales),
        "open_due_sum": open_due_sum,
        "last_sale_date": last_sale_date,
        "last_payment_date": last_payment_date,
        "last_advance_date": last_advance_date,
    }


def get_customer_history(conn: Connection, customer_id: int) -> dict[str, Any]:
    sales = get_customer_sales_with_items(conn, customer_id)
    payments = _sale_payments(conn, customer_id)
    advances = _advances_ledger(conn, customer_id)
    timeline = _timeline(conn, customer_id)
    summary = _overview(conn, customer_id)
    return {
        "summary": summary,
        "sales": sales,
        "payments": payments,
        "advances": advances,
        "timeline": timeline,
    }


def get_customer_statement(
    conn: Connection,
    customer_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> CustomerStatement:
    entries_raw = conn.execute(
        """
        SELECT tx_date, amount, source_type, source_id
        FROM customer_advances
        WHERE customer_id = ?
        ORDER BY tx_date ASC, tx_id ASC
        """,
        (customer_id,),
    ).fetchall()

    bal_row = conn.execute(
        "SELECT balance FROM v_customer_advance_balance WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    closing_balance = Decimal(str(bal_row["balance"])) if bal_row else Decimal("0")

    # ponytail: statement uses simple running balance from advance ledger
    entries: list[CustomerStatementEntry] = []
    running = Decimal("0")
    for r in entries_raw:
        amt = Decimal(str(r["amount"] or 0))
        running += amt
        entries.append(CustomerStatementEntry(
            entry_date=r["tx_date"],
            description=f"{r['source_type']} ({r['source_id'] or ''})",
            debit=amt if amt > 0 else Decimal("0"),
            credit=(-amt) if amt < 0 else Decimal("0"),
            balance=running,
        ))

    return CustomerStatement(
        customer_id=customer_id,
        start_date=start_date,
        end_date=end_date,
        opening_balance=Decimal("0"),
        closing_balance=closing_balance,
        entries=tuple(entries),
    )


def get_customer_aging(
    conn: Connection, cutoff_date: str
) -> CustomerAgingReport:
    from database.repositories.reporting_repo import ReportingRepo

    repo = ReportingRepo(conn)
    customers = conn.execute(
        "SELECT customer_id FROM customers ORDER BY name"
    ).fetchall()
    cids = [r["customer_id"] for r in customers]
    rows = repo.customer_headers_as_of_batch(cids, cutoff_date)
    return CustomerAgingReport(
        as_of=cutoff_date,
        rows=tuple(dict(r) for r in rows),
    )


def get_customer_receivable_summary(
    conn: Connection, customer_id: int
) -> CustomerReceivableSummary:
    row = conn.execute(
        """
        SELECT
          COALESCE((SELECT balance FROM v_customer_advance_balance WHERE customer_id = ?), 0.0) AS credit_balance,
          COALESCE((SELECT COUNT(*) FROM sales WHERE customer_id = ? AND doc_type = 'sale'), 0) AS sales_count,
          COALESCE((
            SELECT SUM(MAX(0.0, CAST(sdt.net_total_amount AS REAL)
              - COALESCE((SELECT SUM(CAST(sp.amount AS REAL)) FROM sale_payments sp
                          WHERE sp.sale_id = s.sale_id AND sp.clearing_state IN ('posted','cleared')), 0.0)
              - COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)))
            FROM sales s
            JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
            WHERE s.customer_id = ? AND s.doc_type = 'sale'
          ), 0.0) AS open_due_sum,
          (SELECT MAX(s.date) FROM sales s WHERE s.customer_id = ? AND s.doc_type = 'sale') AS last_sale_date,
          (SELECT MAX(sp.date) FROM sale_payments sp JOIN sales s ON s.sale_id = sp.sale_id WHERE s.customer_id = ?) AS last_payment_date,
          (SELECT MAX(tx_date) FROM customer_advances WHERE customer_id = ?) AS last_advance_date
        """,
        (customer_id, customer_id, customer_id, customer_id, customer_id, customer_id),
    ).fetchone()
    return CustomerReceivableSummary(
        customer_id=customer_id,
        credit_balance=Decimal(str(row["credit_balance"] or 0)),
        sales_count=int(row["sales_count"] or 0),
        open_due_sum=Decimal(str(row["open_due_sum"] or 0)),
        last_sale_date=row["last_sale_date"],
        last_payment_date=row["last_payment_date"],
        last_advance_date=row["last_advance_date"],
    )


def get_customer_payment_history(
    conn: Connection, customer_id: int
) -> tuple[SalePaymentRow, ...]:
    rows = conn.execute(
        """
        SELECT sp.*
          FROM sale_payments sp
          JOIN sales s ON s.sale_id = sp.sale_id
         WHERE s.customer_id = ?
         ORDER BY sp.date ASC, sp.payment_id ASC
        """,
        (customer_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        res.append(
            SalePaymentRow(
                payment_id=d["payment_id"],
                sale_id=d["sale_id"],
                date=d["date"],
                amount=Decimal(str(d["amount"] or 0)),
                method=d["method"],
                bank_account_id=d.get("bank_account_id"),
                instrument_type=d.get("instrument_type"),
                instrument_no=d.get("instrument_no"),
                instrument_date=d.get("instrument_date"),
                deposited_date=d.get("deposited_date"),
                cleared_date=d.get("cleared_date"),
                clearing_state=d.get("clearing_state"),
                ref_no=d.get("ref_no"),
                notes=d.get("notes"),
                created_by=d.get("created_by"),
                bank_account_label=d.get("bank_account_label"),
            )
        )
    return tuple(res)


def list_customer_sale_summaries(
    conn: Connection, customer_id: int
) -> tuple[dict[str, Any], ...]:
    rows = conn.execute(
        """
        SELECT s.sale_id, s.date, s.doc_no,
               srt.canonical_total_amount AS total,
               srt.paid_amount AS paid,
               srt.advance_payment_applied AS advance_payment_applied,
               srt.remaining_due AS remaining_due
        FROM sales s
        JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
        WHERE s.customer_id = ? AND s.doc_type = 'sale'
        ORDER BY s.date DESC, s.sale_id DESC
        """,
        (customer_id,),
    ).fetchall()
    return tuple(dict(r) for r in rows)


def record_customer_credit_event(
    conn: Connection, payload: CustomerCreditPayload
) -> CustomerCreditResult:
    if payload.amount <= Decimal("0"):
        raise ValueError("Credit amount must be positive.")
    if payload.source_type not in ("deposit", "return_credit"):
        raise ValueError(f"Invalid source_type: {payload.source_type}")
    if payload.method and payload.method not in {"Cash", "Bank Transfer", "Card", "Cheque", "Other"}:
        raise ValueError("Select a valid customer credit method.")
    if payload.bank_account_id is not None:
        acct = conn.execute(
            "SELECT is_active FROM company_bank_accounts WHERE account_id = ?",
            (payload.bank_account_id,),
        ).fetchone()
        if not acct or int(acct["is_active"] or 0) != 1:
            raise ValueError("Select an active company bank account.")

    cur = conn.execute(
        """INSERT INTO customer_advances
           (customer_id, tx_date, amount, source_type, source_id,
            method, bank_account_id, reference_no, notes, created_by)
           VALUES (?, COALESCE(?, CURRENT_DATE), ?, ?, ?,
                   ?, ?, ?, ?, ?)""",
        (payload.customer_id, payload.date, float(payload.amount),
         payload.source_type, payload.source_id,
         payload.method, payload.bank_account_id,
         (payload.reference_no or "").strip() or None,
         payload.notes, payload.created_by),
    )
    return CustomerCreditResult(
        tx_id=int(cur.lastrowid),
        customer_id=payload.customer_id,
        amount=payload.amount,
        source_type=payload.source_type,
    )


def list_customer_credit_ledger(
    conn: Connection, customer_id: int
) -> tuple[CustomerCreditLedgerRow, ...]:
    rows = conn.execute(
        """SELECT tx_id, customer_id, tx_date, amount, source_type, source_id,
                  method, bank_account_id, reference_no, notes, created_by
           FROM customer_advances
           WHERE customer_id = ?
           ORDER BY tx_date ASC, tx_id ASC""",
        (customer_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        res.append(
            CustomerCreditLedgerRow(
                tx_id=d["tx_id"],
                customer_id=d["customer_id"],
                tx_date=d["tx_date"],
                amount=Decimal(str(d["amount"] or 0)),
                source_type=d["source_type"],
                source_id=d.get("source_id"),
                method=d.get("method"),
                bank_account_id=d.get("bank_account_id"),
                reference_no=d.get("reference_no"),
                notes=d.get("notes"),
                created_by=d.get("created_by"),
            )
        )
    return tuple(res)


def record_customer_credit_application_event(
    conn: Connection, payload: CustomerCreditApplicationPayload
) -> CustomerCreditApplicationResult:
    if payload.amount <= Decimal("0"):
        raise ValueError("Apply amount must be positive.")
    row = conn.execute(
        "SELECT customer_id, doc_type FROM sales WHERE sale_id = ?",
        (payload.sale_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Sale '{payload.sale_id}' does not exist.")
    if row["doc_type"] != "sale":
        raise ValueError("Cannot apply credit to a quotation.")
    if int(row["customer_id"]) != payload.customer_id:
        raise ValueError("Sale does not belong to the specified customer.")

    from .sales_rules import get_sale_financial_summary
    remaining = get_sale_financial_summary(conn, payload.sale_id).outstanding
    if payload.amount > remaining:
        raise ValueError(
            f"Cannot apply {float(payload.amount):.2f}; "
            f"remaining due on sale is {float(remaining):.2f}."
        )

    cur = conn.execute(
        """INSERT INTO customer_advances
           (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
           VALUES (?, COALESCE(?, CURRENT_DATE), ?, 'applied_to_sale', ?, ?, ?)""",
        (payload.customer_id, payload.date, -float(payload.amount),
         payload.sale_id, payload.notes, payload.created_by),
    )
    return CustomerCreditApplicationResult(
        tx_id=int(cur.lastrowid),
        customer_id=payload.customer_id,
        sale_id=payload.sale_id,
        amount=payload.amount,
    )


def get_customer_refunds(conn: Connection, customer_id: int) -> tuple[CustomerRefundRow, ...]:
    rows = conn.execute(
        "SELECT sp.payment_id, sp.sale_id, sp.date, sp.amount, sp.method, "
        "sp.clearing_state, sp.notes "
        "FROM sale_payments sp JOIN sales s ON s.sale_id = sp.sale_id "
        "WHERE s.customer_id = ? AND sp.amount < 0 "
        "ORDER BY sp.date ASC, sp.payment_id ASC",
        (customer_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        res.append(
            CustomerRefundRow(
                payment_id=d["payment_id"], sale_id=d["sale_id"], date=d["date"],
                amount=Decimal(str(abs(d["amount"] or 0))),
                method=d["method"], clearing_state=d.get("clearing_state"),
                notes=d.get("notes"),
            )
        )
    return tuple(res)
