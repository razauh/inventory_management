"""Current bank metadata validation behavior."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection

from ..dto import BankBalance, BankLedgerRow, CustomerCashMovement, VendorCashMovement


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def validate_company_bank_account_active(
    conn: Connection,
    bank_account_id: int | None,
) -> None:
    # ACC-RULE-008: Active company bank account required
    # Requires referenced company bank accounts to exist and be active.
    # Uses company_bank_accounts before payment and refund writes.
    # Protects cash and bank movements from inactive accounts.
    if bank_account_id is None:
        return
    row = conn.execute(
        "SELECT is_active FROM company_bank_accounts WHERE account_id = ?",
        (bank_account_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Company bank account not found: {bank_account_id}")
    if int(row["is_active"]) != 1:
        raise ValueError(
            "Selected company bank account is inactive and cannot be used for new transactions."
        )


def validate_vendor_bank_account(
    conn: Connection,
    *,
    vendor_id: int,
    vendor_bank_account_id: int | None,
    vendor_label: str,
) -> None:
    # ACC-RULE-009: Active vendor bank account ownership
    # Requires vendor bank accounts to exist, be active, and match vendor.
    # Uses vendor_bank_accounts for outgoing vendor payment destinations.
    # Protects vendor payments from posting to another vendor account.
    if vendor_bank_account_id is None:
        return
    row = conn.execute(
        """
        SELECT vendor_id, is_active
        FROM vendor_bank_accounts
        WHERE vendor_bank_account_id = ?
        """,
        (vendor_bank_account_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Vendor bank account not found: {vendor_bank_account_id}")
    if int(row["vendor_id"]) != int(vendor_id):
        raise ValueError(f"Vendor bank account does not belong to the {vendor_label} vendor")
    if int(row["is_active"]) != 1:
        raise ValueError(
            "Selected vendor bank account is inactive and cannot be used for new transactions."
        )


def get_bank_balance(conn: Connection, bank_account_id: int) -> BankBalance:
    # ACC-RULE-010: Bank balance from cleared ledger
    # Calculates bank balance as ledger inflows minus outflows.
    # Uses bank ledger rows for a single company bank account.
    # Supports account balance display from cleared cash movement state.
    balance = sum(
        (
            row.amount_in - row.amount_out
            for row in get_bank_ledger(conn, account_id=bank_account_id)
        ),
        Decimal("0"),
    )
    return BankBalance(bank_account_id=int(bank_account_id), balance=balance)


def get_vendor_cash_movements(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[VendorCashMovement, ...]:
    # ACC-RULE-011: Vendor cash movement classification
    # Reports cleared vendor payments and advances as outflows.
    # Reports cleared supplier refunds as inflows.
    # Supports cash activity reports for payable-side transactions.
    date_where = ""
    params: list[object] = []
    if start_date is not None:
        date_where += " AND movement_date >= ?"
        params.append(start_date)
    if end_date is not None:
        date_where += " AND movement_date <= ?"
        params.append(end_date)
    rows = conn.execute(
        f"""
        WITH movements AS (
          SELECT
            pp.cleared_date AS movement_date,
            'Disbursement' AS movement_type,
            CAST(pp.amount AS REAL) AS amount,
            'outflow' AS direction,
            pp.method,
            pp.clearing_state AS status,
            pp.purchase_id AS doc_id,
            pp.notes
          FROM purchase_payments pp
          WHERE pp.clearing_state = 'cleared'
            AND pp.cleared_date IS NOT NULL
            AND CAST(pp.amount AS REAL) > 0
          UNION ALL
          SELECT
            COALESCE(va.cleared_date, va.tx_date) AS movement_date,
            'Vendor Advance' AS movement_type,
            CAST(va.amount AS REAL) AS amount,
            'outflow' AS direction,
            va.method,
            COALESCE(va.clearing_state, 'cleared') AS status,
            va.source_id AS doc_id,
            va.notes
          FROM vendor_advances va
          WHERE va.source_type = 'deposit'
            AND CAST(va.amount AS REAL) > 0
            AND COALESCE(va.clearing_state, 'cleared') = 'cleared'
          UNION ALL
          SELECT
            pr.cleared_date AS movement_date,
            'Vendor Refund' AS movement_type,
            CAST(pr.amount AS REAL) AS amount,
            'inflow' AS direction,
            pr.method,
            pr.clearing_state AS status,
            pr.purchase_id AS doc_id,
            pr.notes
          FROM purchase_refunds pr
          WHERE pr.clearing_state = 'cleared'
            AND pr.cleared_date IS NOT NULL
        )
        SELECT *
        FROM movements
        WHERE 1 = 1 {date_where}
        ORDER BY movement_date, movement_type, doc_id
        """,
        params,
    ).fetchall()
    return tuple(
        VendorCashMovement(
            date=row["movement_date"],
            type=row["movement_type"],
            amount=_decimal(row["amount"]),
            direction=row["direction"],
            method=row["method"],
            status=row["status"],
            doc_id=row["doc_id"],
            notes=row["notes"],
        )
        for row in rows
    )


def get_customer_cash_movements(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[CustomerCashMovement, ...]:
    # ACC-RULE-012: Customer cash movement classification
    # Reports cleared sale payments as receipts or refunds by sign.
    # Reports customer deposit credits as inflows.
    # Supports cash activity reports for receivable-side transactions.
    date_where = ""
    params: list[object] = []
    if start_date is not None:
        date_where += " AND movement_date >= ?"
        params.append(start_date)
    if end_date is not None:
        date_where += " AND movement_date <= ?"
        params.append(end_date)
    rows = conn.execute(
        f"""
        WITH movements AS (
          SELECT sp.cleared_date AS movement_date,
                 CASE WHEN CAST(sp.amount AS REAL) > 0 THEN 'Receipt' ELSE 'Refund' END AS movement_type,
                 ABS(CAST(sp.amount AS REAL)) AS amount,
                 CASE WHEN CAST(sp.amount AS REAL) > 0 THEN 'inflow' ELSE 'outflow' END AS direction,
                 sp.method, sp.clearing_state AS status, sp.sale_id AS doc_id, sp.notes
          FROM sale_payments sp
          WHERE sp.clearing_state = 'cleared' AND sp.cleared_date IS NOT NULL
          UNION ALL
          SELECT ca.tx_date AS movement_date,
                 'Customer Credit' AS movement_type,
                 CAST(ca.amount AS REAL) AS amount,
                 CASE WHEN CAST(ca.amount AS REAL) > 0 THEN 'inflow' ELSE 'outflow' END AS direction,
                 ca.method, 'cleared' AS status, ca.source_id AS doc_id, ca.notes
          FROM customer_advances ca
          WHERE ca.source_type = 'deposit'
            AND CAST(ca.amount AS REAL) > 0
        )
        SELECT * FROM movements WHERE 1 = 1 {date_where}
        ORDER BY movement_date, movement_type, doc_id
        """,
        params,
    ).fetchall()
    return tuple(
        CustomerCashMovement(
            date=row["movement_date"],
            type=row["movement_type"],
            amount=_decimal(row["amount"]),
            direction=row["direction"],
            method=row["method"],
            status=row["status"],
            doc_id=row["doc_id"],
            notes=row["notes"],
        )
        for row in rows
    )


def get_bank_ledger(
    conn: Connection,
    start_date: str | None = None,
    end_date: str | None = None,
    account_id: int | None = None,
) -> tuple[BankLedgerRow, ...]:
    """
    ACC-RULE-013: Bank ledger cleared-date basis
    Builds bank ledger rows only from cleared cash movements.
    Splits sale receipts, refunds, purchase payments, supplier refunds, and advances.
    Supports account ledger display and balance calculation.

    Get bank ledger entries.
    Uses cleared_date semantics for filtering and ordering.
    """
    part_params = []
    if start_date is not None:
        part_params.append(start_date)
    if end_date is not None:
        part_params.append(end_date)
    if account_id is not None:
        part_params.append(account_id)

    params = part_params * 4

    conds = []
    if start_date is not None:
        conds.append("cleared_date >= ?")
    if end_date is not None:
        conds.append("cleared_date <= ?")
    if account_id is not None:
        conds.append("bank_account_id = ?")
    conds_sql = " AND ".join([""] + conds) if conds else ""

    va_conds = []
    if start_date is not None:
        va_conds.append("COALESCE(cleared_date, tx_date) >= ?")
    if end_date is not None:
        va_conds.append("COALESCE(cleared_date, tx_date) <= ?")
    if account_id is not None:
        va_conds.append("bank_account_id = ?")
    va_conds_sql = " AND ".join([""] + va_conds) if va_conds else ""

    query = f"""
        SELECT
          'sale' AS src,
          sp.payment_id,
          sp.cleared_date AS date,
          CASE WHEN sp.amount > 0 THEN CAST(sp.amount AS REAL) ELSE 0.0 END AS amount_in,
          CASE WHEN sp.amount < 0 THEN CAST(-sp.amount AS REAL) ELSE 0.0 END AS amount_out,
          sp.method, sp.instrument_type, sp.instrument_no,
          sp.bank_account_id, NULL AS vendor_bank_account_id, sp.sale_id AS doc_id
        FROM sale_payments sp
        WHERE sp.clearing_state = 'cleared'
          AND sp.cleared_date IS NOT NULL
          {conds_sql}
        UNION ALL
        SELECT
          'purchase' AS src,
          pp.payment_id,
          pp.cleared_date AS date,
          CASE WHEN pp.amount < 0 THEN CAST(-pp.amount AS REAL) ELSE 0.0 END AS amount_in,
          CASE WHEN pp.amount > 0 THEN CAST(pp.amount AS REAL) ELSE 0.0 END AS amount_out,
          pp.method, pp.instrument_type, pp.instrument_no,
          pp.bank_account_id, pp.vendor_bank_account_id, pp.purchase_id AS doc_id
        FROM purchase_payments pp
        WHERE pp.clearing_state = 'cleared'
          AND pp.cleared_date IS NOT NULL
          {conds_sql}
        UNION ALL
        SELECT
          'purchase_refund' AS src,
          pr.refund_id AS payment_id,
          pr.cleared_date AS date,
          CAST(pr.amount AS REAL) AS amount_in,
          0.0 AS amount_out,
          pr.method, pr.instrument_type, pr.instrument_no,
          pr.bank_account_id, pr.vendor_bank_account_id, pr.purchase_id AS doc_id
        FROM purchase_refunds pr
        WHERE pr.clearing_state = 'cleared'
          AND pr.cleared_date IS NOT NULL
          {conds_sql}
        UNION ALL
        SELECT
          'vendor_advance' AS src,
          va.tx_id AS payment_id,
          COALESCE(va.cleared_date, va.tx_date) AS date,
          0.0 AS amount_in,
          CAST(va.amount AS REAL) AS amount_out,
          va.method, va.instrument_type, va.instrument_no,
          va.bank_account_id, va.vendor_bank_account_id, va.source_id AS doc_id
        FROM vendor_advances va
        WHERE va.source_type = 'deposit'
          AND CAST(va.amount AS REAL) > 0
          AND COALESCE(va.clearing_state, 'cleared') = 'cleared'
          {va_conds_sql}
        ORDER BY date, src, payment_id
    """

    rows = conn.execute(query, params).fetchall()
    return tuple(
        BankLedgerRow(
            src=row["src"],
            payment_id=int(row["payment_id"]),
            date=row["date"],
            amount_in=_decimal(row["amount_in"]),
            amount_out=_decimal(row["amount_out"]),
            method=row["method"],
            instrument_type=row["instrument_type"],
            instrument_no=row["instrument_no"],
            bank_account_id=row["bank_account_id"],
            vendor_bank_account_id=row["vendor_bank_account_id"],
            doc_id=row["doc_id"],
        )
        for row in rows
    )
