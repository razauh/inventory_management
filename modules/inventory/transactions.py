# inventory_management/modules/inventory/transactions.py
"""
Read-only Transactions view for Inventory.

Features:
- Filters: Product (All), Date From, Date To, Limit (50/100/500)
- Live reload on filter changes + an explicit Refresh button
- CSV export of the current table
- Reuses TransactionsTableModel (columns: ID, Date, Type, Product, Qty, UoM, Notes)

Update:
- Date editors now default to today's date instead of the 1900-01-01 sentinel.
"""

from __future__ import annotations

from typing import Optional

import csv

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QDateEdit,
    QPushButton,
    QTableView,
    QFileDialog,
    QSizePolicy,
)

from .model import TransactionsTableModel
from ...utils import ui_helpers as ui
from ...database.repositories.inventory_repo import InventoryRepo


class TransactionsView(QWidget):
    """Read-only view of inventory transactions with simple filters."""

    def __init__(self, repo: InventoryRepo | object, parent: QWidget | None = None):
        """
        `repo` can be an InventoryRepo OR a raw sqlite3.Connection.
        We normalize where needed.
        """
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("Inventory — Transactions")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ------------------------------------------------------------------
        # Filters row
        # ------------------------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(6)

        # Product filter
        lbl_prod = QLabel("Product:")
        lbl_prod.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(lbl_prod)

        self.cmb_product = QComboBox(self)
        self.cmb_product.setMinimumWidth(200)
        row.addWidget(self.cmb_product, 1)

        # Date from
        lbl_from = QLabel("From:")
        lbl_from.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(lbl_from)

        self.date_from = QDateEdit(self)
        self._setup_date_edit(self.date_from)
        row.addWidget(self.date_from)

        # Date to
        lbl_to = QLabel("To:")
        lbl_to.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(lbl_to)

        self.date_to = QDateEdit(self)
        self._setup_date_edit(self.date_to)
        row.addWidget(self.date_to)

        # Limit
        lbl_limit = QLabel("Limit:")
        lbl_limit.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(lbl_limit)

        self.cmb_limit = QComboBox(self)
        for v in (50, 100, 500):
            self.cmb_limit.addItem(str(v), userData=v)
        # default 100
        idx_100 = self.cmb_limit.findData(100)
        if idx_100 >= 0:
            self.cmb_limit.setCurrentIndex(idx_100)
        row.addWidget(self.cmb_limit)

        # Spacer
        row.addStretch(1)

        # Refresh + Export
        self.btn_refresh = QPushButton("Refresh")
        self.btn_export_csv = QPushButton("Export CSV")
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_export_csv)

        root.addLayout(row)

        # ------------------------------------------------------------------
        # Table
        # ------------------------------------------------------------------
        self.tbl_txn = QTableView(self)
        self.tbl_txn.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_txn.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tbl_txn.setAlternatingRowColors(True)
        self.tbl_txn.setSortingEnabled(True)
        self.tbl_txn.setWordWrap(False)
        self.tbl_txn.horizontalHeader().setStretchLastSection(True)
        self.tbl_txn.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        root.addWidget(self.tbl_txn, 1)

        # ------------------------------------------------------------------
        # Wire signals
        # ------------------------------------------------------------------
        self.cmb_product.currentIndexChanged.connect(lambda _=None: self._reload())
        self.date_from.dateChanged.connect(lambda _=None: self._reload())
        self.date_to.dateChanged.connect(lambda _=None: self._reload())
        self.cmb_limit.currentIndexChanged.connect(lambda _=None: self._reload())
        self.btn_refresh.clicked.connect(self._reload)
        self.btn_export_csv.clicked.connect(self._on_export_csv)

        # ------------------------------------------------------------------
        # Init data
        # ------------------------------------------------------------------
        self._load_products()
        self._reload()

    # ----------------------------------------------------------------------
    # UI helpers
    # ----------------------------------------------------------------------
    def _setup_date_edit(self, w: QDateEdit) -> None:
        """
        Configure a date edit. We keep a sentinel minimum date (to allow 'no filter'
        if needed) but default the visible date to 'today' instead of the minimum.
        """
        w.setCalendarPopup(True)
        w.setDisplayFormat("yyyy-MM-dd")
        w.setSpecialValueText("")                # blank text for min date
        w.setMinimumDate(QDate(1900, 1, 1))      # sentinel
        w.setDate(QDate.currentDate())           # <-- default to current date
        w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _load_products(self) -> None:
        """
        Populate product combo box.
        First item is '(All)' with userData=None.

        Works whether self.repo is InventoryRepo (has `.conn`) or a raw sqlite3.Connection.
        """
        self.cmb_product.blockSignals(True)
        try:
            self.cmb_product.clear()
            self.cmb_product.addItem("(All)", userData=None)

            # normalize to a connection
            conn = getattr(self.repo, "conn", None) or self.repo
            rows = conn.execute(
                "SELECT product_id AS id, name AS name FROM products ORDER BY name"
            ).fetchall()

            for r in rows:
                # support both sqlite3.Row and tuples
                if hasattr(r, "keys"):
                    pid = int(r["id"])
                    name = r["name"]
                else:
                    pid = int(r[0])
                    name = r[1]
                self.cmb_product.addItem(name, userData=pid)
        except Exception as e:
            ui.info(self, "Error", f"Failed to load products: {e}")
        finally:
            self.cmb_product.blockSignals(False)

    # ----------------------------------------------------------------------
    # Convenience getters for current filters
    # ----------------------------------------------------------------------
    @property
    def selected_product_id(self) -> Optional[int]:
        return self.cmb_product.currentData()

    @property
    def date_from_str(self) -> Optional[str]:
        d = self.date_from.date()
        if d == self.date_from.minimumDate():
            return None
        txt = self.date_from.text().strip()
        return txt or None

    @property
    def date_to_str(self) -> Optional[str]:
        d = self.date_to.date()
        if d == self.date_to.minimumDate():
            return None
        txt = self.date_to.text().strip()
        return txt or None

    @property
    def limit_value(self) -> int:
        val = self.cmb_limit.currentData()
        try:
            return int(val)
        except Exception:
            return 100

    # ----------------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------------
    def _reload(self) -> None:
        """Reload table with current filters."""
        try:
            # if self.repo is a raw connection, wrap it just for this call
            repo = self.repo if isinstance(self.repo, InventoryRepo) else InventoryRepo(self.repo)

            rows = repo.find_transactions(
                date_from=self.date_from_str,
                date_to=self.date_to_str,
                product_id=self.selected_product_id,
                limit=self.limit_value,
            )
        except Exception as e:
            ui.info(self, "Error", f"Failed to load transactions: {e}")
            rows = []

        model = TransactionsTableModel(rows)
        self.tbl_txn.setModel(model)
        self.tbl_txn.resizeColumnsToContents()

    def _on_export_csv(self) -> None:
        """
        Export the current table data to CSV (UTF-8). Gracefully handle empty data.
        """
        model = self.tbl_txn.model()
        if model is None or model.rowCount() == 0:
            ui.info(self, "Nothing to export", "There are no transactions to export.")
            return

        # Ask for a path
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Transactions to CSV",
            "transactions.csv",
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not path:
            return

        # Determine headers
        headers = getattr(model, "headers", None)
        if not headers:
            headers = ["ID", "Date", "Type", "Product", "Qty", "UoM", "Notes"]

        # Write CSV
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                rows = model.rowCount()
                cols = len(headers)
                for r in range(rows):
                    row_out = []
                    for c in range(cols):
                        idx = model.index(r, c)
                        row_out.append(idx.data())
                    writer.writerow(row_out)
            ui.info(self, "Exported", f"Saved {model.rowCount()} rows to:\n{path}")
        except Exception as e:
            ui.info(self, "Error", f"Failed to export CSV:\n{e}")
