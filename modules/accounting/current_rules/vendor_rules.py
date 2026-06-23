"""Future home for extracted vendor accounting behavior.

These rules will mirror current code first. They are not assumed correct.
"""

from __future__ import annotations

import logging
import sqlite3
from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    SupplierRefundMetadata,
    SupplierRefundPayload,
    SupplierRefundResult,
    SupplierRefundRow,
    VendorBalance,
    VendorAdvancePayload,
    VendorAdvanceResult,
    VendorCreditLedgerRow,
    VendorOpenPurchase,
    VendorPaymentEffect,
    VendorPaymentMetadata,
    VendorPaymentPayload,
    VendorPaymentResult,
    VendorPurchaseTotals,
)
from ..validators import validate_supplier_refund_metadata, validate_vendor_payment_metadata

_log = logging.getLogger(__name__)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _row_value(row: object, key: str, index: int) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (TypeError, KeyError, IndexError):
        return row[index]  # type: ignore[index]


def _row_dict(row: object, keys: tuple[str, ...]) -> dict:
    if hasattr(row, "keys"):
        return dict(row)  # type: ignore[arg-type]
    return {key: row[index] for index, key in enumerate(keys)}  # type: ignore[index]


def get_vendor_advance_balance(conn: Connection, vendor_id: int) -> VendorBalance:
    row = conn.execute(
        "SELECT balance FROM v_vendor_advance_balance WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    balance = _decimal(_row_value(row, "balance", 0) if row else 0)
    return VendorBalance(vendor_id=int(vendor_id), balance=balance)


def get_vendor_advance_balances(
    conn: Connection,
    vendor_ids: tuple[int, ...],
) -> dict[int, VendorBalance]:
    ids = tuple(int(vendor_id) for vendor_id in vendor_ids if vendor_id is not None)
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT v.vendor_id, COALESCE(b.balance, 0.0) AS balance
        FROM vendors v
        LEFT JOIN v_vendor_advance_balance b ON b.vendor_id = v.vendor_id
        WHERE v.vendor_id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {
        int(_row_value(row, "vendor_id", 0)): VendorBalance(
            vendor_id=int(_row_value(row, "vendor_id", 0)),
            balance=_decimal(_row_value(row, "balance", 1)),
        )
        for row in rows
    }


def list_vendor_purchases(
    conn: Connection,
    vendor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[dict, ...]:
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

    rows = conn.execute("\n".join(sql), params).fetchall()
    keys = ("purchase_id", "date", "total_amount", "net_total_amount")
    return tuple(_row_dict(row, keys) for row in rows)


def get_vendor_purchase_totals(
    conn: Connection,
    vendor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> VendorPurchaseTotals:
    row = conn.execute(
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
        (
            [vendor_id]
            + ([date_from] if date_from else [])
            + ([date_to] if date_to else [])
        ),
    ).fetchone()
    return VendorPurchaseTotals(
        vendor_id=int(vendor_id),
        purchases_total=_decimal(_row_value(row, "purchases_total", 0)),
        paid_total=_decimal(_row_value(row, "paid_total", 1)),
        advance_applied_total=_decimal(_row_value(row, "advance_applied_total", 2)),
    )


def get_vendor_open_purchases(
    conn: Connection,
    vendor_id: int,
) -> tuple[VendorOpenPurchase, ...]:
    rows = conn.execute(
        """
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
        """,
        (vendor_id,),
    ).fetchall()
    out: list[VendorOpenPurchase] = []
    for row in rows:
        purchase_id = _row_value(row, "purchase_id", 0)
        date = _row_value(row, "date", 1)
        calculated_total = _decimal(_row_value(row, "calculated_total_amount", 2))
        total = _decimal(_row_value(row, "total_amount", 3))
        paid = _decimal(_row_value(row, "paid_amount", 4))
        applied = _decimal(_row_value(row, "advance_payment_applied", 5))
        balance = _decimal(_row_value(row, "balance", 6))
        out.append(
            VendorOpenPurchase(
                purchase_id=purchase_id,
                vendor_id=int(vendor_id),
                purchase_date=date,
                reference=str(purchase_id),
                net_total=calculated_total,
                outstanding=balance,
                total_amount=total,
                paid_amount=paid,
                advance_payment_applied=applied,
                calculated_total_amount=calculated_total,
            )
        )
    return tuple(out)


def _list_vendor_payments(
    conn: Connection,
    vendor_id: int,
    date_from: str | None,
    date_to: str | None,
) -> tuple[dict, ...]:
    sql = [
        """
        SELECT
          pp.payment_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.instrument_type,
          pp.instrument_no,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.purchase_id
        FROM purchase_payments pp
        JOIN purchases p ON p.purchase_id = pp.purchase_id
        WHERE p.vendor_id = ?
        """,
    ]
    params: list[object] = [vendor_id]
    if date_from:
        sql.append("AND DATE(pp.date) >= DATE(?)")
        params.append(date_from)
    if date_to:
        sql.append("AND DATE(pp.date) <= DATE(?)")
        params.append(date_to)
    sql.append("ORDER BY DATE(pp.date) ASC, pp.payment_id ASC")
    rows = conn.execute("\n".join(sql), params).fetchall()
    keys = (
        "payment_id",
        "date",
        "amount",
        "method",
        "instrument_type",
        "instrument_no",
        "bank_account_id",
        "vendor_bank_account_id",
        "clearing_state",
        "ref_no",
        "notes",
        "purchase_id",
    )
    return tuple(_row_dict(row, keys) for row in rows)


def _list_vendor_advances(
    conn: Connection,
    vendor_id: int,
    date_from: str | None,
    date_to: str | None,
) -> tuple[dict, ...]:
    sql = [
        """
        SELECT
          va.tx_id,
          va.tx_date,
          CAST(va.amount AS REAL) AS amount,
          va.source_type,
          va.source_id,
          va.method,
          va.bank_account_id,
          va.vendor_bank_account_id,
          va.instrument_type,
          va.instrument_no,
          va.instrument_date,
          va.deposited_date,
          va.cleared_date,
          va.clearing_state,
          va.ref_no,
          va.temp_vendor_bank_name,
          va.temp_vendor_bank_number,
          va.notes,
          va.created_by
        FROM vendor_advances va
        WHERE va.vendor_id = ?
        """,
    ]
    params: list[object] = [vendor_id]
    if date_from:
        sql.append("AND DATE(va.tx_date) >= DATE(?)")
        params.append(date_from)
    if date_to:
        sql.append("AND DATE(va.tx_date) <= DATE(?)")
        params.append(date_to)
    sql.append("ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC")
    rows = conn.execute("\n".join(sql), params).fetchall()
    keys = (
        "tx_id",
        "tx_date",
        "amount",
        "source_type",
        "source_id",
        "method",
        "bank_account_id",
        "vendor_bank_account_id",
        "instrument_type",
        "instrument_no",
        "instrument_date",
        "deposited_date",
        "cleared_date",
        "clearing_state",
        "ref_no",
        "temp_vendor_bank_name",
        "temp_vendor_bank_number",
        "notes",
        "created_by",
    )
    return tuple(_row_dict(row, keys) for row in rows)


def _list_return_values_by_purchase(conn: Connection, purchase_id: str) -> tuple[dict, ...]:
    rows = conn.execute(
        """
        SELECT
          transaction_id,
          item_id,
          CAST(qty_returned AS REAL) AS qty_returned,
          CAST(unit_buy_price AS REAL) AS unit_buy_price,
          CAST(unit_discount AS REAL) AS unit_discount,
          return_date,
          valuation_status,
          CAST(return_value AS REAL) AS return_value,
          CAST(return_value AS REAL) AS line_value,
          CAST(return_value AS REAL) AS value
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """,
        (purchase_id,),
    ).fetchall()
    keys = (
        "transaction_id",
        "item_id",
        "qty_returned",
        "unit_buy_price",
        "unit_discount",
        "return_date",
        "valuation_status",
        "return_value",
        "line_value",
        "value",
    )
    return tuple(_row_dict(row, keys) for row in rows)


def get_vendor_statement(
    conn: Connection,
    vendor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    include_opening: bool = True,
    show_return_origins: bool = False,
) -> dict:
    opening_credit = 0.0
    opening_payable = 0.0
    if include_opening and date_from:
        row = conn.execute(
            """
            WITH pre_period_purchases AS (
                SELECT COALESCE(
                    SUM(CAST(COALESCE(pdt.calculated_total_amount, p.total_amount) AS REAL)),
                    0.0
                ) AS amount
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                WHERE p.vendor_id = ?
                  AND DATE(p.date) < DATE(?)
            ),
            pre_period_payments AS (
                SELECT COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS amount
                FROM purchase_payments pp
                JOIN purchases p ON p.purchase_id = pp.purchase_id
                WHERE p.vendor_id = ?
                  AND LOWER(COALESCE(pp.clearing_state, '')) = 'cleared'
                  AND DATE(pp.date) < DATE(?)
            ),
            pre_period_refunds AS (
                SELECT COALESCE(SUM(CAST(pr.amount AS REAL)), 0.0) AS amount
                FROM purchase_refunds pr
                WHERE pr.vendor_id = ?
                  AND pr.clearing_state = 'cleared'
                  AND DATE(pr.date) < DATE(?)
            ),
            pre_period_deposits AS (
                SELECT COALESCE(SUM(CAST(va.amount AS REAL)), 0.0) AS amount
                FROM vendor_advances va
                WHERE va.vendor_id = ?
                  AND va.source_type = 'deposit'
                  AND DATE(va.tx_date) < DATE(?)
            )
            SELECT
                pre_period_deposits.amount AS opening_credit,
                pre_period_purchases.amount
                  - pre_period_payments.amount
                  - pre_period_deposits.amount
                  + pre_period_refunds.amount AS opening_payable
            FROM pre_period_purchases, pre_period_payments,
                 pre_period_refunds, pre_period_deposits
            """,
            (
                vendor_id,
                date_from,
                vendor_id,
                date_from,
                vendor_id,
                date_from,
                vendor_id,
                date_from,
            ),
        ).fetchone()
        if row:
            opening_credit = float(_row_value(row, "opening_credit", 0))
            opening_payable = float(_row_value(row, "opening_payable", 1))

    rows: list[dict] = []
    for purchase in list_vendor_purchases(conn, vendor_id, date_from, date_to):
        amount = float(purchase["net_total_amount"])
        rows.append(
            {
                "date": purchase["date"],
                "type": "Purchase",
                "doc_id": purchase["purchase_id"],
                "reference": {},
                "amount": amount,
                "amount_effect": amount,
            }
        )

    for payment in _list_vendor_payments(conn, vendor_id, date_from, date_to):
        if str(payment["clearing_state"] or "").lower() != "cleared":
            continue
        amount = float(payment["amount"])
        row_type = "Cash Payment" if amount >= 0 else "Refund"
        rows.append(
            {
                "date": payment["date"],
                "type": row_type,
                "doc_id": payment["purchase_id"],
                "reference": {
                    "payment_id": payment["payment_id"],
                    "method": payment["method"],
                    "instrument_no": payment["instrument_no"],
                    "instrument_type": payment["instrument_type"],
                    "bank_account_id": payment["bank_account_id"],
                    "vendor_bank_account_id": payment["vendor_bank_account_id"],
                    "ref_no": payment["ref_no"],
                    "clearing_state": payment["clearing_state"],
                },
                "amount": abs(amount),
                "amount_effect": -amount,
            }
        )

    refund_sql = [
        """
        SELECT refund_id, purchase_id, date, CAST(amount AS REAL) AS amount,
               method, instrument_no, instrument_type, bank_account_id,
               vendor_bank_account_id, ref_no, clearing_state
        FROM purchase_refunds
        WHERE vendor_id = ? AND clearing_state = 'cleared'
        """,
    ]
    refund_params: list[object] = [vendor_id]
    if date_from:
        refund_sql.append("AND DATE(date) >= DATE(?)")
        refund_params.append(date_from)
    if date_to:
        refund_sql.append("AND DATE(date) <= DATE(?)")
        refund_params.append(date_to)
    try:
        refund_rows = conn.execute("\n".join(refund_sql), refund_params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: purchase_refunds" not in str(exc):
            raise
        refund_rows = []
    for refund in refund_rows:
        amount = float(_row_value(refund, "amount", 3))
        rows.append(
            {
                "date": _row_value(refund, "date", 2),
                "type": "Refund",
                "doc_id": _row_value(refund, "purchase_id", 1),
                "reference": {
                    "refund_id": _row_value(refund, "refund_id", 0),
                    "method": _row_value(refund, "method", 4),
                    "instrument_no": _row_value(refund, "instrument_no", 5),
                    "instrument_type": _row_value(refund, "instrument_type", 6),
                    "bank_account_id": _row_value(refund, "bank_account_id", 7),
                    "vendor_bank_account_id": _row_value(
                        refund, "vendor_bank_account_id", 8
                    ),
                    "ref_no": _row_value(refund, "ref_no", 9),
                    "clearing_state": _row_value(refund, "clearing_state", 10),
                },
                "amount": amount,
                "amount_effect": amount,
            }
        )

    credit_note_rows_to_enrich: list[tuple[int, dict]] = []

    def advance_reference(advance: dict) -> dict:
        ref = {"tx_id": advance["tx_id"]}
        for key in (
            "method",
            "bank_account_id",
            "vendor_bank_account_id",
            "instrument_type",
            "instrument_no",
            "instrument_date",
            "clearing_state",
            "ref_no",
            "temp_vendor_bank_name",
            "temp_vendor_bank_number",
        ):
            if key in advance:
                ref[key] = advance[key]
        return ref

    for advance in _list_vendor_advances(conn, vendor_id, date_from, date_to):
        amount = float(advance["amount"])
        source_type = (advance["source_type"] or "").lower()
        if source_type == "return_credit":
            row = {
                "date": advance["tx_date"],
                "type": "Credit Note",
                "doc_id": advance["source_id"],
                "reference": advance_reference(advance),
                "amount": abs(amount),
                "amount_effect": 0.0,
            }
            rows.append(row)
            if show_return_origins and advance["source_id"]:
                credit_note_rows_to_enrich.append((advance["tx_id"], row))
        elif source_type == "applied_to_purchase":
            rows.append(
                {
                    "date": advance["tx_date"],
                    "type": "Credit Applied",
                    "doc_id": advance["source_id"],
                    "reference": advance_reference(advance),
                    "amount": abs(amount),
                    "amount_effect": 0.0,
                }
            )
        else:
            rows.append(
                {
                    "date": advance["tx_date"],
                    "type": "Credit Note",
                    "doc_id": advance["source_id"],
                    "reference": advance_reference(advance),
                    "amount": abs(amount),
                    "amount_effect": -amount,
                }
            )

    if show_return_origins and credit_note_rows_to_enrich:
        for _tx_id, row in credit_note_rows_to_enrich:
            purchase_id = row.get("doc_id")
            if purchase_id:
                try:
                    lines = _list_return_values_by_purchase(conn, purchase_id)
                    if lines:
                        row.setdefault("reference", {})["lines"] = list(lines)
                except Exception:
                    _log.exception(
                        "Failed to load return-origin lines for purchase_id=%s",
                        purchase_id,
                    )

    type_order = {
        "Purchase": 1,
        "Cash Payment": 2,
        "Refund": 3,
        "Credit Note": 4,
        "Credit Applied": 5,
    }

    def tie_value(row: dict):
        ref = row.get("reference", {}) or {}
        return (
            row.get("doc_id")
            or ref.get("payment_id")
            or ref.get("refund_id")
            or ref.get("tx_id")
            or ""
        )

    rows.sort(key=lambda row: (row["date"], type_order.get(row["type"], 9), tie_value(row)))
    balance = opening_payable
    totals = {
        "purchases": 0.0,
        "cash_paid": 0.0,
        "refunds": 0.0,
        "credit_notes": 0.0,
        "credit_applied": 0.0,
    }
    out_rows: list[dict] = []
    for row in rows:
        balance += float(row["amount_effect"])
        out_row = dict(row)
        out_row["balance_after"] = balance
        out_rows.append(out_row)
        if row["type"] == "Purchase":
            totals["purchases"] += abs(float(row["amount"]))
        elif row["type"] == "Cash Payment":
            totals["cash_paid"] += abs(float(row["amount"]))
        elif row["type"] == "Refund":
            totals["refunds"] += abs(float(row["amount"]))
        elif row["type"] == "Credit Note":
            totals["credit_notes"] += abs(float(row["amount"]))
        elif row["type"] == "Credit Applied":
            totals["credit_applied"] += abs(float(row["amount"]))

    try:
        from ....database.repositories.company_info_repo import get_invoice_company_context
    except ImportError:
        from database.repositories.company_info_repo import get_invoice_company_context

    return {
        "vendor_id": vendor_id,
        "company": get_invoice_company_context(conn),
        "period": {"from": date_from, "to": date_to},
        "opening_credit": opening_credit,
        "opening_payable": opening_payable,
        "rows": out_rows,
        "totals": totals,
        "closing_balance": balance,
    }


def _purchase_payment_position(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[int, Decimal, Decimal, Decimal]:
    row = conn.execute(
        """
        SELECT
            COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
            COALESCE(p.paid_amount, 0.0) AS paid_amount,
            COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied,
            p.vendor_id
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Purchase not found: {purchase_id}")
    return (
        int(row["vendor_id"]),
        _decimal(row["total_calc"]),
        _decimal(row["paid_amount"]),
        _decimal(row["advance_payment_applied"]),
    )


def preview_vendor_payment_effect(
    conn: Connection,
    payload: VendorPaymentPayload,
) -> VendorPaymentEffect:
    if payload.amount <= 0:
        raise ValueError("Vendor purchase payment amount must be greater than zero")
    state = payload.clearing_state or "cleared"
    vendor_id, total_amount, current_paid, current_advance = _purchase_payment_position(
        conn,
        payload.purchase_id,
    )
    validate_vendor_payment_metadata(
        conn,
        VendorPaymentMetadata(
            vendor_id=vendor_id,
            method=payload.method,
            bank_account_id=payload.bank_account_id,
            vendor_bank_account_id=payload.vendor_bank_account_id,
            instrument_type=payload.instrument_type,
            instrument_no=payload.instrument_no,
            clearing_state=state,
            temp_vendor_bank_name=payload.temp_vendor_bank_name,
            temp_vendor_bank_number=payload.temp_vendor_bank_number,
            vendor_label="purchase",
        ),
    )
    amount_due = max(Decimal("0"), total_amount - current_paid - current_advance)
    payment_amount = payload.amount
    overpayment_credit = Decimal("0")
    if payload.amount > amount_due + Decimal("0.000000001"):
        overpayment_credit = payload.amount - amount_due
        payment_amount = amount_due
    return VendorPaymentEffect(
        purchase_id=payload.purchase_id,
        vendor_id=vendor_id,
        amount_due=amount_due,
        payment_amount=payment_amount,
        overpayment_credit=overpayment_credit,
    )


def _record_vendor_deposit_credit(
    conn: Connection,
    *,
    vendor_id: int,
    amount: Decimal,
    date: str,
    notes: str,
    created_by: int | None,
    source_id: int | str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id, notes, created_by
        )
        VALUES (?, ?, ?, 'deposit', ?, ?, ?)
        """,
        (vendor_id, date, float(amount), source_id, notes, created_by),
    )
    return int(cur.lastrowid)


def record_vendor_payment_event(
    conn: Connection,
    payload: VendorPaymentPayload,
) -> VendorPaymentResult:
    effect = preview_vendor_payment_effect(conn, payload)
    state = payload.clearing_state or "cleared"
    cleared_date = payload.cleared_date or payload.date
    credit_tx_id: int | None = None

    if effect.overpayment_credit > Decimal("0.000000001"):
        credit_tx_id = _record_vendor_deposit_credit(
            conn,
            vendor_id=effect.vendor_id,
            amount=effect.overpayment_credit,
            date=payload.date,
            notes=f"Excess payment converted to vendor credit on {payload.purchase_id}",
            created_by=payload.created_by,
            source_id=payload.purchase_id,
        )
        if effect.payment_amount <= Decimal("0.000000001"):
            return VendorPaymentResult(
                payment_id=None,
                credit_tx_id=credit_tx_id,
                effect=effect,
            )

    cur = conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id,
            date,
            amount,
            method,
            bank_account_id,
            vendor_bank_account_id,
            instrument_type,
            instrument_no,
            instrument_date,
            deposited_date,
            cleared_date,
            clearing_state,
            ref_no,
            notes,
            created_by,
            temp_vendor_bank_name,
            temp_vendor_bank_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.purchase_id,
            payload.date,
            float(effect.payment_amount),
            payload.method,
            payload.bank_account_id,
            payload.vendor_bank_account_id,
            payload.instrument_type,
            payload.instrument_no,
            payload.instrument_date,
            payload.deposited_date,
            cleared_date,
            state,
            payload.ref_no,
            payload.notes,
            payload.created_by,
            payload.temp_vendor_bank_name,
            payload.temp_vendor_bank_number,
        ),
    )
    payment_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload.created_by,
            "payment",
            "purchase_payments",
            payment_id,
            f"Recorded payment of {float(effect.payment_amount):g} using {payload.method}. Purchase ID: {payload.purchase_id}",
        ),
    )
    return VendorPaymentResult(
        payment_id=payment_id,
        credit_tx_id=credit_tx_id,
        effect=effect,
    )


def update_vendor_payment_state(
    conn: Connection,
    payment_id: int,
    *,
    clearing_state: str,
    cleared_date: str | None = None,
    notes: str | None = None,
) -> int:
    if clearing_state != "cleared":
        raise ValueError("Vendor purchase payments must remain cleared")
    sets = ["clearing_state = ?"]
    params: list[object] = [clearing_state]
    if cleared_date is not None:
        sets.append("cleared_date = ?")
        params.append(cleared_date)
    if notes is not None:
        sets.append("notes = ?")
        params.append(notes)
    params.append(payment_id)
    cur = conn.execute(
        f"UPDATE purchase_payments SET {', '.join(sets)} WHERE payment_id = ?",
        params,
    )
    return cur.rowcount


def record_vendor_advance_event(
    conn: Connection,
    payload: VendorAdvancePayload,
) -> VendorAdvanceResult:
    if payload.amount <= 0:
        raise ValueError("amount must be positive when granting credit")
    allowed_types = {"deposit", "return_credit"}
    source_type = (payload.source_type or "deposit").lower()
    if source_type not in allowed_types:
        raise ValueError(
            f"source_type must be one of {allowed_types}, got {payload.source_type!r}"
        )
    validate_vendor_payment_metadata(
        conn,
        VendorPaymentMetadata(
            vendor_id=payload.vendor_id,
            method=payload.method,
            bank_account_id=payload.bank_account_id,
            vendor_bank_account_id=payload.vendor_bank_account_id,
            instrument_type=payload.instrument_type,
            clearing_state=payload.clearing_state,
            vendor_label="advance",
            reject_card=True,
        ),
    )

    metadata_values = {
        "method": payload.method,
        "bank_account_id": payload.bank_account_id,
        "vendor_bank_account_id": payload.vendor_bank_account_id,
        "instrument_type": payload.instrument_type,
        "instrument_no": payload.instrument_no,
        "instrument_date": payload.instrument_date,
        "deposited_date": payload.deposited_date,
        "cleared_date": payload.cleared_date,
        "clearing_state": payload.clearing_state,
        "ref_no": payload.ref_no,
        "temp_vendor_bank_name": payload.temp_vendor_bank_name,
        "temp_vendor_bank_number": payload.temp_vendor_bank_number,
    }
    existing_cols = {
        str(row["name"] if hasattr(row, "keys") else row[1])
        for row in conn.execute("PRAGMA table_info(vendor_advances);").fetchall()
    }
    metadata_cols = [col for col, value in metadata_values.items() if value is not None]
    missing_cols = [col for col in metadata_cols if col not in existing_cols]
    if missing_cols:
        raise ValueError(
            "Vendor advance payment metadata columns are missing: "
            + ", ".join(sorted(missing_cols))
        )

    columns = ["vendor_id", "tx_date", "amount", "source_type", "source_id"]
    values: list[object] = [
        payload.vendor_id,
        payload.date,
        float(payload.amount),
        source_type,
        payload.source_id,
    ]
    for col, value in metadata_values.items():
        if col in existing_cols:
            columns.append(col)
            values.append(value)
    columns.extend(["notes", "created_by"])
    values.extend([payload.notes, payload.created_by])

    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"""
        INSERT INTO vendor_advances (
            {", ".join(columns)}
        )
        VALUES ({placeholders})
        """,
        values,
    )
    return VendorAdvanceResult(
        tx_id=int(cur.lastrowid),
        vendor_id=payload.vendor_id,
        amount=payload.amount,
        source_type=source_type,
    )


