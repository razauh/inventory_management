"""
Dialog for creating and editing expenses.

Collects: description, amount, date, and category.
Validates: non-empty description, amount > 0.0.
On accept, `payload()` returns a dict compatible with ExpensesRepo.
"""

from __future__ import annotations

from typing import Iterable, Tuple, Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QDateEdit,
    QComboBox,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import QDate, Qt

from ...utils.validators import non_empty


class ExpenseForm(QDialog):
    """Modal dialog for adding or editing an expense."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        categories: Iterable[Tuple[int, str]] = (),
        initial: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Expense")
        self.setModal(True)
        self.setMinimumWidth(420)

        # Existing expense_id if editing (None for create)
        self._expense_id = (
            int(initial["expense_id"]) if initial and initial.get("expense_id") else None
        )

        # ---------------- Widgets ----------------
        self.edt_description = QLineEdit()
        self.edt_description.setPlaceholderText("e.g., Stationery, fuel, utilities…")
        self.edt_description.setClearButtonEnabled(True)

        self.spin_amount = QDoubleSpinBox()
        self.spin_amount.setMinimum(0.0)   # validation enforces > 0.0
        self.spin_amount.setMaximum(10**9)
        self.spin_amount.setDecimals(2)
        self.spin_amount.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin_amount.setAlignment(Qt.AlignRight)

        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())  # default to today

        # Small clear button for date (resets to today)
        self.btn_clear_date = QPushButton("×")
        self.btn_clear_date.setToolTip("Reset date to today")
        self.btn_clear_date.setFixedWidth(24)
        self.btn_clear_date.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_clear_date.clicked.connect(
            lambda: self.date_edit.setDate(QDate.currentDate())
        )

        self.cmb_category = QComboBox()
        self.cmb_category.addItem("(None)", userData=None)
        for cid, name in categories:
            self.cmb_category.addItem(name, userData=cid)

        # Inline error label (hidden by default)
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("errorLabel")
        self.lbl_error.setStyleSheet("color:#b00020;")
        self.lbl_error.setVisible(False)

        # OK/Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        # ---------------- Layout ----------------
        layout = QVBoxLayout(self)
        form = QFormLayout()

        form.addRow("Description*", self.edt_description)
        form.addRow("Amount*", self.spin_amount)

        # Date row: date widget + clear button side-by-side
        date_row = QWidget()
        date_row_h = QHBoxLayout(date_row)
        date_row_h.setContentsMargins(0, 0, 0, 0)
        date_row_h.addWidget(self.date_edit, 0)
        date_row_h.addWidget(self.btn_clear_date, 0)
        form.addRow("Date*", date_row)

        form.addRow("Category", self.cmb_category)

        layout.addLayout(form)
        layout.addWidget(self.lbl_error)
        layout.addWidget(self.buttons)

        # ---------------- Prefill (edit mode) ----------------
        if initial:
            self.edt_description.setText(initial.get("description", ""))
            try:
                self.spin_amount.setValue(float(initial.get("amount") or 0.0))
            except Exception:
                self.spin_amount.setValue(0.0)

            date_val = initial.get("date")
            if date_val:
                qd = QDate.fromString(date_val, "yyyy-MM-dd")
                if qd.isValid():
                    self.date_edit.setDate(qd)

            cat_id = initial.get("category_id")
            if cat_id is not None:
                idx = self.cmb_category.findData(cat_id)
                if idx >= 0:
                    self.cmb_category.setCurrentIndex(idx)

        # Accessibility / focus flow
        self.setTabOrder(self.edt_description, self.spin_amount)
        self.setTabOrder(self.spin_amount, self.date_edit)
        self.setTabOrder(self.date_edit, self.cmb_category)
        self.setTabOrder(self.cmb_category, self.buttons)

        self._payload: Optional[dict] = None

    # ---------------- Validation & payload ----------------
    def _fail(self, message: str, widget_to_focus: QWidget) -> None:
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(True)
        widget_to_focus.setFocus()

    def payload(self) -> dict | None:
        """Return the last accepted payload, or None if dialog was canceled."""
        return self._payload

    def _build_payload(self) -> dict:
        date_str = self.date_edit.date().toString("yyyy-MM-dd")
        return {
            "expense_id": self._expense_id,  # None for create
            "description": self.edt_description.text().strip(),
            "amount": float(self.spin_amount.value()),
            "date": date_str,
            "category_id": self.cmb_category.currentData(),  # None if "(None)"
        }

    def accept(self) -> None:  # type: ignore[override]
        # Clear previous error
        self.lbl_error.setVisible(False)

        # Description validation
        if not non_empty(self.edt_description.text()):
            self._fail("Description cannot be empty.", self.edt_description)
            return

        # Amount validation
        amount = float(self.spin_amount.value())
        if amount <= 0.0:
            self._fail("Amount must be greater than 0.00.", self.spin_amount)
            return

        # Date sanity (QDateEdit always has a date; still ensure text format)
        date_txt = self.date_edit.date().toString("yyyy-MM-dd")
        if not date_txt:
            self._fail("Please select a valid date.", self.date_edit)
            return

        # Build and stash payload
        self._payload = self._build_payload()
        super().accept()

    # ---------------- Public helpers ----------------
    def expense_id(self) -> int | None:
        """Return the current expense id (None for new)."""
        return self._expense_id
