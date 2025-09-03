"""
View for the expense module.

This view encapsulates all the widgets used by the ExpenseController.
It provides fields for searching, date filtering, category filtering,
buttons to add/edit/delete expenses, and a table view to list them.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDateEdit,
    QComboBox,
    QPushButton,
    QTableView,
)
from PySide6.QtCore import Qt, QDate

from ..utils.helpers import today_str


class ExpenseView(QWidget):
    """UI container for listing and filtering expenses."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Expenses")

        layout = QVBoxLayout(self)

        # Top row: search, date filter, category filter, buttons
        filter_row = QHBoxLayout()

        # Search box
        filter_row.addWidget(QLabel("Search:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Description contains …")
        filter_row.addWidget(self.txt_search)

        # Date filter (optional)
        filter_row.addWidget(QLabel("Date:"))
        self.date_filter = QDateEdit()
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setCalendarPopup(True)
        # Start with no date selected
        self.date_filter.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))
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

        # Table view to display expenses
        self.tbl_expenses = QTableView()
        self.tbl_expenses.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_expenses.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tbl_expenses.setAlternatingRowColors(True)
        self.tbl_expenses.setSortingEnabled(True)
        layout.addWidget(self.tbl_expenses, 1)

    # Convenience properties for controller
    @property
    def search_text(self) -> str:
        return self.txt_search.text().strip()

    @property
    def selected_date(self) -> str | None:
        date_str = self.date_filter.date().toString("yyyy-MM-dd")
        return date_str if date_str else None

    @property
    def selected_category_id(self) -> int | None:
        return self.cmb_category.currentData()
