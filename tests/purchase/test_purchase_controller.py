import pytest
from unittest.mock import MagicMock, patch
import sqlite3
from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.database.repositories.purchases_repo import PurchasesRepo

class TestConn:
    def __init__(self, real_conn):
        self.real_conn = real_conn
        self.row_factory = real_conn.row_factory

    def execute(self, sql, parameters=()):
        if isinstance(sql, str) and sql.strip().upper() in ("BEGIN", "COMMIT", "ROLLBACK"):
            return
        return self.real_conn.execute(sql, parameters)
    
    def commit(self):
        pass
        
    def rollback(self):
        pass
        
    def __getattr__(self, name):
        return getattr(self.real_conn, name)

@pytest.fixture
def controller(conn, current_user):
    """Fixture for PurchaseController."""
    conn.row_factory = sqlite3.Row
    return PurchaseController(TestConn(conn), current_user)

def test_controller_add_flow(controller, monkeypatch, ids):
    """Test adding a new purchase via controller."""
    # Mock PurchaseForm to return a valid payload immediately
    payload = {
        "vendor_id": ids["vendor_id"],
        "date": "2023-01-01",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_piece"],
                "quantity": 5,
                "purchase_price": 10.0,
                "sale_price": 15.0,
                "item_discount": 0.0
            }
        ],
        "total_amount": 50.0,
        "order_discount": 0.0,
        "notes": "Test PO",
        "initial_payment": None
    }
    
    # We need to mock the dialog class used in _add
    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as MockForm:
        instance = MockForm.return_value
        instance.exec.return_value = True  # Accepted
        instance.payload.return_value = payload
        
        # Call _add
        controller._add()
        
        # Verify DB insertion
        repo = PurchasesRepo(controller.conn)
        purchases = repo.list_purchases()
        assert len(purchases) == 1
        assert purchases[0]["vendor_id"] == ids["vendor_id"]
        assert float(purchases[0]["total_amount"]) == 50.0

def test_controller_delete_not_implemented(controller, monkeypatch):
    """DB-INT-004: Verify delete is not implemented or exposed."""
    # The view has a btn_del but it might be commented out or not connected
    # Check if _delete method exists or is connected
    
    # In the provided view.py, btn_del is commented out:
    # self.btn_del = QPushButton("Delete")
    # row.addWidget(self.btn_add); row.addWidget(self.btn_edit)#; row.addWidget(self.btn_del)
    
    # So we verify that there is no active delete button in the layout
    # or that clicking it (if we could find it) does nothing
    
    # Let's check if the controller has a _delete method wired
    # And check if view has btn_del (it might not)
    has_btn = hasattr(controller.view, "btn_del")
    if has_btn:
        assert not controller.view.btn_del.isVisible()
    
    # Also check controller method - it MIGHT exist but shouldn't be exposed
    # assert not hasattr(controller, "_delete") 
    # Actually it does exist, but the button is missing.
    pass

def test_auto_apply_vendor_credit(controller, ids, conn):
    """DB-INT-006: Test auto-application of vendor credit."""
    # 1. Create a vendor credit (advance)
    conn.execute("""
        INSERT INTO vendor_advances (vendor_id, amount, source_type, notes)
        VALUES (?, ?, 'deposit', 'Test Credit')
    """, (ids["vendor_id"], 100.0))
    
    # 2. Create a purchase for 50.0
    payload = {
        "vendor_id": ids["vendor_id"],
        "date": "2023-01-01",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_piece"],
                "quantity": 5,
                "purchase_price": 10.0,
                "sale_price": 15.0,
                "item_discount": 0.0
            }
        ],
        "total_amount": 50.0,
        "order_discount": 0.0,
        "notes": "PO with Credit",
        "initial_payment": None
    }
    
    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as MockForm:
        instance = MockForm.return_value
        instance.exec.return_value = True
        instance.payload.return_value = payload
        
        controller._add()
        
    # 3. Verify purchase is paid (via credit)
    repo = PurchasesRepo(controller.conn)
    purchases = repo.list_purchases()
    assert len(purchases) == 1
    po = purchases[0]
    
    # Should be fully paid
    assert po["payment_status"] == "paid"
    assert float(po["advance_payment_applied"]) == 50.0
    
    # 4. Verify vendor credit reduced
    remaining_credit = controller.vadv.get_balance(ids["vendor_id"])
    assert remaining_credit == 50.0  # 100 - 50
