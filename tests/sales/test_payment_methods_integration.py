import sqlite3
import pytest
from PySide6.QtCore import Qt
from inventory_management.database.schema import SQL
from inventory_management.database.repositories.sale_payments_repo import SalePaymentsRepo
from inventory_management.database.repositories.sales_repo import SalesRepo, SaleHeader, SaleItem
from inventory_management.modules.sales.payment_form import SalesPaymentForm

@pytest.fixture()
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Test Customer', '123')"
    ).lastrowid

    conn.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied,
            doc_type
        ) VALUES ('SO-PAY-TEST', ?, '2026-06-11', 1000.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')
        """,
        (customer_id,),
    )

    # Insert a company bank account (id=1)
    conn.execute(
        """
        INSERT INTO company_bank_accounts (company_id, label, bank_name, account_no)
        VALUES (1, 'Meezan Bank', 'Meezan', '12345')
        """
    )
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()

def test_repo_accepts_all_display_payment_methods(test_db, tmp_path):
    # We must use a file-based or shared connection repo.
    # Since SalePaymentsRepo connects to a db_path, we can write the DB to a temp file.
    db_file = tmp_path / "test_payment_methods.sqlite"
    # Copy from memory test_db to file db
    disk_conn = sqlite3.connect(db_file)
    test_db.backup(disk_conn)
    disk_conn.close()

    repo = SalePaymentsRepo(db_file)

    # Test Cash (immediate, posted/cleared, negative amount allowed for refund)
    pid_cash = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Cash",
        date="2026-06-11",
        clearing_state="cleared",
    )
    assert pid_cash > 0

    # Test Bank Transfer (requires bank account and instrument number)
    pid_bt = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Bank Transfer",
        date="2026-06-11",
        bank_account_id=1,
        instrument_no="BT-12345",
    )
    assert pid_bt > 0

    # Test Card
    pid_card = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Card",
        date="2026-06-11",
    )
    assert pid_card > 0

    # Test Cheque
    pid_ch = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Cheque",
        date="2026-06-11",
        bank_account_id=1,
        instrument_no="CH-9876",
    )
    assert pid_ch > 0

    # Test Cross Cheque
    pid_cc = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Cross Cheque",
        date="2026-06-11",
        bank_account_id=1,
        instrument_no="CC-5432",
    )
    assert pid_cc > 0

    # Test Cash Deposit
    pid_cd = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Cash Deposit",
        date="2026-06-11",
        bank_account_id=1,
        instrument_no="CD-1122",
    )
    assert pid_cd > 0

    # Test Other
    pid_oth = repo.record_payment(
        sale_id="SO-PAY-TEST",
        amount=100.0,
        method="Other",
        date="2026-06-11",
    )
    assert pid_oth > 0


def test_sales_payment_form_payload_emits_display_values(qtbot):
    def mock_banks():
        return [{"id": 1, "name": "Meezan Bank"}]

    form = SalesPaymentForm(
        parent=None,
        sale_id="SO-PAY-TEST",
        remaining=1000.0,
        list_company_bank_accounts=mock_banks,
    )
    qtbot.addWidget(form)

    for key, expected_display in form.PAYMENT_METHODS.items():
        form._payload = None
        form.amount.setText("100.0")

        index = form.method.findData(key)
        assert index >= 0, f"Method key {key} not found in combobox"
        form.method.setCurrentIndex(index)

        if key in form.METHODS_REQUIRE_COMPANY_BANK:
            # Meezan Bank is the second item (index 1), because index 0 is None/empty
            form.company_acct.setCurrentIndex(1)
        if key in form.METHODS_REQUIRE_INSTRUMENT:
            form.instr_no.setText("INSTR-12345")

        form.accept()
        payload = form.payload()
        assert payload is not None, f"Payload was not generated for method key {key}"
        assert payload["method"] == expected_display, f"Expected {expected_display} but got {payload['method']}"


def test_create_sale_atomicity_with_payment(test_db):
    sales_repo = SalesRepo(test_db)

    # First verify we can create sale with a valid payment
    h = SaleHeader(
        sale_id="SO-ATOM-VALID",
        customer_id=1,
        date="2026-06-11",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Atomicity test valid",
        created_by=1
    )
    items = [
        SaleItem(
            item_id=None,
            sale_id="SO-ATOM-VALID",
            product_id=1, # Widget A from seed
            quantity=1.0,
            uom_id=1, # Piece
            unit_price=100.0,
            item_discount=0.0
        )
    ]
    payment_info = {
        "sale_id": "SO-ATOM-VALID",
        "amount": 100.0,
        "method": "Cash",
        "date": "2026-06-11",
        "clearing_state": "cleared"
    }

    # Should succeed
    sales_repo.create_sale(h, items, payment_info)

    # Verify both sale and payment exist
    sale_row = test_db.execute("SELECT * FROM sales WHERE sale_id='SO-ATOM-VALID'").fetchone()
    assert sale_row is not None
    assert sale_row["payment_status"] == "paid"
    assert float(sale_row["paid_amount"]) == 100.0

    payment_row = test_db.execute("SELECT * FROM sale_payments WHERE sale_id='SO-ATOM-VALID'").fetchone()
    assert payment_row is not None
    assert float(payment_row["amount"]) == 100.0

    # Now verify failure rollbacks BOTH sale and payment
    h_invalid = SaleHeader(
        sale_id="SO-ATOM-INVALID",
        customer_id=1,
        date="2026-06-11",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Atomicity test invalid",
        created_by=1
    )
    items_invalid = [
        SaleItem(
            item_id=None,
            sale_id="SO-ATOM-INVALID",
            product_id=1,
            quantity=1.0,
            uom_id=1,
            unit_price=100.0,
            item_discount=0.0
        )
    ]
    payment_info_invalid = {
        "sale_id": "SO-ATOM-INVALID",
        "amount": 100.0,
        "method": "INVALID_METHOD", # This will trigger ValueError in _normalize_and_validate
        "date": "2026-06-11",
        "clearing_state": "cleared"
    }

    # Should raise ValueError
    with pytest.raises(ValueError, match="Unsupported payment method"):
        sales_repo.create_sale(h_invalid, items_invalid, payment_info_invalid)

    # Verify NEITHER the sale nor the payment exist
    sale_row_invalid = test_db.execute("SELECT * FROM sales WHERE sale_id='SO-ATOM-INVALID'").fetchone()
    assert sale_row_invalid is None

    payment_row_invalid = test_db.execute("SELECT * FROM sale_payments WHERE sale_id='SO-ATOM-INVALID'").fetchone()
    assert payment_row_invalid is None


def test_update_sale_settlement_guard(test_db):
    sales_repo = SalesRepo(test_db)

    # 1. Create a sale with total_amount = 100
    h = SaleHeader(
        sale_id="SO-GUARD-TEST",
        customer_id=1,
        date="2026-06-11",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Guard test",
        created_by=1
    )
    items = [
        SaleItem(
            item_id=None,
            sale_id="SO-GUARD-TEST",
            product_id=1,
            quantity=1.0,
            uom_id=1,
            unit_price=100.0,
            item_discount=0.0
        )
    ]
    # We record an initial cleared payment of 80.0
    payment_info = {
        "sale_id": "SO-GUARD-TEST",
        "amount": 80.0,
        "method": "Cash",
        "date": "2026-06-11",
        "clearing_state": "cleared"
    }
    sales_repo.create_sale(h, items, payment_info)

    # 2. Try to update the sale with a total_amount of 50.0 (which is less than the settled 80.0)
    h_update = SaleHeader(
        sale_id="SO-GUARD-TEST",
        customer_id=1,
        date="2026-06-11",
        total_amount=50.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=80.0,
        advance_payment_applied=0.0,
        notes="Guard test updated",
        created_by=1
    )
    items_update = [
        SaleItem(
            item_id=None,
            sale_id="SO-GUARD-TEST",
            product_id=1,
            quantity=1.0,
            uom_id=1,
            unit_price=50.0,
            item_discount=0.0
        )
    ]

    # Should raise ValueError because 50.0 < 80.0 settled
    with pytest.raises(ValueError, match="Cannot reduce sale total below settled value"):
        sales_repo.update_sale(h_update, items_update)

    # 3. Verify that updating to 80.0 or more succeeds
    h_update_ok = SaleHeader(
        sale_id="SO-GUARD-TEST",
        customer_id=1,
        date="2026-06-11",
        total_amount=85.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=80.0,
        advance_payment_applied=0.0,
        notes="Guard test updated ok",
        created_by=1
    )
    items_update_ok = [
        SaleItem(
            item_id=None,
            sale_id="SO-GUARD-TEST",
            product_id=1,
            quantity=1.0,
            uom_id=1,
            unit_price=85.0,
            item_discount=0.0
        )
    ]
    sales_repo.update_sale(h_update_ok, items_update_ok)

    # Verify update succeeded
    row = test_db.execute("SELECT total_amount FROM sales WHERE sale_id='SO-GUARD-TEST'").fetchone()
    assert float(row["total_amount"]) == 85.0


def test_convert_quotation_to_sale_safety(test_db):
    sales_repo = SalesRepo(test_db)

    # 1. Create a draft quotation
    qh = SaleHeader(
        sale_id="Q-TEST-1",
        customer_id=1,
        date="2026-06-11",
        total_amount=120.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Quotation test",
        created_by=1
    )
    items = [
        SaleItem(
            item_id=None,
            sale_id="Q-TEST-1",
            product_id=1,
            quantity=1.0,
            uom_id=1,
            unit_price=120.0,
            item_discount=0.0
        )
    ]
    sales_repo.create_quotation(qh, items, quotation_status="draft")

    # 2. First conversion should succeed
    sales_repo.convert_quotation_to_sale(
        qo_id="Q-TEST-1",
        new_so_id="SO-CONV-1",
        date="2026-06-11",
        created_by=1
    )

    # Verify quotation marked as accepted/converted
    q_row = test_db.execute("SELECT quotation_status FROM sales WHERE sale_id='Q-TEST-1'").fetchone()
    assert q_row["quotation_status"] == "accepted"

    # Verify sale is created
    so_row = test_db.execute("SELECT * FROM sales WHERE sale_id='SO-CONV-1'").fetchone()
    assert so_row is not None
    assert so_row["source_type"] == "quotation"
    assert so_row["source_id"] == "Q-TEST-1"

    # 3. Repeated conversion of accepted quotation should fail
    with pytest.raises(ValueError, match="cannot be converted"):
        sales_repo.convert_quotation_to_sale(
            qo_id="Q-TEST-1",
            new_so_id="SO-CONV-2",
            date="2026-06-11",
            created_by=1
        )

    # 4. Create a cancelled quotation and verify conversion fails
    qh_cancelled = SaleHeader(
        sale_id="Q-TEST-CANCELLED",
        customer_id=1,
        date="2026-06-11",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Cancelled quotation",
        created_by=1
    )
    sales_repo.create_quotation(qh_cancelled, items, quotation_status="cancelled")
    with pytest.raises(ValueError, match="cannot be converted"):
        sales_repo.convert_quotation_to_sale(
            qo_id="Q-TEST-CANCELLED",
            new_so_id="SO-CONV-3",
            date="2026-06-11",
            created_by=1
        )

    # 5. Verify database unique constraint prevents duplicate conversion link
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            """
            INSERT INTO sales (
                sale_id, customer_id, date, total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied,
                source_type, source_id, doc_type
            ) VALUES ('SO-CONV-DUP', 1, '2026-06-11', 100.0, 0.0, 'unpaid', 0.0, 0.0, 'quotation', 'Q-TEST-1', 'sale')
            """
        )
