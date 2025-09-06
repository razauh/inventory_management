"""
View for the expense module.

Encapsulates the widgets used by ExpenseController:
- Search box
- Optional single-date filter (blank == no filter, defaults to today)
- Category filter
- Advanced filters: Date From / Date To, Min Amount / Max Amount
- Buttons: Add / Edit / Delete / Manage Categories / Export CSV
- Table view for expenses
- Summary (totals by category) table

Exposes convenience properties:
- search_text: str
- selected_date: str | None          (format: yyyy-MM-dd)  # legacy single-date filter
- selected_category_id: int | None
- date_from_str: str | None          (format: yyyy-MM-dd)
- date_to_str: str | None            (format: yyyy-MM-dd)
- amount_min_val: float | None
- amount_max_val: float | None
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
    QDoubleSpinBox,
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
        # Top row: search, single-date filter, clear button, category filter,
        #          action buttons (Add/Edit/Delete/Manage/Export)
        # ------------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        # Search box
        lbl_search = QLabel("Search:")
        lbl_search.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_row.addWidget(lbl_search)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Description contains …")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setMinimumWidth(180)
        top_row.addWidget(self.txt_search, 1)

        # Single date filter (optional) — defaults to TODAY now
        lbl_date = QLabel("Date:")
        lbl_date.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_row.addWidget(lbl_date)

        self.date_filter = QDateEdit(self)
        self.date_filter.setCalendarPopup(True)
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        # Represent "no date selected" via special minimum date + blank text
        self.date_filter.setSpecialValueText("")     # display blank for min date
        self.date_filter.setMinimumDate(QDate(1900, 1, 1))
        # Initialize to today's date (previously was the sentinel min date)
        self.date_filter.setDate(QDate.currentDate())
        self.date_filter.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top_row.addWidget(self.date_filter)

        # Small clear button for the single-date filter
        self.btn_clear_date = QPushButton("×")
        self.btn_clear_date.setToolTip("Clear date filter")
        self.btn_clear_date.setFixedWidth(24)
        self.btn_clear_date.clicked.connect(
            lambda: self.date_filter.setDate(self.date_filter.minimumDate())
        )
        top_row.addWidget(self.btn_clear_date)

        # Category filter
        lbl_cat = QLabel("Category:")
        lbl_cat.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_row.addWidget(lbl_cat)

        self.cmb_category = QComboBox()
        self.cmb_category.setMinimumWidth(160)
        top_row.addWidget(self.cmb_category)

        # Spacer before buttons
        top_row.addStretch(1)

        # Action buttons
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        self.btn_manage_categories = QPushButton("Manage Categories")
        self.btn_export_csv = QPushButton("Export CSV")

        top_row.addWidget(self.btn_add)
        top_row.addWidget(self.btn_edit)
        top_row.addWidget(self.btn_delete)
        top_row.addWidget(self.btn_manage_categories)
        top_row.addWidget(self.btn_export_csv)

        root.addLayout(top_row)

        # ------------------------------------------------------------------
        # Advanced filter row: Date From / Date To / Min Amount / Max Amount
        # ------------------------------------------------------------------
        adv_row = QHBoxLayout()
        adv_row.setSpacing(6)

        # Date range
        lbl_from = QLabel("From:")
        adv_row.addWidget(lbl_from)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setSpecialValueText("")               # blank when min sentinel
        self.date_from.setMinimumDate(QDate(1900, 1, 1))     # sentinel retained
        # Default: one month back from today
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        adv_row.addWidget(self.date_from)

        lbl_to = QLabel("To:")
        adv_row.addWidget(lbl_to)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setSpecialValueText("")
        self.date_to.setMinimumDate(QDate(1900, 1, 1))
        # Default: today
        self.date_to.setDate(QDate.currentDate())
        adv_row.addWidget(self.date_to)

        # Amount range
        lbl_min = QLabel("Min:")
        adv_row.addWidget(lbl_min)
        self.amount_min = QDoubleSpinBox()
        self.amount_min.setDecimals(2)
        self.amount_min.setMinimum(0.00)
        self.amount_min.setMaximum(10**12)
        # Using 0.00 as "unset" sentinel; controller will interpret 0.00 -> None
        self.amount_min.setValue(0.00)
        adv_row.addWidget(self.amount_min)

        lbl_max = QLabel("Max:")
        adv_row.addWidget(lbl_max)
        self.amount_max = QDoubleSpinBox()
        self.amount_max.setDecimals(2)
        self.amount_max.setMinimum(0.00)
        self.amount_max.setMaximum(10**12)
        # Using 0.00 as "unset" sentinel; controller will interpret 0.00 -> None
        self.amount_max.setValue(0.00)
        adv_row.addWidget(self.amount_max)

        # stretch to keep filters compact on the left
        adv_row.addStretch(1)
        root.addLayout(adv_row)

        # ------------------------------------------------------------------
        # Main table (expenses)
        # ------------------------------------------------------------------
        self.tbl_expenses = QTableView()
        self.tbl_expenses.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_expenses.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tbl_expenses.setAlternatingRowColors(True)
        self.tbl_expenses.setSortingEnabled(True)
        self.tbl_expenses.setWordWrap(False)
        self.tbl_expenses.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.tbl_expenses, 1)

        # ------------------------------------------------------------------
        # Summary table (totals by category)
        # ------------------------------------------------------------------
        self.tbl_totals = QTableView()
        self.tbl_totals.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.tbl_totals.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.tbl_totals.setAlternatingRowColors(True)
        self.tbl_totals.setWordWrap(False)
        self.tbl_totals.setMaximumHeight(160)
        self.tbl_totals.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.tbl_totals)

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

    # ---- Advanced filter getters -----------------------------------------
    @property
    def date_from_str(self) -> str | None:
        """Return 'yyyy-MM-dd' or None if not set (min-date sentinel)."""
        if self.date_from.date() == self.date_from.minimumDate():
            return None
        txt = self.date_from.text().strip()
        return txt or None

    @property
    def date_to_str(self) -> str | None:
        """Return 'yyyy-MM-dd' or None if not set (min-date sentinel)."""
        if self.date_to.date() == self.date_to.minimumDate():
            return None
        txt = self.date_to.text().strip()
        return txt or None

    @property
    def amount_min_val(self) -> float | None:
        """Return float value or None if unset (0.00 sentinel)."""
        val = float(self.amount_min.value())
        return None if val == 0.0 else val

    @property
    def amount_max_val(self) -> float | None:
        """Return float value or None if unset (0.00 sentinel)."""
        val = float(self.amount_max.value())
        return None if val == 0.0 else val
