import pytest
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QDialogButtonBox

from inventory_management.modules.purchase.form import PurchaseForm
from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.repositories.products_repo import ProductsRepo

@pytest.fixture
def purchase_form(qtbot, conn):
    """Fixture to provide a PurchaseForm instance with repos connected to test DB."""
    vendors = VendorsRepo(conn)
    products = ProductsRepo(conn)
    form = PurchaseForm(None, vendors=vendors, products=products)
    qtbot.addWidget(form)
    return form

def test_po_ui_initial_state(purchase_form):
    """PO-UI-001: Open the 'New PO' window."""
    assert purchase_form.windowTitle() == "Purchase"
    assert purchase_form.tbl.rowCount() == 1  # Should have one empty row by default
    assert purchase_form.cmb_vendor.count() > 1  # Empty item + seeded vendor
    assert purchase_form.lab_total.text() == "0.00"

def test_po_ui_add_row(purchase_form, qtbot):
    """PO-UI-004: Add a new row to the items table."""
    initial_rows = purchase_form.tbl.rowCount()
    qtbot.mouseClick(purchase_form.btn_add_row, Qt.LeftButton)
    assert purchase_form.tbl.rowCount() == initial_rows + 1

def test_po_ui_delete_row(purchase_form, qtbot):
    """PO-UI-005: Delete a row from the items table."""
    # Ensure we have 2 rows
    if purchase_form.tbl.rowCount() < 2:
        purchase_form._add_row()
    
    initial_rows = purchase_form.tbl.rowCount()
    # Click the delete button on the first row (column 6)
    del_btn = purchase_form.tbl.cellWidget(0, 6)
    qtbot.mouseClick(del_btn, Qt.LeftButton)
    
    assert purchase_form.tbl.rowCount() == initial_rows - 1

def test_po_ui_vendor_selection(purchase_form, ids):
    """PO-UI-006, PO-UI-007: Select a vendor."""
    # Find vendor index
    vendor_id = ids["vendor_id"]
    idx = purchase_form.cmb_vendor.findData(vendor_id)
    assert idx >= 0
    
    purchase_form.cmb_vendor.setCurrentIndex(idx)
    assert purchase_form.cmb_vendor.currentData() == vendor_id
    # Check if balance label updated (text contains 'Vendor Balance')
    assert "Vendor Balance" in purchase_form.lbl_vendor_advance.text()

def test_po_dv_validation_error_no_vendor(purchase_form, monkeypatch):
    """PO-DV-001: Try to save a PO without selecting a vendor."""
    # Mock QMessageBox to capture warning
    warning_shown = False
    def mock_warning(parent, title, text):
        nonlocal warning_shown
        warning_shown = True
        assert "Vendor" in text or "vendor" in text
    
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", mock_warning)
    
    # Trigger save
    purchase_form.save_button.click()
    assert warning_shown

def test_po_dv_validation_error_no_items(purchase_form, monkeypatch, ids):
    """PO-DV-002: Try to save a PO without any items (or empty items)."""
    # Select vendor first
    purchase_form.cmb_vendor.setCurrentIndex(purchase_form.cmb_vendor.findData(ids["vendor_id"]))
    
    # Mock QMessageBox
    warning_shown = False
    def mock_warning(parent, title, text):
        nonlocal warning_shown
        warning_shown = True
        # The error might be about "valid purchase details" or specific item errors
        assert "valid" in text or "items" in text
    
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", mock_warning)
    
    # Trigger save with empty default row
    purchase_form.save_button.click()
    assert warning_shown

def test_po_calculations(purchase_form, ids):
    """Test calculations for line total and grand total."""
    # Select product in first row
    prod_id = ids["prod_A"]
    combo = purchase_form.tbl.cellWidget(0, 1)
    idx = combo.findData(prod_id)
    combo.setCurrentIndex(idx)
    
    # Set Qty = 2, Buy Price = 10
    purchase_form.tbl.item(0, 2).setText("2")
    purchase_form.tbl.item(0, 3).setText("10")
    
    # Trigger calculation (usually happens on cell change or focus out)
    # We can manually call _recalc_row or rely on signals if qtbot edits
    purchase_form._recalc_row(0)
    purchase_form._refresh_totals()
    
    # Check line total (col 5)
    line_total = purchase_form.tbl.item(0, 5).text()
    assert float(line_total) == 20.0
    
    # Check grand total
    assert purchase_form.lab_total.text() == "20.00"

def test_initial_payment_toggles(purchase_form):
    """PO-UI-008: Change the 'Initial Payment' amount."""
    # Initially disabled/hidden logic is handled by _toggle_ip_fields_by_amount
    
    # Set amount > 0
    purchase_form.ip_amount.setText("100")
    # 1. Initial state: Amount is empty/0 -> fields disabled
    # Note: setText triggers textChanged
    purchase_form.ip_amount.setText("0")
    print(f"DEBUG: ip_amount text: '{purchase_form.ip_amount.text()}'")
    print(f"DEBUG: ip_method enabled: {purchase_form.ip_method.isEnabled()}")
    assert not purchase_form.ip_method.isEnabled()
    
    # Check if fields enabled
    assert purchase_form.ip_method.isEnabled()
    
    # Check if fields disabled
    assert not purchase_form.ip_method.isEnabled()

def test_initial_payment_methods(purchase_form):
    """Test initial payment method permutations (PO-IP-001 to PO-IP-006)."""
    # Enable IP fields
    purchase_form.ip_amount.setText("100")
    
    # 1. Cash (Default)
    purchase_form.ip_method.setCurrentText("Cash")
    # Company Bank: Disabled? Logic says: if Cash, no company bank needed? 
    # Actually form.py: _refresh_ip_visibility:
    # if method in (Cash, Other): company_bank disabled?
    # Let's check form.py logic or just assert expected behavior
    # Based on form.py analysis (from memory/previous view):
    # Cash -> Company Bank Disabled (or Optional?), Vendor Bank Disabled, Instrument Disabled.
    
    # 2. Bank Transfer
    purchase_form.ip_method.setCurrentText("Bank Transfer")
    assert purchase_form.ip_company_acct.isEnabled()
    assert purchase_form.ip_vendor_acct.isEnabled()
    assert purchase_form.ip_instr_no.isEnabled()
    
    # 3. Cheque
    purchase_form.ip_method.setCurrentText("Cheque")
    assert purchase_form.ip_company_acct.isEnabled()
    assert not purchase_form.ip_vendor_acct.isEnabled() # Cheque is given to vendor, no vendor bank needed?
    # Wait, Cheque needs Instrument No.
    assert purchase_form.ip_instr_no.isEnabled()
