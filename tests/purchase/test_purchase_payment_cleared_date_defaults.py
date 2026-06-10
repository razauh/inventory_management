import sqlite3

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE purchases (
            purchase_id TEXT PRIMARY KEY,
            total_amount NUMERIC NOT NULL,
            paid_amount NUMERIC NOT NULL DEFAULT 0,
            advance_payment_applied NUMERIC NOT NULL DEFAULT 0,
            vendor_id INTEGER NOT NULL
        );

        CREATE TABLE purchase_detailed_totals (
            purchase_id TEXT PRIMARY KEY,
            calculated_total_amount NUMERIC
        );

        CREATE TABLE vendor_bank_accounts (
            vendor_bank_account_id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL
        );

        CREATE TABLE purchase_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id TEXT NOT NULL,
            date DATE NOT NULL,
            amount NUMERIC NOT NULL,
            method TEXT NOT NULL,
            bank_account_id INTEGER,
            vendor_bank_account_id INTEGER,
            instrument_type TEXT,
            instrument_no TEXT,
            instrument_date DATE,
            deposited_date DATE,
            cleared_date DATE,
            clearing_state TEXT NOT NULL,
            ref_no TEXT,
            notes TEXT,
            created_by INTEGER,
            temp_vendor_bank_name TEXT,
            temp_vendor_bank_number TEXT
        );

        CREATE TABLE audit_logs (
            user_id INTEGER,
            action_type TEXT,
            table_name TEXT,
            record_id INTEGER,
            details TEXT
        );

        CREATE TABLE vendor_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            amount NUMERIC,
            remaining_amount NUMERIC,
            date DATE,
            notes TEXT,
            created_by INTEGER,
            source_id TEXT,
            source_type TEXT,
            method TEXT,
            bank_account_id INTEGER,
            vendor_bank_account_id INTEGER,
            instrument_type TEXT,
            instrument_no TEXT,
            instrument_date DATE,
            deposited_date DATE,
            cleared_date DATE,
            clearing_state TEXT,
            ref_no TEXT,
            temp_vendor_bank_name TEXT,
            temp_vendor_bank_number TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, total_amount, paid_amount, advance_payment_applied, vendor_id
        ) VALUES ('PUR-001', 500, 0, 0, 10)
        """
    )
    return conn


def _record_cash_payment(repo, *, cleared_date):
    return repo.record_payment(
        "PUR-001",
        amount=100,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no="",
        instrument_date="2026-06-10",
        deposited_date=None,
        cleared_date=cleared_date,
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )


def test_cleared_purchase_payment_defaults_cleared_date_to_payment_date():
    conn = _conn()
    repo = PurchasePaymentsRepo(conn)

    payment_id = _record_cash_payment(repo, cleared_date=None)

    row = conn.execute(
        "SELECT date, cleared_date, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert dict(row) == {
        "date": "2026-06-10",
        "cleared_date": "2026-06-10",
        "clearing_state": "cleared",
    }


def test_cleared_purchase_payment_preserves_explicit_cleared_date():
    conn = _conn()
    repo = PurchasePaymentsRepo(conn)

    payment_id = _record_cash_payment(repo, cleared_date="2026-06-12")

    row = conn.execute(
        "SELECT date, cleared_date, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert dict(row) == {
        "date": "2026-06-10",
        "cleared_date": "2026-06-12",
        "clearing_state": "cleared",
    }
