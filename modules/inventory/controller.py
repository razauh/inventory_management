from __future__ import annotations

import sqlite3
from PySide6.QtWidgets import QWidget, QTabWidget, QVBoxLayout

from ..base_module import BaseModule

# Your existing adjustments+recent subview and table model
from .view import InventoryView
from .model import TransactionsTableModel

# Additional simple views you already have/added
from .transactions import TransactionsView
from .stock_valuation import StockValuationWidget

# Repositories
from ...database.repositories.inventory_repo import InventoryRepo
from ...database.repositories.products_repo import ProductsRepo

# Utils
from ...utils.ui_helpers import info, error
from ...utils.helpers import today_str


class InventoryController(BaseModule):
    """
    Single controller for the Inventory module.

    Tabs:
      1) Adjustments & Recent  (existing InventoryView)
      2) Transactions          (recent list with adjustable LIMIT)
      3) Stock Valuation       (per-product on-hand snapshot)

    This file replaces the need for a separate inventory_controller.py.
    """

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        super().__init__()
        self.conn = conn
        self.user = current_user

        # Repos
        self.inv = InventoryRepo(conn)
        self.prod = ProductsRepo(conn)

        # Root container (tabbed)
        self._root = QWidget()
        layout = QVBoxLayout(self._root)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # --- Tab 1: Adjustments & Recent (your existing screen) ---
        self.view = InventoryView()  # keep your current UI as the first tab
        self.tabs.addTab(self.view, "Adjustments & Recent")
        self._wire_adjustments()
        self._load_products()
        self._reload_recent()

        # --- Tab 2: Transactions (read-only recent list with LIMIT) ---
        self._transactions_view = TransactionsView(conn)
        self.tabs.addTab(self._transactions_view, "Transactions")

        # --- Tab 3: Stock Valuation (per-product snapshot) ---
        self._valuation_view = StockValuationWidget(conn)
        self.tabs.addTab(self._valuation_view, "Stock Valuation")

    def get_widget(self) -> QWidget:
        return self._root

    # ========= Adjustments & Recent tab logic (unchanged behavior) =========

    def _wire_adjustments(self):
        self.view.btn_record.clicked.connect(self._record)
        # default date
        self.view.txt_date.setText(today_str())

    def _load_products(self):
        self.view.cmb_product.clear()
        for p in self.prod.list_products():
            self.view.cmb_product.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self._load_uoms_for_selected()
        self.view.cmb_product.currentIndexChanged.connect(self._load_uoms_for_selected)

    def _load_uoms_for_selected(self):
        self.view.cmb_uom.clear()
        pid = self.view.cmb_product.currentData()
        if not pid:
            return
        # list product-specific UOMs if any, else all UOMs
        puoms = self.prod.product_uoms(pid)
        if puoms:
            for m in puoms:
                self.view.cmb_uom.addItem(m["unit_name"], m["uom_id"])
        else:
            for u in self.prod.list_uoms():
                self.view.cmb_uom.addItem(u["unit_name"], u["uom_id"])

    def _reload_recent(self):
        rows = self.inv.recent_transactions()
        model = TransactionsTableModel(rows)
        self.view.tbl_recent.setModel(model)
        self.view.tbl_recent.resizeColumnsToContents()
        self.model = model  # keep a reference if tests need to read it

    def _record(self):
        pid = self.view.cmb_product.currentData()
        uom_id = self.view.cmb_uom.currentData()
        qty_text = (self.view.txt_qty.text() or "").strip()
        date = (self.view.txt_date.text() or "").strip() or today_str()
        notes = (self.view.txt_notes.text() or "").strip() or None

        # minimal guards for selections
        if pid is None:
            error(self.view, "Missing", "Please choose a product.")
            return
        if uom_id is None:
            error(self.view, "Missing", "Please choose a unit of measure.")
            return

        # qty can be positive or negative for 'adjustment'; must be numeric
        try:
            qty = float(qty_text)
        except Exception:
            error(self.view, "Invalid", "Quantity must be a number (e.g., 5 or -3).")
            return

        self.inv.add_adjustment(
            product_id=int(pid),
            uom_id=int(uom_id),
            quantity=qty,
            date=date,
            notes=notes,
            created_by=(self.user["user_id"] if self.user else None),
        )
        info(self.view, "Saved", "Adjustment recorded.")
        self._reload_recent()
