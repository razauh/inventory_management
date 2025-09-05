"""
View for the expense module.

Encapsulates the widgets used by ExpenseController:
- Search box
- Optional date filter (blank == no filter)
- Category filter
- Add/Edit/Delete buttons
- Table view for expenses

Exposes convenience properties:
- search_text: str
- selected_date: str | None  (format: yyyy-MM-dd)
- selected_category_id: int | None
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
    QSizePolicy,
)
from PySide6.QtCore import Qt, QDate


class ExpenseView(QWidget):
    """UI container for listing and filtering expenses."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Expenses")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ------------------------------------------------------------------
        # Top row: search, date filter, category filter, buttons
        # ------------------------------------------------------------------
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        # Search box
        lbl_search = QLabel("Search:")
        lbl_search.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        filter_row.addWidget(lbl_search)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Description contains …")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setMinimumWidth(180)
        filter_row.addWidget(self.txt_search, 1)

        # Date filter (optional)
        lbl_date = QLabel("Date:")
        lbl_date.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        filter_row.addWidget(lbl_date)

        self.date_filter = QDateEdit(self)
        self.date_filter.setCalendarPopup(True)
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        # Represent "no date selected" via special minimum date + blank text
        self.date_filter.setSpecialValueText("")     # display blank for min date
        self.date_filter.setMinimumDate(QDate(1900, 1, 1))
        self.date_filter.setDate(self.date_filter.minimumDate())  # start blank
        self.date_filter.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        filter_row.addWidget(self.date_filter)

        # Small clear button for date
        self.btn_clear_date = QPushButton("×")
        self.btn_clear_date.setToolTip("Clear date filter")
        self.btn_clear_date.setFixedWidth(24)
        self.btn_clear_date.clicked.connect(
            lambda: self.date_filter.setDate(self.date_filter.minimumDate())
        )
        filter_row.addWidget(self.btn_clear_date)

        # Category filter
        lbl_cat = QLabel("Category:")
        lbl_cat.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        filter_row.addWidget(lbl_cat)

        self.cmb_category = QComboBox()
        self.cmb_category.setMinimumWidth(160)
        filter_row.addWidget(self.cmb_category)

        # Spacer before buttons
        filter_row.addStretch(1)

        # Buttons
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        filter_row.addWidget(self.btn_add)
        filter_row.addWidget(self.btn_edit)
        filter_row.addWidget(self.btn_delete)

        root.addLayout(filter_row)

        # ------------------------------------------------------------------
        # Table view
        # ------------------------------------------------------------------
        self.tbl_expenses = QTableView()
        self.tbl_expenses.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_expenses.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tbl_expenses.setAlternatingRowColors(True)
        self.tbl_expenses.setSortingEnabled(True)
        self.tbl_expenses.setWordWrap(False)
        self.tbl_expenses.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.tbl_expenses, 1)

    # ----------------------------------------------------------------------
    # Convenience properties for the controller
    # ----------------------------------------------------------------------
    @property
    def search_text(self) -> str:
        return self.txt_search.text().strip()

    @property
    def selected_date(self) -> str | None:
        """
        Returns the selected date as 'yyyy-MM-dd' or None if no date is selected.
        Blank text or the minimum date sentinel means 'no filter'.
        """
        if self.date_filter.date() == self.date_filter.minimumDate():
            return None
        txt = self.date_filter.text().strip()
        return txt or None

    @property
    def selected_category_id(self) -> int | None:
        """Returns the current category id or None when '(All)' is selected."""
        return self.cmb_category.currentData()
