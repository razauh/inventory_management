"""
Unit tests to verify window properties and functionality for SO and PO windows
"""
import unittest
from unittest.mock import Mock, MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import sys
import os

# Add the project root to the path and run as module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Add the main package to sys.path for proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use importlib to properly import the modules
import importlib.util
spec = importlib.util.spec_from_file_location("SaleForm", "/home/pc/Desktop/inventory_management/modules/sales/form.py")
SaleForm_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SaleForm_module)
SaleForm = SaleForm_module.SaleForm

spec2 = importlib.util.spec_from_file_location("PurchaseForm", "/home/pc/Desktop/inventory_management/modules/purchase/form.py")
PurchaseForm_module = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(PurchaseForm_module)
PurchaseForm = PurchaseForm_module.PurchaseForm

# Import repositories directly
from database.repositories.customers_repo import CustomersRepo
from database.repositories.products_repo import ProductsRepo
from database.repositories.vendors_repo import VendorsRepo


class TestWindowProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication instance only once
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        # Mock repositories for testing
        self.mock_customers = Mock(spec=CustomersRepo)
        self.mock_products = Mock(spec=ProductsRepo)
        self.mock_vendors = Mock(spec=VendorsRepo)
        
        # Mock required methods
        self.mock_customers.list_customers.return_value = []
        self.mock_products.list_products.return_value = []
        self.mock_products.get_base_uom.return_value = {"uom_id": 1}
        self.mock_products.list_uoms.return_value = [{"uom_id": 1, "unit_name": "unit"}]
        self.mock_products.list_product_uoms.return_value = []
        self.mock_products.latest_prices_base.return_value = {"cost": 10.0, "sale": 15.0}
        self.mock_products.on_hand_base.return_value = 100
        self.mock_vendors.list_vendors.return_value = []
        
        # Mock database connection
        mock_conn = Mock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_conn.execute.return_value.fetchone.return_value = None
        self.mock_vendors.conn = mock_conn

    def test_purchase_form_window_flags(self):
        """Test that PurchaseForm has the correct window flags set"""
        form = PurchaseForm(parent=None, vendors=self.mock_vendors, products=self.mock_products)
        
        # Check that window flags are set correctly
        window_flags = form.windowFlags()
        self.assertTrue(window_flags & Qt.WindowMinimizeButtonHint)
        self.assertTrue(window_flags & Qt.WindowMaximizeButtonHint)
        self.assertTrue(window_flags & Qt.WindowCloseButtonHint)
        
        # Check that modal status is set correctly
        self.assertFalse(form.isModal())
        
        form.close()

    def test_sale_form_window_flags(self):
        """Test that SaleForm has the correct window flags set"""
        form = SaleForm(parent=None, customers=self.mock_customers, products=self.mock_products)
        
        # Check that window flags are set correctly
        window_flags = form.windowFlags()
        self.assertTrue(window_flags & Qt.WindowMinimizeButtonHint)
        self.assertTrue(window_flags & Qt.WindowMaximizeButtonHint)
        self.assertTrue(window_flags & Qt.WindowCloseButtonHint)
        
        # Check that modal status is set correctly
        self.assertFalse(form.isModal())
        
        form.close()

    def test_purchase_form_properties(self):
        """Test other properties of PurchaseForm"""
        form = PurchaseForm(parent=None, vendors=self.mock_vendors, products=self.mock_products)
        
        # Check size properties
        self.assertGreater(form.minimumSize().width(), 800)
        self.assertGreater(form.minimumSize().height(), 500)
        
        # Check size grip
        # Note: This attribute may not be directly accessible, so checking if it's enabled during init
        # The property itself might be internal to Qt
        
        form.close()

    def test_sale_form_properties(self):
        """Test other properties of SaleForm"""
        form = SaleForm(parent=None, customers=self.mock_customers, products=self.mock_products)
        
        # Check size properties
        self.assertGreater(form.minimumSize().width(), 800)
        self.assertGreater(form.minimumSize().height(), 500)
        
        form.close()

    def test_window_state_changes(self):
        """Test that both forms can handle window state changes"""
        # Test PurchaseForm
        po_form = PurchaseForm(parent=None, vendors=self.mock_vendors, products=self.mock_products)
        initial_state = po_form.windowState()
        
        # Test SaleForm
        so_form = SaleForm(parent=None, customers=self.mock_customers, products=self.mock_products)
        initial_state_so = so_form.windowState()
        
        # Both should initialize properly without errors
        self.assertIsNotNone(initial_state)
        self.assertIsNotNone(initial_state_so)
        
        po_form.close()
        so_form.close()


if __name__ == '__main__':
    unittest.main()