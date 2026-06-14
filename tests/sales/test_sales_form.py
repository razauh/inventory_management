import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout
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
    """Test the current compact sales form layout."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()

    assert isinstance(form.layout(), QVBoxLayout), f"Main layout should be QVBoxLayout, got {type(form.layout())}"
    assert form.layout().count() >= 2
    assert form.pay_box.isVisible()

def test_bank_account_dropdown_population(qtbot, mock_repos):
    """Test that bank account dropdown is populated when Bank Transfer is selected."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    
    # Select Bank Transfer
    form.pay_method.setCurrentIndex(1)
    
    assert form.cmb_bank_account.isVisible()
    assert form.edt_instr_no.isVisible()
    
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

def test_ctrl_enter_adds_row_from_sales_product_field(qtbot, mock_repos):
    """Ctrl+Enter adds a row from the current product line."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    initial_rows = form.tbl.rowCount()
    product_edit = form.tbl.cellWidget(0, 1)
    product_edit.setFocus()

    qtbot.keyClick(product_edit, Qt.Key_Return, Qt.ControlModifier)

    assert form.tbl.rowCount() == initial_rows + 1

def test_ctrl_enter_adds_row_from_sales_numeric_cell(qtbot, mock_repos):
    """Ctrl+Enter adds a row from any editable item cell."""
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()
    initial_rows = form.tbl.rowCount()
    form.tbl.setCurrentCell(0, 5)
    form.tbl.setFocus()

    qtbot.keyClick(form.tbl, Qt.Key_Return, Qt.ControlModifier)

    assert form.tbl.rowCount() == initial_rows + 1

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
    assert font.pointSize() >= 10 or font.pixelSize() >= 12, "Total label font should be increased"

def test_sales_payload_with_product_text_editor(qtbot, mock_repos, ids):
    """Test payload generation with the text-based product editor."""
    # Seed stock and price for Widget A (prod_A)
    mock_repos["products"].conn.execute(
        "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, date) VALUES (?, 100.0, ?, 'adjustment', '2026-06-11')",
        (ids["prod_A"], ids["uom_piece"]),
    )
    mock_repos["products"].set_manual_sale_price_base(ids["prod_A"], 10.0)
    mock_repos["products"].conn.commit()

    customer_id = mock_repos["customers"].create(name="Payload User", contact_info="123", address="Street")
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()

    form.cmb_customer.setCurrentIndex(form.cmb_customer.findData(customer_id))
    product_edit = form.tbl.cellWidget(0, 1)
    product_edit.setText(f"Widget A (#{ids['prod_A']})")
    form.tbl.item(0, 0).setData(Qt.UserRole, ids["uom_piece"])
    form.tbl.item(0, 4).setText("100")
    form.tbl.cellWidget(0, 5).setValue(1.0)
    form.tbl.item(0, 6).setText("10")

    # Wait for the product debounce timer (300ms) to fire and load the product info
    qtbot.wait(400)

    p = form.get_payload()
    assert p is not None, "Payload should be generated for text product entry"
    assert p["customer_id"] == customer_id
    assert p["items"][0]["product_id"] == ids["prod_A"]


def test_sales_payload_validation_rejects_any_error(qtbot, mock_repos, ids):
    """Test that if there is one valid row and one invalid row, get_payload() returns None."""
    customer_id = mock_repos["customers"].create(name="Payload User", contact_info="123", address="Street")
    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"])
    qtbot.addWidget(form)
    form.show()

    # Select customer
    form.cmb_customer.setCurrentIndex(form.cmb_customer.findData(customer_id))

    # Add a second row
    form._add_row()
    assert form.tbl.rowCount() == 2

    # Row 1 is valid
    product_edit_1 = form.tbl.cellWidget(0, 1)
    product_edit_1.setText(f"Widget A (#{ids['prod_A']})")
    # Store parsed product ID in the hidden column (column 11)
    id_item_1 = form.tbl.item(0, 11)
    if id_item_1 is None:
        from PySide6.QtWidgets import QTableWidgetItem
        id_item_1 = QTableWidgetItem()
        form.tbl.setItem(0, 11, id_item_1)
    id_item_1.setData(Qt.UserRole, ids["prod_A"])
    form.tbl.item(0, 0).setData(Qt.UserRole, ids["uom_piece"])
    form.tbl.item(0, 4).setText("100")
    form.tbl.cellWidget(0, 5).setValue(1.0)
    form.tbl.item(0, 6).setText("10")

    # Row 2 is invalid (missing product)
    product_edit_2 = form.tbl.cellWidget(1, 1)
    product_edit_2.setText("") # Invalid/empty product

    # get_payload() should return None (not silently drop row 2 and return only row 1)
    p = form.get_payload()
    assert p is None


def test_sales_form_prefill_preserves_historical_price_and_uom(qtbot, mock_repos, ids):
    """Test that if the form is prefilled with a specific UOM and historical price, they are preserved."""
    # Seed stock and price for Widget A (prod_A)
    mock_repos["products"].conn.execute(
        "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, date) VALUES (?, 100.0, ?, 'adjustment', '2026-06-11')",
        (ids["prod_A"], ids["uom_piece"]),
    )
    mock_repos["products"].set_manual_sale_price_base(ids["prod_A"], 10.0)
    # Map Box as an alternate UOM for prod_A in the test database
    mock_repos["products"].conn.execute(
        "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 0, 10.0)",
        (ids["prod_A"], ids["uom_box"]),
    )
    mock_repos["products"].conn.commit()

    initial_data = {
        "sale_id": "SO-PREFILL-TEST",
        "customer_id": 1,
        "customer_name": "Test Customer",
        "order_discount": 0.0,
        "notes": "Prefill test",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_box"],
                "quantity": 2.0,
                "unit_price": 5000.0,
                "item_discount": 0.0,
            }
        ]
    }

    form = SaleForm(None, customers=mock_repos["customers"], products=mock_repos["products"], bank_accounts=mock_repos["bank_accounts"], initial=initial_data)
    qtbot.addWidget(form)
    form.show()

    # Wait 400 ms to make sure that if any debounced product loading were to occur, it has finished
    qtbot.wait(400)

    # Now verify the row 0 fields
    # Unit price should be 5,000.00
    price_item = form.tbl.item(0, 6)
    assert price_item is not None
    assert price_item.text().replace(",", "") == "5000.00"

    # Alternate UOM combobox should have Box selected
    alt_cb = form.tbl.cellWidget(0, 3)
    assert alt_cb is not None
    assert alt_cb.currentData() is not None
    assert alt_cb.currentData()[0] == ids["uom_box"]

    # Verify that get_payload() returns the exact custom UOM and price
    payload = form.get_payload()
    assert payload is not None
    assert payload["items"][0]["product_id"] == ids["prod_A"]
    assert payload["items"][0]["uom_id"] == ids["uom_box"]
    assert float(payload["items"][0]["unit_price"]) == 5000.0
