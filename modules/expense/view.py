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
        self.date_filter = QDateEdit(self)
        self.date_filter.setCalendarPopup(True)
        self.date_filter.setDisplayFormat("yyyy-MM-dd")

        # Represent "no date selected" via special value
        self.date_filter.setSpecialValueText("")  # display blank for min date
        self.date_filter.setMinimumDate(QDate(1900, 1, 1))
        self.date_filter.setDate(self.date_filter.minimumDate())  # show blank (special value)

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
        # If at the minimum date, treat as "no filter"
        if self.date_filter.date() == self.date_filter.minimumDate():
            return None
        txt = self.date_filter.text().strip()
        return txt or None

    @property
    def selected_category_id(self) -> int | None:
        return self.cmb_category.currentData()
