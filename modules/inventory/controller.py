from __future__ import annotations

import sqlite3
from PySide6.QtWidgets import QWidget, QTabWidget, QVBoxLayout

from ..base_module import BaseModule

from .transactions import TransactionsView
from .stock_valuation import StockValuationWidget

from ...database.repositories.inventory_repo import InventoryRepo
from ...database.repositories.products_repo import ProductsRepo

from ...utils.ui_helpers import info, error
from ...utils.helpers import today_str


class InventoryController(BaseModule):
    """
    Single controller for the Inventory module.

    Tabs:
      1) Stock Valuation       (per-product on-hand snapshot)
      2) Transactions          (recent list with adjustable LIMIT)
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

        # --- Tab 1: Stock Valuation (per-product snapshot) ---
        self._valuation_view = StockValuationWidget(conn)
        self.tabs.addTab(self._valuation_view, "Stock Valuation")

        # --- Tab 2: Transactions (read-only recent list with LIMIT) ---
        self._transactions_view = TransactionsView(conn)
        self.tabs.addTab(self._transactions_view, "Transactions")

    def get_widget(self) -> QWidget:
        return self._root
