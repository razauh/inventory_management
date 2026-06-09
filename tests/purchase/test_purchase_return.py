import pytest
from PySide6.QtWidgets import QDialogButtonBox
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
    # Use the form's column constant so the test follows the current table layout.
    # But better to use the internal method or widget if accessible
    
    # The form populates a table. Let's find the return qty cell.
    form.tbl.item(0, form.COL_QTY_RETURN).setText("20") # Max is 10
    
    # Trigger validation (usually on save or change)
    # The form has _validate_return_qty
    
    # Mock warning
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        form.buttons.button(QDialogButtonBox.Ok).click()
        assert mock_warn.called
        assert "exceeds max returnable" in mock_warn.call_args[0][2]

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
        "date": "2023-01-02",
        "lines": [
            {
                "item_id": 1,
                "qty_return": 5,
            }
        ],
        "settlement": {"mode": "credit_note"},
        "notes": "Return 5 items"
    }
    
    # We need to fetch the item_id correctly
    items = repo.list_items(pid)
    item_id = items[0]["item_id"]
    payload["lines"][0]["item_id"] = item_id
    
    with patch("inventory_management.modules.purchase.controller.PurchaseReturnForm") as MockForm:
        instance = MockForm.return_value
        instance.set_purchase_id.return_value = None
        instance.exec.return_value = True
        instance.payload.return_value = payload
        
        controller._selected_row_dict = MagicMock(return_value={"purchase_id": pid})
        controller._reload = MagicMock()
        
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
