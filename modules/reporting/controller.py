# inventory_management/modules/reporting/controller.py
from __future__ import annotations

import logging
import sqlite3
from importlib import import_module
from typing import Dict, Optional

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel

from ..base_module import BaseModule


def _placeholder_tab(msg: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lbl = QLabel(msg)
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    return w


def _safe_import_widget(
    module_path: str,
    class_name: str,
    conn: sqlite3.Connection,
    placeholder_msg: str,
) -> QWidget:
    """
    Import a QWidget class safely. On failure, print a traceback to stderr
    and return a small placeholder tab so the module keeps loading.
    """
    try:
        mod = import_module(module_path)
        Cls = getattr(mod, class_name)
        return Cls(conn)
    except Exception as e:
        import sys, traceback
        print(f"[Reporting:{class_name}] failed to load from {module_path}: {e}", file=sys.stderr)
        traceback.print_exc()
        return _placeholder_tab(f"{placeholder_msg}\n\n({module_path}.{class_name} failed to load)")


class ReportingController(BaseModule):
    """
    Classic tabbed Reporting module.

    Tabs (in order):
      1) Vendor Aging
      2) Customer Aging
      3) Inventory
      4) Expenses
      5) Financials (Income Statement)
      6) Sales Reports
      7) Purchase Reports
      8) Payment Reports
    """

    def __init__(self, conn: sqlite3.Connection, current_user: Optional[dict] = None) -> None:
        # Keep BaseModule MRO happy if it defines __init__
        try:
            super().__init__()
        except Exception:
            pass

        self.conn = conn
        self.user = current_user

        self._root = QWidget()
        self._root.setObjectName("ReportingModuleRoot")

        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget(self._root)
        self.tabs.setObjectName("ReportingTabs")
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setMovable(False)
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)

        # ---- Existing, implemented tabs ----
        vendor_widget = _safe_import_widget(
            "inventory_management.modules.reporting.vendor_aging_reports",
            "VendorAgingTab",
            self.conn,
            "Vendor Aging tab failed to load.",
        )
        customer_widget = _safe_import_widget(
            "inventory_management.modules.reporting.customer_aging_reports",
            "CustomerAgingTab",
            self.conn,
            "Customer Aging tab failed to load.",
        )
        inventory_widget = _safe_import_widget(
            "inventory_management.modules.reporting.inventory_reports",
            "InventoryReportsTab",
            self.conn,
            "Inventory Reports tab failed to load.",
        )
        expenses_widget = _safe_import_widget(
            "inventory_management.modules.reporting.expense_reports",
            "ExpenseReportsTab",
            self.conn,
            "Expense Reports tab failed to load.",
        )
        financials_widget = _safe_import_widget(
            "inventory_management.modules.reporting.financial_reports",
            "FinancialReportsTab",
            self.conn,
            "Financial Reports tab failed to load.",
        )

        # ---- Individual tabs for proper sub-tab structure ----
        sales_widget = _safe_import_widget(
            "inventory_management.modules.reporting.sales_reports",
            "SalesReportsTab",
            self.conn,
            "Sales Reports tab not available yet.",
        )
        purchases_widget = _safe_import_widget(
            "inventory_management.modules.reporting.purchase_reports",
            "PurchaseReportsTab",
            self.conn,
            "Purchase Reports tab not available yet.",
        )
        payments_widget = _safe_import_widget(
            "inventory_management.modules.reporting.payment_reports",
            "PaymentReportsTab",
            self.conn,
            "Payment Reports tab not available yet.",
        )
        

        
        # Create a combined Payments tab with all individual sub-tabs
        combined_payments_widget = QWidget()
        combined_payments_layout = QVBoxLayout(combined_payments_widget)
        
        # Create a tab widget for all payment-related reports as direct sub-tabs
        payments_sub_tabs = QTabWidget()
        payments_sub_tabs.addTab(payments_widget, "Summary")
        
        # Since we cannot move widgets between parents in Qt, we'll need a different approach.
        # The proper way is to create a custom combined payment tab that has all the functionality
        # But for now, let's work with the existing system differently by creating new instances
        
        # For enhanced payments, we need to think differently about the approach
        # Let's create a proper implementation that creates individual tabs
        # This is complex, so we'll implement a simpler approach
        
        # Create individual report widgets to add as separate tabs
        # This approach avoids the complexities of widget reparenting while still achieving the goal
        try:
            # Summary tab (from original payment_reports.py) - this shows cleared payments only
            from inventory_management.modules.reporting.payment_reports import PaymentReportsTab
            summary_widget = PaymentReportsTab(self.conn)
            summary_widget.refresh()  # Ensure data is loaded
            payments_sub_tabs.addTab(summary_widget, "Summary")
            
            # Enhanced payment report tabs (from enhanced_payment_reports.py)
            from inventory_management.modules.reporting.enhanced_payment_reports import EnhancedPaymentReportsTab
            enhanced_instance = EnhancedPaymentReportsTab(self.conn)
            enhanced_instance.refresh()  # Ensure data is loaded
            # Add each sub-tab from EnhancedPaymentReportsTab individually
            for i in range(enhanced_instance.tabs.count()):
                sub_widget = enhanced_instance.tabs.widget(i)
                sub_title = enhanced_instance.tabs.tabText(i)
                # Create unique names to avoid conflicts
                if sub_title == "All Payments":
                    unique_title = "All Payment Records"  
                elif sub_title == "By Status":
                    unique_title = "All Payments by Status"
                elif sub_title == "Uncleared":
                    unique_title = "Uncleared Payment Records"
                else:
                    unique_title = sub_title
                payments_sub_tabs.addTab(sub_widget, unique_title)
            
            # Comprehensive payment report tabs (from comprehensive_payments_reports.py)
            from inventory_management.modules.reporting.comprehensive_payments_reports import ComprehensivePaymentReportsTab
            comp_instance = ComprehensivePaymentReportsTab(self.conn)
            comp_instance.refresh()  # Ensure data is loaded
            # Add each sub-tab from ComprehensivePaymentReportsTab individually
            for i in range(comp_instance.tabs.count()):
                sub_widget = comp_instance.tabs.widget(i)
                sub_title = comp_instance.tabs.tabText(i)
                # Create unique names to avoid conflicts
                if sub_title == "By Status":
                    unique_title = "Payment Summary by Status"
                elif sub_title == "Unprocessed":
                    unique_title = "Unprocessed Payment Records"
                elif sub_title == "All Payments":
                    unique_title = "Detailed Payment Records"
                else:
                    unique_title = sub_title
                payments_sub_tabs.addTab(sub_widget, unique_title)
                
        except Exception as e:
            # If individual sub-tab extraction fails, add fallback tabs
            summary_widget = _safe_import_widget(
                "inventory_management.modules.reporting.payment_reports",
                "PaymentReportsTab",
                self.conn,
                "Payment Reports tab not available yet.",
            )
            enhanced_payments_widget = _safe_import_widget(
                "inventory_management.modules.reporting.enhanced_payment_reports",
                "EnhancedPaymentReportsTab",
                self.conn,
                "Enhanced Payment Reports tab not available yet.",
            )
            comprehensive_payments_widget = _safe_import_widget(
                "inventory_management.modules.reporting.comprehensive_payments_reports",
                "ComprehensivePaymentReportsTab",
                self.conn,
                "Comprehensive Payment Reports tab not available yet.",
            )
            payments_sub_tabs.addTab(summary_widget, "Summary")
            payments_sub_tabs.addTab(enhanced_payments_widget, "Enhanced Payments")
            payments_sub_tabs.addTab(comprehensive_payments_widget, "Comprehensive Payments")
        
        combined_payments_layout.addWidget(payments_sub_tabs)

        # ---- Add tabs in the desired order ----
        self.tabs.addTab(vendor_widget, "Vendor Aging")
        self.tabs.addTab(customer_widget, "Customer Aging")
        self.tabs.addTab(inventory_widget, "Inventory")
        self.tabs.addTab(expenses_widget, "Expenses")
        self.tabs.addTab(financials_widget, "Financials")
        self.tabs.addTab(sales_widget, "Sales")
        self.tabs.addTab(purchases_widget, "Purchases")
        self.tabs.addTab(combined_payments_widget, "Payments")  # Payments with sub-tabs

        # Map for programmatic navigation if other modules need to open a specific tab
        self._key_to_index: Dict[str, int] = {
            "vendor_aging": 0,
            "customer_aging": 1,
            "inventory": 2,
            "expenses": 3,
            "financials": 4,
            "sales": 5,
            "purchases": 6,
            "payments": 7,  # Now refers to the combined payments tab
        }

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._safe_refresh(self.tabs.currentWidget())

    def get_widget(self) -> QWidget:
        return self._root

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        self._safe_refresh(self.tabs.widget(index))

    def _safe_refresh(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        fn = getattr(widget, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception as exc:
                # Keep UI quiet, but emit a structured warning for easier debugging.
                # We avoid any heavy imports; use stdlib logging.
                logger = logging.getLogger(__name__)
                try:
                    obj_name = widget.objectName()  # may be empty
                except Exception:
                    obj_name = ""
                logger.warning(
                    "Reporting.refresh_failed widget=%s objectName=%s exc=%s",
                    type(widget).__name__,
                    obj_name,
                    exc,
                    exc_info=True,
                )

    # Optional helper to jump to a tab by key from elsewhere in the app
    def open_sub(self, key: str) -> None:
        idx = self._key_to_index.get(key)
        if idx is not None and 0 <= idx < self.tabs.count():
            self.tabs.setCurrentIndex(idx)
