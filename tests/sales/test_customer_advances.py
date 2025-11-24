
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from inventory_management.modules.sales.form import SaleForm
from inventory_management.database.repositories.customers_repo import CustomersRepo
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.repositories.sales_repo import SalesRepo
from inventory_management.database.repositories.customer_advances_repo import CustomerAdvancesRepo

def test_customer_advances_display(qtbot, conn):
    """
    Verify that customer advances are displayed in the payment history panel.
    """
    # Setup repos
    customers_repo = CustomersRepo(conn)
    products_repo = ProductsRepo(conn)
    sales_repo = SalesRepo(conn)
    # Get DB path from connection or use the known test DB path
    # Since we are using the shared test DB, we can use the path from conftest (if we could import it)
    # or just derive it. But let's try to get it from the connection if possible, 
    # or just use the hardcoded test path since we know it.
    from pathlib import Path
    db_path = Path("data/test_myshop.db").resolve()
    
    advances_repo = CustomerAdvancesRepo(db_path)
    
    # Create a test customer
    cid = customers_repo.create(
        name="Test Customer Advances",
        contact_info="123",
        address="Test Address"
    )
    
    # Add an advance payment (deposit)
    advances_repo.grant_credit(
        customer_id=cid,
        amount=500.0,
        date="2024-01-01",
        notes="Test Deposit"
    )
    
    # Initialize form
    # We need to pass the db_path string/Path, not the connection object, because SaleForm re-opens it.
    # Since we are using the 'conn' fixture which is an in-memory or temp file DB, 
    # we need to make sure SaleForm can access it. 
    # The 'conn' fixture in conftest.py usually creates a temporary file-based DB for tests.
    # Let's check where the DB is.
    
    # For this test, we might need to rely on the fact that 'conn' is pointing to a file 
    # that can be opened by path.
    # If 'conn' is :memory:, this won't work with SaleForm's design of opening a new connection.
    # However, looking at previous tests, it seems we can pass a path.
    
    # Let's assume for now we can get the path from the connection or just use a mock path 
    # if the form allows injection of repos (which it does for some, but it instantiates SalePaymentsRepo internally).
    
    # Actually, SaleForm instantiates SalePaymentsRepo and CustomerAdvancesRepo internally using self.db_path.
    # So we need a valid db_path.
    # In the previous debug test, I used the real DB path. Here I should use the test DB path.
    # I'll check if I can get the path from the cursor or connection.
    
    # Hack: For testing purposes, we can monkeypatch the repo instantiation in SaleForm 
    # or just ensure the test DB is on disk.
    # Let's try to find the DB path from the connection.
    
    cursor = conn.cursor()
    cursor.execute("PRAGMA database_list")
    db_list = cursor.fetchall()
    db_path = db_list[0][2] # main database file path
    
    if not db_path:
        pytest.skip("Test requires a file-based database")

    form = SaleForm(
        None, 
        customers=customers_repo, 
        products=products_repo, 
        sales_repo=sales_repo, 
        db_path=db_path
    )
    qtbot.addWidget(form)
    
    # Select the customer (this triggers _update_payment_history_for_customer)
    # But we can also call it directly for isolation
    form._update_payment_history_for_customer(cid)
    
    # Verify "Advances" label
    # We expect a new label or updated UI. 
    # Since we haven't implemented it yet, this test will fail (TDD).
    # But first let's check if we can access the label. 
    # The plan says "Add 'Advances' label".
    
    # Let's assert that the advances are in the table
    row_count = form.payments_table.rowCount()
    found_advance = False
    for i in range(row_count):
        # Check method/type column (index 2) or maybe we'll put "Advance" there
        method_item = form.payments_table.item(i, 2)
        if method_item.text() == "Deposit": # or whatever we decide to call it
            found_advance = True
            # Check color
            assert method_item.foreground().color() == QColor("green")
            
            # Check amount
            amount_item = form.payments_table.item(i, 1)
            assert "500.00" in amount_item.text()
            break
            
    assert found_advance, "Advance payment should be listed in the table"
    
    # Verify summary label if we can find it (we'll need to expose it or find it by text)
    # For now, let's assume we'll add a self.payment_advances_label
    if hasattr(form, 'payment_advances_label'):
        assert "500.00" in form.payment_advances_label.text()

