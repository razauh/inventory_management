"""
Dialog for creating and editing expenses.

The form collects a description, amount, date, and category from the user.
It normalizes whitespace and validates that description is not empty and
amount is positive.  If invalid, it returns None and sets focus to the
first offending field.  On success, call `.payload()` to get the saved
payload after `.accept()` returns True.
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
)
from PySide6.QtCore import QDate

from ...utils.validators import non_empty


class ExpenseForm(QDialog):
    """Modal dialog for adding or editing an expense."""

    def __init__(
        self,
        parent=None,
        *,
        categories: Iterable[Tuple[int, str]] = (),
        initial: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Expense")
        self.setModal(True)

        # Record existing expense_id if editing (None for create)
        self._expense_id = int(initial["expense_id"]) if initial and initial.get("expense_id") else None

        # Widgets
        self.edt_description = QLineEdit()
        self.spin_amount = QDoubleSpinBox()
        self.spin_amount.setMinimum(0.0)
        self.spin_amount.setMaximum(10**9)
        self.spin_amount.setPrefix("")
        self.spin_amount.setDecimals(2)
        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.cmb_category = QComboBox()

        # Populate category list
        self.cmb_category.addItem("(None)", userData=None)
        for cid, name in categories:
            self.cmb_category.addItem(name, userData=cid)

        # Layout
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Description*", self.edt_description)
        form.addRow("Amount*", self.spin_amount)
        form.addRow("Date*", self.date_edit)
        form.addRow("Category", self.cmb_category)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Pre-fill initial data if provided
        if initial:
            self.edt_description.setText(initial.get("description", ""))
            self.spin_amount.setValue(float(initial.get("amount") or 0.0))
            # Set date
            date_val = initial.get("date")
            if date_val:
                self.date_edit.setDate(QDate.fromString(date_val, "yyyy-MM-dd"))
            # Set category
            cat_id = initial.get("category_id")
            if cat_id is not None:
                index = self.cmb_category.findData(cat_id)
                if index >= 0:
                    self.cmb_category.setCurrentIndex(index)

        self._payload: Optional[dict] = None

    def get_payload(self) -> dict | None:
        """Validate inputs and return a dict or None on failure."""
        if not non_empty(self.edt_description.text()):
            self.edt_description.setFocus()
            return None
        if self.spin_amount.value() <= 0:
            self.spin_amount.setFocus()
            return None

        payload = {
            "expense_id": getattr(self, "_expense_id", None),  # include key for both create/edit
            "description": self.edt_description.text().strip(),
            "amount": float(self.spin_amount.value()),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "category_id": self.cmb_category.currentData(),  # None if "(None)" selected
        }
        return payload

    def accept(self) -> None:
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    def payload(self) -> dict | None:
        return self._payload

    def expense_id(self) -> int | None:
        return self._expense_id
