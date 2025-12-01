from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QGridLayout,
    QComboBox,
    QLineEdit,
    QDateEdit,
    QMessageBox,
)
from PySide6.QtCore import Qt, QDate

from typing import Callable, Iterable, Dict, Any
from ...utils.helpers import today_str


class SalesPaymentForm(QDialog):
    """
    Simple payment dialog for SALES, modelled after the purchase
    PaymentForm but without any vendor-bank logic.

    It records ONLY additional payments against a single sale and
    does not handle advances/credit.
    """

    PAYMENT_METHODS = {
        "CASH": "Cash",
        "BANK_TRANSFER": "Bank Transfer",
        "CHEQUE": "Cheque",
        "CROSS_CHEQUE": "Cross Cheque",
        "CASH_DEPOSIT": "Cash Deposit",
        "CARD": "Card",
        "OTHER": "Other",
    }

    METHODS_REQUIRE_BANK_AND_INSTRUMENT = {
        "BANK_TRANSFER",
        "CHEQUE",
        "CROSS_CHEQUE",
        "CASH_DEPOSIT",
    }
    METHODS_REQUIRE_COMPANY_BANK = METHODS_REQUIRE_BANK_AND_INSTRUMENT
    METHODS_REQUIRE_INSTRUMENT = METHODS_REQUIRE_BANK_AND_INSTRUMENT

    def __init__(
        self,
        parent=None,
        *,
        sale_id: str,
        remaining: float,
        list_company_bank_accounts: Callable[[], Iterable[Dict[str, Any]]],
    ):
        super().__init__(parent)
        self.setWindowTitle("Record Payment")
        self.setModal(True)
        self._sale_id = str(sale_id)
        self._remaining = float(remaining)
        self._list_company_bank_accounts = list_company_bank_accounts
        self._payload = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # --- Sale info / remaining ---
        box_info = QGroupBox("Sale Information")
        info_lay = QHBoxLayout(box_info)
        self.lbl_sale_id = QLabel(f"Sale ID: {self._sale_id}")
        info_lay.addWidget(self.lbl_sale_id)
        outer.addWidget(box_info)

        box_sum = QGroupBox("Payment Summary")
        sum_lay = QHBoxLayout(box_sum)
        self.lbl_remaining = QLabel(f"Remaining: {self._remaining:0.2f}")
        sum_lay.addWidget(self.lbl_remaining)
        outer.addWidget(box_sum)

        # --- Payment details ---
        box_pay = QGroupBox("Payment Details")
        grid = QGridLayout(box_pay)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.amount = QLineEdit()
        self.amount.setPlaceholderText(f"{self._remaining:0.2f}")

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))

        self.method = QComboBox()
        for key, label in self.PAYMENT_METHODS.items():
            self.method.addItem(label, key)

        self.company_acct = QComboBox()

        self.instr_no = QLineEdit()
        self.instr_no.setPlaceholderText("Instrument / Cheque / Slip #")

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Notes (optional)")

        def add_row(row: int, label: str, widget):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)

        add_row(0, "Amount", self.amount)
        add_row(1, "Date", self.date)
        add_row(2, "Method", self.method)
        add_row(3, "Company Bank", self.company_acct)
        add_row(4, "Instrument No", self.instr_no)
        add_row(5, "Notes", self.notes)

        outer.addWidget(box_pay, 1)

        # --- Buttons ---
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Record Payment")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        # wiring
        self.amount.textChanged.connect(self._on_amount_changed)
        self.method.currentIndexChanged.connect(self._refresh_field_enablement)

        # data
        self._reload_company_accounts()
        self._on_amount_changed()
        self.resize(520, 360)

    # --- helpers ---------------------------------------------------------

    def _to_float(self, txt: str) -> float:
        try:
            return float(txt.strip())
        except Exception:
            return 0.0

    def _reload_company_accounts(self):
        self.company_acct.clear()
        self.company_acct.addItem("", None)
        try:
            rows = list(self._list_company_bank_accounts()) if self._list_company_bank_accounts else []
        except Exception:
            rows = []
        for r in rows:
            rid = r.get("id")
            try:
                rid_int = int(rid) if rid is not None else None
            except Exception:
                rid_int = None
            self.company_acct.addItem(str(r.get("name", "")), rid_int)

    def _current_company_bank_id(self):
        data = self.company_acct.currentData()
        if isinstance(data, int):
            return data
        try:
            return int(data) if data is not None else None
        except Exception:
            return None

    def _on_amount_changed(self):
        amt = self._to_float(self.amount.text())
        enable = amt > 0.0
        self.date.setEnabled(enable)
        self.method.setEnabled(enable)
        self.notes.setEnabled(enable)
        self._refresh_field_enablement()

    def _refresh_field_enablement(self):
        amt = self._to_float(self.amount.text())
        enable = amt > 0.0
        key = self.method.currentData()

        needs_bank = key in self.METHODS_REQUIRE_COMPANY_BANK
        needs_instr = key in self.METHODS_REQUIRE_INSTRUMENT

        self.company_acct.setEnabled(enable and needs_bank)
        self.instr_no.setEnabled(enable and needs_instr)

        if not enable:
            self.company_acct.setCurrentIndex(0)
            self.instr_no.clear()

    # --- validation / payload --------------------------------------------

    def _validate(self) -> tuple[bool, str]:
        amt = self._to_float(self.amount.text())
        if amt <= 0.0:
            return False, "Payment amount must be greater than zero."
        if amt - self._remaining > 1e-9:
            return False, "Payment amount cannot exceed remaining for this sale."

        key = self.method.currentData()
        if not key:
            return False, "Select a payment method."

        if key in self.METHODS_REQUIRE_COMPANY_BANK and self._current_company_bank_id() is None:
            return False, "Select a company bank account for this method."

        if key in self.METHODS_REQUIRE_INSTRUMENT and not (self.instr_no.text().strip()):
            return False, "Enter instrument / cheque / slip number."

        return True, ""

    def accept(self):
        ok, msg = self._validate()
        if not ok:
            QMessageBox.warning(self, "Cannot record payment", msg)
            return

        # Resolve internal method key instead of display text
        method_key = self.method.currentData()

        self._payload = {
            "sale_id": self._sale_id,
            "amount": self._to_float(self.amount.text()),
            "date": self.date.date().toString("yyyy-MM-dd"),
            "method": method_key,
            "bank_account_id": self._current_company_bank_id(),
            "instrument_no": (self.instr_no.text().strip() or None),
            "notes": (self.notes.text().strip() or None),
        }
        super().accept()

    def payload(self):
        return self._payload
