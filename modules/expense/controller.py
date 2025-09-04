"""
Controller for the expense module.

This controller wires together the expense repository, the Qt view,
models and basic filtering logic.  It provides a simple listing
interface with search, date and category filters.  Buttons for
adding, editing and deleting expenses and categories are provided
but currently only display informational messages via the shared
``ui_helpers.info`` helper.  More complete forms can be added later
to handle CRUD operations interactively.

The controller follows the same architectural pattern as other
controllers in the application (e.g. vendor, customer).  It
inherits from ``BaseModule`` and implements ``get_widget()`` to
expose its root widget to the main application.
"""

from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QDateEdit,
    QComboBox,
    QPushButton,
    QTableView,
    QLabel,
    QMessageBox,  # <-- added for test monkeypatching
)

from ..base_module import BaseModule
from ...utils import ui_helpers as ui
from ...utils.helpers import today_str
from ...database.repositories.expenses_repo import ExpensesRepo
from .model import ExpensesTableModel


class ExpenseController(BaseModule):
    """UI controller for viewing and filtering expenses."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        # Repository for data operations
        self.repo = ExpensesRepo(conn)
        # Root widget
        self.view = QWidget()
        self.view.setWindowTitle("Expenses")
        # Build UI
        self._build_ui()
        # Initial load
        self._load_categories()
        self._reload()

    # ------------------------------------------------------------------
    # BaseModule implementation
    # ------------------------------------------------------------------
    def get_widget(self) -> QWidget:
        return self.view

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Builds widgets and layouts for the module."""
        layout = QVBoxLayout(self.view)

        # Filter row
        filter_row = QHBoxLayout()
        # Search by description
        filter_row.addWidget(QLabel("Search:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Description contains …")
        filter_row.addWidget(self.txt_search)
        # Date filter
        filter_row.addWidget(QLabel("Date:"))
        self.date_filter = QDateEdit()
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setCalendarPopup(True)
        # default to empty (no date filter)
        self.date_filter.setDate(datetime.date.today())
        self.date_filter.clear()
        filter_row.addWidget(self.date_filter)
        # Category filter
        filter_row.addWidget(QLabel("Category:"))
        self.cmb_category = QComboBox()
        filter_row.addWidget(self.cmb_category)
        # Buttons
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        filter_row.addWidget(self.btn_add)
        filter_row.addWidget(self.btn_edit)
        filter_row.addWidget(self.btn_delete)
        layout.addLayout(filter_row)

        # Table view for expenses
        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # Connect signals
        self.txt_search.textChanged.connect(lambda _text: self._reload())
        self.date_filter.dateChanged.connect(lambda _date: self._reload())
        self.cmb_category.currentIndexChanged.connect(lambda _index: self._reload())
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _load_categories(self) -> None:
        """Populate the category filter combo box."""
        cats = self.repo.list_categories()
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("(All)", userData=None)
        for c in cats:
            self.cmb_category.addItem(c.name, userData=c.category_id)
        self.cmb_category.blockSignals(False)

    def _reload(self) -> None:
        """Reload the expenses table based on current filters."""
        query = self.txt_search.text().strip()
        # Use an empty string if date is not set (checked by isNull)
        date: Optional[str] = None
        if self.date_filter.date().isValid() and self.date_filter.date().toString("yyyy-MM-dd"):
            # If user cleared the date, toString returns empty string; treat as no filter
            date_str = self.date_filter.date().toString("yyyy-MM-dd")
            date = date_str if date_str else None
        cat_id = self.cmb_category.currentData()
        # Query repo
        rows = self.repo.search_expenses(query=query, date=date, category_id=cat_id)
        # Set model
        model = ExpensesTableModel(rows)
        self.table.setModel(model)
        # Resize columns to contents for better display
        self.table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def _get_selected_expense_id(self) -> Optional[int]:
        """Return the currently selected expense_id, or None."""
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return None
        row = idxs[0].row()
        model = self.table.model()
        exp_id = model.data(model.index(row, 0), Qt.DisplayRole)
        return exp_id

    def _on_add(self) -> None:
        ui.info(self.view, "Not Implemented", "Add expense form is not implemented yet.")

    def _on_edit(self) -> None:
        exp_id = self._get_selected_expense_id()
        if exp_id is None:
            ui.info(self.view, "Select", "Please select an expense to edit.")
            return
        ui.info(self.view, "Not Implemented", f"Edit expense {exp_id} is not implemented yet.")

    def _on_delete(self) -> None:
        exp_id = self._get_selected_expense_id()
        if exp_id is None:
            ui.info(self.view, "Select", "Please select an expense to delete.")
            return
        # Confirm deletion (lazy import preserved)
        from PySide6.QtWidgets import QMessageBox

        resp = QMessageBox.question(
            self.view,
            "Delete",
            f"Are you sure you want to delete expense {exp_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        # Delete via repo and reload
        self.repo.delete_expense(exp_id)
        self._reload()
