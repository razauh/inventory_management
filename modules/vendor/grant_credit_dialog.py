from __future__ import annotations
import sqlite3
from typing import Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDateEdit, QLabel,
    QDialogButtonBox, QMessageBox
)

from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...utils.helpers import today_str
from ...utils.validators import is_positive_number


class GrantVendorCreditDialog(QDialog):
    """
    A tiny dialog to grant vendor credit (manual deposit/adjustment).
    Writes vendor_advances with source_type='deposit'.
    """
    def __init__(self, parent=None, *, conn: sqlite3.Connection, vendor_id: int, created_by: Optional[int] = None):
        super().__init__(parent)
        self.setWindowTitle("Grant Vendor Credit")
        self.conn = conn
        self.vendor_id = int(vendor_id)
        self.created_by = created_by
        self.repo = VendorAdvancesRepo(conn)
        self._payload = None

        # Header: current balance
        bal = 0.0
        try:
            bal = float(self.repo.get_balance(self.vendor_id))
        except Exception:
            bal = 0.0
        self.lab_balance = QLabel(f"Available credit: {bal:,.2f}")

        # Inputs
        self.txt_amount = QLineEdit()
        self.txt_amount.setPlaceholderText("Amount (e.g., 250)")

        self.dt_date = QDateEdit()
        self.dt_date.setCalendarPopup(True)
        self.dt_date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))

        self.txt_notes = QLineEdit()

        form = QFormLayout()
        form.addRow(self.lab_balance)
        form.addRow("Amount*", self.txt_amount)
        form.addRow("Date*", self.dt_date)
        form.addRow("Notes", self.txt_notes)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def accept(self):
        amt_s = (self.txt_amount.text() or "").strip()
        if not is_positive_number(amt_s):
            QMessageBox.warning(self, "Invalid", "Enter a positive amount.")
            return
        amount = float(amt_s)
        date_str = self.dt_date.date().toString("yyyy-MM-dd")
        notes = (self.txt_notes.text() or "").strip() or None

        try:
            # Defaults to source_type='deposit' per your repo change
            self.repo.grant_credit(
                vendor_id=self.vendor_id,
                amount=amount,
                date=date_str,
                notes=notes,
                created_by=self.created_by
            )
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not saved", f"Could not grant credit:\n{e}")
            return
        except sqlite3.OperationalError as e:
            QMessageBox.warning(self, "Not saved", f"Database error:\n{e}")
            return

        self._payload = {"amount": amount, "date": date_str, "notes": notes}
        super().accept()

    def payload(self) -> Optional[dict]:
        return self._payload
