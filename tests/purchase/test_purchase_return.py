import pytest
from unittest.mock import MagicMock, patch
from inventory_management.modules.purchase.return_form import PurchaseReturnForm
from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.database.repositories.purchases_repo import PurchasesRepo

@pytest.fixture
def controller(conn, current_user):
    return PurchaseController(conn, current_user)

def test_return_ui_validation(qtbot, conn, ids):
    """Test UI validation for returns."""
    # We need a purchase first
    repo = PurchasesRepo(conn)
    from inventory_management.database.repositories.purchases_repo import PurchaseHeader, PurchaseItem
    
    h = PurchaseHeader(
        purchase_id="PO-RET-UI",
        vendor_id=ids["vendor_id"],
        date="2023-01-01",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Test",
        created_by=1
    )
    items = [
        PurchaseItem(None, "PO-RET-UI", ids["prod_A"], 10.0, ids["uom_piece"], 10.0, 15.0, 0.0)
    ]
    repo.create_purchase(h, items)
    pid = "PO-RET-UI"
    
    # Open return form
    # We can't easily use the controller's _return method because it requires UI interaction
    # So we instantiate the form directly
    
    # We need to fetch the item_id correctly
    items = repo.list_items(pid)
    item_id = items[0]["item_id"]
    
    # Prepare items for form (similar to controller logic)
    items_for_form = [dict(it) for it in items]
    items_for_form[0]["returnable"] = 10.0 # Mock returnable
    
    form = PurchaseReturnForm(
        None, 
        items=items_for_form,
        vendor_id=ids["vendor_id"],
        purchases_repo=repo
    )
    form.purchase_id = pid
    qtbot.addWidget(form)
    
    # Try to return more than purchased
    # Row 0, col 4 is 'Return Qty' (assuming based on typical layout, need to verify if possible)
    # But better to use the internal method or widget if accessible
    
    # The form populates a table. Let's find the return qty cell.
    # Based on return_form.py analysis:
    # Col 4 is Return Qty (editable)
    
    form.tbl.item(0, 4).setText("20") # Max is 10
    
    # Trigger validation (usually on save or change)
    # The form has _validate_return_qty
    
    # Mock warning
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        form.btn_save.click()
        assert mock_warn.called
        assert "cannot exceed" in mock_warn.call_args[0][2]

def test_return_logic_credit(controller, conn, ids):
    """Test recording a return with vendor credit."""
    # 1. Create Purchase
    repo = PurchasesRepo(conn)
    from inventory_management.database.repositories.purchases_repo import PurchaseHeader, PurchaseItem
    
    h = PurchaseHeader(
        purchase_id="PO-RET-LOGIC",
        vendor_id=ids["vendor_id"],
        date="2023-01-01",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="paid",
        paid_amount=100.0,
        advance_payment_applied=0.0,
        notes="Test",
        created_by=1
    )
    items = [
        PurchaseItem(None, "PO-RET-LOGIC", ids["prod_A"], 10.0, ids["uom_piece"], 10.0, 15.0, 0.0)
    ]
    repo.create_purchase(h, items)
    pid = "PO-RET-LOGIC"
    
    # 2. Perform Return via Controller (mocking form)
    payload = {
        "items": [
            {
                "item_id": 1, # Assuming auto-increment starts at 1
                "return_qty": 5,
                "return_amount": 50.0
            }
        ],
        "date": "2023-01-02",
        "settlement_mode": "credit",
        "notes": "Return 5 items"
    }
    
    # We need to fetch the item_id correctly
    items = repo.list_items(pid)
    item_id = items[0]["item_id"]
    payload["items"][0]["item_id"] = item_id
    
    with patch("inventory_management.modules.purchase.controller.PurchaseReturnForm") as MockForm:
        instance = MockForm.return_value
        instance.exec.return_value = True
        instance.get_data.return_value = payload
        
        # We need to select the row in the view to return
        # But controller._return() uses self.view.table.currentIndex()
        # We can mock the view and table
        mock_view = MagicMock()
        mock_view.table.currentIndex.return_value.data.return_value = pid
        # Also need selected purchase data
        mock_view.get_selected_purchase_id.return_value = pid
        controller.view = mock_view
        
        # Mock repo.get_purchase_by_id to return something valid so controller proceeds
        # (It actually calls it inside _return)
        
        controller._return()
        
    # 3. Verify Return Record
    # Check inventory_transactions
    txns = conn.execute("SELECT * FROM inventory_transactions WHERE transaction_type='purchase_return'").fetchall()
    assert len(txns) == 1
    assert txns[0]["quantity"] == 5
    
    # Check Vendor Credit
    credit = conn.execute("SELECT * FROM vendor_advances WHERE source_id=?", (pid,)).fetchone()
    # source_id might be the return ID or purchase ID depending on implementation
    # But we can check total credit
    total_credit = controller.vadv.get_balance(ids["vendor_id"])
    assert total_credit == 50.0
