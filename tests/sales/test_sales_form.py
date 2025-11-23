import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QWidget, QHBoxLayout, QComboBox
from inventory_management.modules.sales.form import SaleForm
from inventory_management.database.repositories.customers_repo import CustomersRepo
from inventory_management.database.repositories.products_repo import ProductsRepo

# Mock BankAccountsRepo since it might not exist yet or we want to control data
class MockBankAccountsRepo:
    def list_company_bank_accounts(self):
        return [
            {"bank_account_id": 1, "bank_name": "Test Bank", "account_title": "Main", "account_no": "123"},
            {"bank_account_id": 2, "bank_name": "Other Bank", "account_title": "Reserve", "account_no": "456"},
        ]

@pytest.fixture
def mock_repos(conn):
    return {
        "customers": CustomersRepo(conn),
        "products": ProductsRepo(conn),
        "bank_accounts": MockBankAccountsRepo()
    }

def test_sales_form_window_controls(qtbot, mock_repos):
    """Test that the window has minimize and maximize buttons."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    
    flags = form.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint, "Minimize button missing"
    assert flags & Qt.WindowMaximizeButtonHint, "Maximize button missing"
    assert flags & Qt.WindowCloseButtonHint, "Close button missing"

def test_sales_form_layout_structure(qtbot, mock_repos):
    """Test that the layout is restructured with payment section on the right."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Check main layout is horizontal
    assert isinstance(form.layout(), QHBoxLayout), f"Main layout should be QHBoxLayout, got {type(form.layout())}"
    
    # Check for left and right widgets (this assumes implementation detail, but necessary for structure check)
    # We expect 2 items in the main layout: Left Content and Right Sidebar
    assert form.layout().count() >= 2
    
    # Verify payment box is in the right sidebar (or at least not in the main vertical flow)
    # This is tricky to test strictly without inspecting the exact widget hierarchy, 
    # but we can check if pay_box is visible and where it is parented.
    assert form.pay_box.isVisible()
    
    # Check width ratio (approximate)
    # In a real UI test we might check geometry, but here we just ensure the structure exists.

def test_bank_account_dropdown_population(qtbot, mock_repos):
    """Test that bank account dropdown is populated when Bank Transfer is selected."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Select Bank Transfer
    form.pay_method.setCurrentIndex(1)
    
    # Check visibility
    assert form.bank_box.isVisible()
    
    # Check items in dropdown
    assert form.cmb_bank_account.count() > 0
    assert "Test Bank" in form.cmb_bank_account.itemText(0)

def test_column_widths(qtbot, mock_repos):
    """Test column width adjustments."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Check Product column (index 1) is wider than others
    prod_width = form.tbl.columnWidth(1)
    qty_width = form.tbl.columnWidth(5)
    
    assert prod_width > qty_width * 1.5, "Product column should be significantly wider"
    assert form.tbl.columnWidth(0) <= 50, "Index column should be narrow"

def test_input_field_widths(qtbot, mock_repos):
    """Test input field maximum widths."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Check max width of customer combo, etc.
    assert form.cmb_customer.maximumWidth() < 300, "Customer input too wide"
    assert form.edt_contact.maximumWidth() < 300
    assert form.date.maximumWidth() < 300

def test_font_sizes(qtbot, mock_repos):
    """Test font sizes for totals."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Check font size of total label
    font = form.lab_total.font()
    assert font.pointSize() > 10 or font.pixelSize() > 12, "Total label font should be increased"

def test_manual_customer_entry(qtbot, mock_repos):
    """Test that manually typing a customer ID works."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Manually type a customer ID that exists in the mock repo
    # Mock repo has customers? We need to ensure mock_repos['customers'] has data.
    # The CustomersRepo mock isn't explicitly defined in the test file, it uses the real one with a connection.
    # We should create a customer first.
    c = mock_repos["customers"].create(name="Manual User", contact_info="123", address="Street")
    
    # Verify customer exists in repo
    created_c = mock_repos["customers"].get(c)
    assert created_c is not None, "Customer not found in repo immediately after create"
    
    # Type the ID
    form.cmb_customer.lineEdit().setText(str(c))
    assert form.cmb_customer.currentText() == str(c), f"ComboBox text mismatch: expected {c}, got {form.cmb_customer.currentText()}"
    
    # Add an item to make payload valid
    form._add_row()
    form.tbl.cellWidget(0, 1).setCurrentIndex(1) # Select product
    form.tbl.item(0, 4).setText("100") # Available
    form.tbl.item(0, 5).setText("1") # Qty
    form.tbl.item(0, 6).setText("10") # Price
    
    # Try to get payload
    p = form.get_payload()
    assert p is not None, "Payload should be generated for manual ID entry"
    assert p["customer_id"] == c, f"Customer ID mismatch: expected {c}, got {p['customer_id']}"
