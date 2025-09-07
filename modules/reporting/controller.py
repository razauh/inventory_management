# inventory_management/modules/reporting/controller.py
from __future__ import annotations

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

        # ---- New tabs to implement (show placeholder until ready) ----
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

        # ---- Add tabs in the desired order ----
        self.tabs.addTab(vendor_widget, "Vendor Aging")
        self.tabs.addTab(customer_widget, "Customer Aging")
        self.tabs.addTab(inventory_widget, "Inventory")
        self.tabs.addTab(expenses_widget, "Expenses")
        self.tabs.addTab(financials_widget, "Financials")
        self.tabs.addTab(sales_widget, "Sales")
        self.tabs.addTab(purchases_widget, "Purchases")
        self.tabs.addTab(payments_widget, "Payments")

        # Map for programmatic navigation if other modules need to open a specific tab
        self._key_to_index: Dict[str, int] = {
            "vendor_aging": 0,
            "customer_aging": 1,
            "inventory": 2,
            "expenses": 3,
            "financials": 4,
            "sales": 5,
            "purchases": 6,
            "payments": 7,
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
            except Exception:
                # keep silent in UI; errors are printed in _safe_import_widget on load failure
                pass

    # Optional helper to jump to a tab by key from elsewhere in the app
    def open_sub(self, key: str) -> None:
        idx = self._key_to_index.get(key)
        if idx is not None and 0 <= idx < self.tabs.count():
            self.tabs.setCurrentIndex(idx)
