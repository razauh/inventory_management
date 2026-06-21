import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService, VendorAdvancePayload


def _advance_event_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.execute("INSERT INTO company_info (company_id, company_name) VALUES (1, 'Company')")
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    company_bank_id = conn.execute(
        "INSERT INTO company_bank_accounts (label, is_active) VALUES ('Bank', 1)"
    ).lastrowid
    vendor_bank_id = conn.execute(
        "INSERT INTO vendor_bank_accounts (vendor_id, label, is_active) VALUES (?, 'Vendor Bank', 1)",
        (vendor_id,),
    ).lastrowid
    return conn, int(vendor_id), int(company_bank_id), int(vendor_bank_id)


def test_record_vendor_advance_event_preserves_signed_credit_rows():
    conn, vendor_id, _company_bank_id, _vendor_bank_id = _advance_event_db()

    result = AccountingService(conn).record_vendor_advance_event(
        VendorAdvancePayload(
            vendor_id=vendor_id,
            amount=Decimal("75"),
            date="2026-06-10",
            notes="Manual credit",
            source_type="return_credit",
            source_id="PO-1",
        )
    )

    row = conn.execute(
        "SELECT vendor_id, amount, source_type, source_id, notes FROM vendor_advances WHERE tx_id = ?",
        (result.tx_id,),
    ).fetchone()
    assert int(row["vendor_id"]) == vendor_id
    assert float(row["amount"]) == pytest.approx(75.0)
    assert row["source_type"] == "return_credit"
    assert row["source_id"] == "PO-1"
    assert row["notes"] == "Manual credit"
    assert AccountingService(conn).get_vendor_advance_balance(vendor_id).balance == Decimal("75.0")
    conn.close()


def test_record_vendor_advance_event_preserves_payment_metadata():
    conn, vendor_id, company_bank_id, vendor_bank_id = _advance_event_db()

    result = AccountingService(conn).record_vendor_advance_event(
        VendorAdvancePayload(
            vendor_id=vendor_id,
            amount=Decimal("125"),
            date="2026-06-10",
            method="Bank Transfer",
            bank_account_id=company_bank_id,
            vendor_bank_account_id=vendor_bank_id,
            instrument_type="online",
            instrument_no="TRX-1",
            instrument_date="2026-06-10",
            cleared_date="2026-06-10",
            clearing_state="cleared",
            ref_no="REF-1",
        )
    )

    row = conn.execute(
        """
        SELECT method, bank_account_id, vendor_bank_account_id, instrument_type,
               instrument_no, instrument_date, cleared_date, clearing_state, ref_no
        FROM vendor_advances
        WHERE tx_id = ?
        """,
        (result.tx_id,),
    ).fetchone()
    assert dict(row) == {
        "method": "Bank Transfer",
        "bank_account_id": company_bank_id,
        "vendor_bank_account_id": vendor_bank_id,
        "instrument_type": "online",
        "instrument_no": "TRX-1",
        "instrument_date": "2026-06-10",
        "cleared_date": "2026-06-10",
        "clearing_state": "cleared",
        "ref_no": "REF-1",
    }
    conn.close()


def test_vendor_advances_repo_grant_credit_delegates_to_accounting_service():
    conn, vendor_id, _company_bank_id, _vendor_bank_id = _advance_event_db()

    tx_id = VendorAdvancesRepo(conn).grant_credit(
        vendor_id=vendor_id,
        amount=20,
        date="2026-06-10",
        notes="Repo wrapper",
        created_by=None,
    )

    assert conn.execute(
        "SELECT amount FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()[0] == pytest.approx(20.0)
    conn.close()
