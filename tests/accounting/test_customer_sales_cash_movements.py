"""Characterization tests for customer cash movements and payment metadata."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, CustomerPaymentMetadata


def test_customer_cash_movements_match_bank_ledger_view():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sale_payments (payment_id INTEGER PRIMARY KEY,
            sale_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, cleared_date TEXT, notes TEXT);
        CREATE TABLE customer_advances (tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL, source_type TEXT, source_id TEXT,
            method TEXT, bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER);
        INSERT INTO sale_payments VALUES (1, 'S1', '2026-06-21', 100, 'Cash', 'cleared', '2026-06-21', NULL);
        INSERT INTO sale_payments VALUES (2, 'S1', '2026-06-22', -30, 'Cash', 'cleared', '2026-06-22', 'Refund');
    """)
    svc = AccountingService(conn)
    movements = svc.get_customer_cash_movements()
    assert len(movements) == 2
    assert movements[0].type == "Receipt"
    assert float(movements[0].amount) == 100
    assert movements[1].type == "Refund"
    assert float(movements[1].amount) == 30


def test_customer_payment_metadata_validation_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE company_bank_accounts (account_id INTEGER PRIMARY KEY, is_active INTEGER DEFAULT 1)")
    conn.execute("INSERT INTO company_bank_accounts VALUES (1, 1)")

    svc = AccountingService(conn)
    # Valid cash
    svc.validate_customer_payment_metadata(
        CustomerPaymentMetadata(customer_id=1, method="Cash")
    )
    # Valid bank transfer with details
    svc.validate_customer_payment_metadata(
        CustomerPaymentMetadata(customer_id=1, method="Bank Transfer",
            bank_account_id=1, instrument_type="online",
            instrument_no="TXN001", require_method_details=True)
    )
    # Invalid method
    try:
        svc.validate_customer_payment_metadata(
            CustomerPaymentMetadata(customer_id=1, method="Bitcoin")
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_bank_ledger_ordering_matches_intended_date_basis():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sale_payments (payment_id INTEGER PRIMARY KEY,
            sale_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, cleared_date TEXT, instrument_type TEXT,
            instrument_no TEXT, bank_account_id INTEGER);
        CREATE TABLE purchase_payments (payment_id INTEGER PRIMARY KEY,
            purchase_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, cleared_date TEXT, instrument_type TEXT,
            instrument_no TEXT, bank_account_id INTEGER, vendor_bank_account_id INTEGER);
        CREATE TABLE purchase_refunds (refund_id INTEGER PRIMARY KEY,
            purchase_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, cleared_date TEXT, instrument_type TEXT,
            instrument_no TEXT, bank_account_id INTEGER, vendor_bank_account_id INTEGER);
        CREATE TABLE vendor_advances (tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER, tx_date TEXT, amount REAL, source_type TEXT, source_id TEXT,
            method TEXT, bank_account_id INTEGER, vendor_bank_account_id INTEGER, instrument_type TEXT,
            instrument_no TEXT, cleared_date TEXT, clearing_state TEXT);

        -- Entry 1: Clears late
        INSERT INTO sale_payments VALUES (1, 'S1', '2026-06-10', 100, 'Cash', 'cleared', '2026-06-22', 'online', 'TXN-1', 1);
        -- Entry 2: Clears early
        INSERT INTO sale_payments VALUES (2, 'S2', '2026-06-20', 200, 'Cash', 'cleared', '2026-06-21', 'online', 'TXN-2', 1);
    """)
    svc = AccountingService(conn)
    rows = svc.get_bank_ledger("2026-06-01", "2026-06-30", 1)

    # Should be ordered by cleared_date (date), so Entry 2 (cleared 21st) comes before Entry 1 (cleared 22nd)
    assert len(rows) == 2
    assert rows[0].payment_id == 2
    assert rows[0].date == "2026-06-21"
    assert rows[1].payment_id == 1
    assert rows[1].date == "2026-06-22"
    conn.close()