def record_supplier_refund_event(
    conn: Connection,
    payload: SupplierRefundPayload,
) -> SupplierRefundResult:
    if payload.amount <= 0:
        raise ValueError("amount must be positive when recording supplier refund")
    validate_supplier_refund_metadata(
        conn,
        SupplierRefundMetadata(
            vendor_id=payload.vendor_id,
            method=payload.method,
            bank_account_id=payload.bank_account_id,
            vendor_bank_account_id=payload.vendor_bank_account_id,
            instrument_type=payload.instrument_type,
            instrument_no=payload.instrument_no,
            clearing_state=payload.clearing_state,
            temp_vendor_bank_name=payload.temp_vendor_bank_name,
            temp_vendor_bank_number=payload.temp_vendor_bank_number,
            vendor_label="purchase",
        ),
    )

    returned_value_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(return_value AS REAL)), 0.0) AS val FROM purchase_return_valuations WHERE purchase_id = ?",
        (payload.purchase_id,)
    ).fetchone()
    returned_value = Decimal(str(returned_value_row["val"] if returned_value_row else 0.0))

    prior_refunds_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS val FROM purchase_refunds WHERE purchase_id = ? AND clearing_state = 'cleared'",
        (payload.purchase_id,)
    ).fetchone()
    prior_refunds = Decimal(str(prior_refunds_row["val"] if prior_refunds_row else 0.0))

    prior_credits_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS val FROM vendor_advances WHERE source_id = ? AND source_type = 'return_credit'",
        (payload.purchase_id,)
    ).fetchone()
    prior_credits = Decimal(str(prior_credits_row["val"] if prior_credits_row else 0.0))

    remaining_refundable = returned_value - prior_refunds - prior_credits
    if payload.amount > remaining_refundable:
        raise ValueError(
            f"Supplier refund amount {payload.amount} exceeds the remaining refundable value of {remaining_refundable}"
        )

    cur = conn.execute(
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
            payload.purchase_id,
            payload.vendor_id,
            payload.date,
            float(payload.amount),
            payload.method,
            payload.bank_account_id,
            payload.vendor_bank_account_id,
            payload.instrument_type,
            payload.instrument_no,
            payload.instrument_date,
            payload.deposited_date,
            payload.cleared_date or payload.date,
            payload.ref_no,
            payload.temp_vendor_bank_name,
            payload.temp_vendor_bank_number,
            payload.notes,
            payload.created_by,
        ),
    )
    refund_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
        VALUES (?, 'refund', 'purchase_refunds', ?, ?)
        """,
        (
            payload.created_by,
            refund_id,
            f"Recorded vendor refund of {payload.amount:g}. Purchase ID: {payload.purchase_id}",
        ),
    )
    return SupplierRefundResult(
        refund_id=refund_id,
        purchase_id=payload.purchase_id,
        vendor_id=payload.vendor_id,
        amount=payload.amount,
    )


def get_supplier_refunds_for_purchase(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[SupplierRefundRow, ...]:
    rows = conn.execute(
        """
        SELECT
          refund_id, purchase_id, vendor_id, date,
          CAST(amount AS REAL) AS amount,
          method, bank_account_id, vendor_bank_account_id,
          instrument_type, instrument_no, instrument_date,
          deposited_date, cleared_date, clearing_state, ref_no,
          temp_vendor_bank_name, temp_vendor_bank_number, notes, created_by
        FROM purchase_refunds
        WHERE purchase_id = ?
        ORDER BY refund_id
        """,
        (purchase_id,),
    ).fetchall()
    return tuple(
        SupplierRefundRow(
            refund_id=int(row["refund_id"]),
            purchase_id=row["purchase_id"],
            vendor_id=int(row["vendor_id"]),
            date=row["date"],
            amount=_decimal(row["amount"]),
            method=row["method"],
            bank_account_id=row["bank_account_id"],
            vendor_bank_account_id=row["vendor_bank_account_id"],
            instrument_type=row["instrument_type"],
            instrument_no=row["instrument_no"],
            instrument_date=row["instrument_date"],
            deposited_date=row["deposited_date"],
            cleared_date=row["cleared_date"],
            clearing_state=row["clearing_state"],
            ref_no=row["ref_no"],
            temp_vendor_bank_name=row["temp_vendor_bank_name"],
            temp_vendor_bank_number=row["temp_vendor_bank_number"],
            notes=row["notes"],
            created_by=row["created_by"],
        )
        for row in rows
    )


def get_vendor_credit_ledger(
    conn: Connection,
    vendor_id: int,
) -> tuple[VendorCreditLedgerRow, ...]:
    rows = _list_vendor_advances(conn, vendor_id, None, None)
    return tuple(
        VendorCreditLedgerRow(
            tx_id=int(row["tx_id"]),
            vendor_id=int(vendor_id),
            tx_date=row["tx_date"],
            amount=_decimal(row["amount"]),
            source_type=row["source_type"],
            source_id=row["source_id"],
            notes=row.get("notes"),
        )
        for row in rows
    )


def preview_vendor_advance_allocation(
    conn: Connection,
    vendor_id: int,
    amount: Decimal,
) -> dict:
    remaining_credit = max(Decimal("0"), amount)
    open_purchases = sorted(
        get_vendor_open_purchases(conn, vendor_id),
        key=lambda purchase: (
            str(purchase.purchase_date or ""),
            str(purchase.purchase_id or ""),
        ),
    )
    rows: list[dict] = []
    for purchase in open_purchases:
        if remaining_credit <= Decimal("0.000000001"):
            break
        remaining_due = max(Decimal("0"), purchase.outstanding)
        if remaining_due <= Decimal("0.000000001"):
            continue
        amount_to_apply = min(remaining_due, remaining_credit)
        if amount_to_apply <= Decimal("0.000000001"):
            continue
        rows.append(
            {
                "purchase_id": purchase.purchase_id,
                "date": purchase.purchase_date,
                "remaining_due": float(remaining_due),
                "amount_to_apply": float(amount_to_apply),
                "remaining_due_after": float(
                    max(Decimal("0"), remaining_due - amount_to_apply)
                ),
            }
        )
        remaining_credit -= amount_to_apply
    return {
        "total_credit": float(max(Decimal("0"), amount)),
        "rows": rows,
        "remaining_credit": float(max(Decimal("0"), remaining_credit)),
    }


def _apply_vendor_credit_to_purchase(
    conn: Connection,
    *,
    vendor_id: int,
    purchase_id: int | str,
    amount: float,
    date: str,
    notes: str | None,
    created_by: int | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id, notes, created_by
        )
        VALUES (?, ?, ?, 'applied_to_purchase', ?, ?, ?)
        """,
        (vendor_id, date, -abs(float(amount)), purchase_id, notes, created_by),
    )
    return int(cur.lastrowid)


def record_vendor_advance_with_auto_apply(
    conn: Connection,
    payload: VendorAdvancePayload,
) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        preview = preview_vendor_advance_allocation(
            conn,
            payload.vendor_id,
            payload.amount,
        )
        result = record_vendor_advance_event(conn, payload)
        for row in preview["rows"]:
            _apply_vendor_credit_to_purchase(
                conn,
                vendor_id=payload.vendor_id,
                purchase_id=row["purchase_id"],
                amount=row["amount_to_apply"],
                date=payload.date,
                notes=f"Auto-applied from vendor advance (Tx #{result.tx_id})",
                created_by=payload.created_by,
            )
            _log.info(
                f"Auto-applied {row['amount_to_apply']:.2f} of vendor advance "
                f"to purchase {row['purchase_id']}"
            )
        conn.execute("COMMIT")
        return {
            "tx_id": result.tx_id,
            "applied_amount": float(payload.amount) - preview["remaining_credit"],
            "remaining_credit": preview["remaining_credit"],
            "rows": preview["rows"],
        }
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
