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

        # Record existing expense_id if editing (None for create)
        self._expense_id = (
            int(initial["expense_id"]) if initial and initial.get("expense_id") else None
        )

        # --- Widgets ------------------------------------------------------
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
        self.date_edit.setDate(QDate.currentDate())  # sensible default

        # Small clear button for date
        self.btn_clear_date = QPushButton("×")
        self.btn_clear_date.setToolTip("Clear date")
        self.btn_clear_date.setFixedWidth(24)
        self.btn_clear_date.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_clear_date.clicked.connect(
            lambda: self.date_edit.setDate(QDate.currentDate())
        )

        self.cmb_category = QComboBox()
        self.cmb_category.addItem("(None)", userData=None)
        for cid, name in categories:
            self.cmb_category.addItem(name, userData=cid)

        # Inline error message (hidden by default)
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("errorLabel")
        self.lbl_error.setStyleSheet("color:#b00020;")
        self.lbl_error.setVisible(False)

        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        # --- Layout -------------------------------------------------------
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Description*", self.edt_description)

        form.addRow("Amount*", self.spin_amount)

        # Put date + clear button on one row
        row_date = QVBoxLayout()
        row_date_w = QWidget()
        row_date_h = QVBoxLayout(row_date_w)
        row_date_h.setContentsMargins(0, 0, 0, 0)
        # Horizontal mini-row for date + clear
        from PySide6.QtWidgets import QHBoxLayout
        row_date_hh = QHBoxLayout()
        row_date_hh.setContentsMargins(0, 0, 0, 0)
        row_date_hh.addWidget(self.date_edit, 0)
        row_date_hh.addWidget(self.btn_clear_date, 0)
        row_date_h.addLayout(row_date_hh)
        form.addRow("Date*", row_date_w)

        form.addRow("Category", self.cmb_category)

        layout.addLayout(form)
        layout.addWidget(self.lbl_error)
        layout.addWidget(self.buttons)

        # --- Prefill ------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # Validation & payload
    # ----------------------------------------------------------------------
    def _fail(self, message: str, widget_to_focus: QWidget) -> None:
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(True)
        widget_to_focus.setFocus()

    def get_payload(self) -> dict | None:
        """Validate inputs and return a dict or None on failure."""
        self.lbl_error.setVisible(False)

        if not non_empty(self.edt_description.text()):
            self._fail("Description cannot be empty.", self.edt_description)
            return None

        amount = float(self.spin_amount.value())
        if amount <= 0.0:
            self._fail("Amount must be greater than 0.00.", self.spin_amount)
            return None

        date_txt = self.date_edit.date().toString("yyyy-MM-dd")
        if not date_txt:
            self._fail("Please select a valid date.", self.date_edit)
            return None

        payload = {
            "expense_id": self._expense_id,               # None for create
            "description": self.edt_description.text().strip(),
            "amount": amount,
            "date": date_txt,
            "category_id": self.cmb_category.currentData(),  # None if "(None)"
        }
        return payload

    def accept(self) -> None:  # type: ignore[override]
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    # ----------------------------------------------------------------------
    # Public API used by controller
    # ----------------------------------------------------------------------
    def payload(self) -> dict | None:
        """Return the last accepted payload, or None if dialog was canceled."""
        return self._payload

    def expense_id(self) -> int | None:
        """Return the current expense id (None for new)."""
        return self._expense_id
