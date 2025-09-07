from __future__ import annotations

from typing import Callable, Optional

try:
    # Prefer PySide6 per spec
    from PySide6.QtCore import Qt, QDate
    from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDateEdit,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    raise


# -----------------------------
# i18n shim
# -----------------------------

def _t(s: str) -> str:
    """Trivial translation shim (replace with Qt tr() if you wire it)."""
    return s


# -----------------------------
# Canonical sets
# -----------------------------

METHODS = [
    "Cash",
    "Bank Transfer",
    "Card",
    "Cheque",
    "Cash Deposit",
    "Other",
]

INSTRUMENT_TYPES = [
    "online",
    "cross_cheque",
    "cash_deposit",
    "pay_order",
    "other",
]

CLEARING_STATES = ["posted", "pending", "cleared", "bounced"]

FORCED_INST_FOR_METHOD = {
    "Bank Transfer": "online",
    "Cheque": "cross_cheque",
    "Cash Deposit": "cash_deposit",
}

BANKISH_METHODS = {"Bank Transfer", "Cheque", "Cash Deposit"}


# -----------------------------
# Public API
# -----------------------------

def open_vendor_payment_form(
    *,
    vendor_id: int,
    purchase_id: Optional[str] = None,
    defaults: Optional[dict] = None,
) -> Optional[dict]:
    """Show a modal dialog to capture a vendor payment/refund.
    Returns a mapping compatible with PurchasePaymentsRepo.record_payment(...)
    or None if the user cancels.
    """
    app = QApplication.instance()
    owns_app = False
    if app is None:
        app = QApplication([])
        owns_app = True
    dlg = VendorPaymentForm(vendor_id=vendor_id, purchase_id=purchase_id, defaults=defaults or {})
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None
    if owns_app:
        app.quit()
    return payload


class VendorPaymentForm(QDialog):
    """Vendor Payment (or Refund when amount < 0) entry form.

    Exposes:
      - exec() -> int (Accepted/Rejected)
      - payload() -> dict | None (None iff canceled)
    """

    def __init__(self, *, vendor_id: int, purchase_id: Optional[str], defaults: dict):
        super().__init__(None)
        self._vendor_id = vendor_id
        self._purchase_id = purchase_id
        self._defaults = defaults or {}
        self._payload: Optional[dict] = None

        # Optional adapters
        self._list_company_bank_accounts: Optional[Callable[[], list]] = self._defaults.get("list_company_bank_accounts")
        self._list_vendor_bank_accounts: Optional[Callable[[int], list]] = self._defaults.get("list_vendor_bank_accounts")
        self._today_func: Optional[Callable[[], str]] = self._defaults.get("today")
        self._vendor_display: Optional[str] = self._defaults.get("vendor_display")

        # Prefills
        self._prefill_method: Optional[str] = self._defaults.get("method")
        self._prefill_amount: Optional[float] = self._defaults.get("amount")
        self._prefill_date: Optional[str] = self._defaults.get("date")
        self._prefill_bank_id: Optional[int] = self._defaults.get("bank_account_id")
        self._prefill_vendor_bank_id: Optional[int] = self._defaults.get("vendor_bank_account_id")
        self._prefill_inst_type: Optional[str] = self._defaults.get("instrument_type")
        self._prefill_inst_no: Optional[str] = self._defaults.get("instrument_no")
        self._prefill_inst_date: Optional[str] = self._defaults.get("instrument_date")
        self._prefill_dep_date: Optional[str] = self._defaults.get("deposited_date")
        self._prefill_cleared_date: Optional[str] = self._defaults.get("cleared_date")
        self._prefill_clearing_state: Optional[str] = self._defaults.get("clearing_state")
        self._prefill_ref_no: Optional[str] = self._defaults.get("ref_no")
        self._prefill_notes: Optional[str] = self._defaults.get("notes")

        self._build_ui()
        self._load_company_banks()
        self._load_vendor_banks()
        self._apply_prefills()
        self._wire_signals()
        self._update_by_method()
        self._validate_live()

    # ------------------------- UI -------------------------
    def _build_ui(self) -> None:
        self.setModal(True)
        self.setWindowTitle(_t("Vendor Payment"))

        outer = QVBoxLayout(self)

        # Header/context
        title = QLabel(_t("Vendor Payment"))
        title.setObjectName("dlgTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(title)

        ctx = QHBoxLayout()
        vendor_lbl = QLabel(_t("Vendor: ") + (str(self._vendor_display) if self._vendor_display else f"#{self._vendor_id}"))
        ctx.addWidget(vendor_lbl)
        if self._purchase_id:
            ctx.addWidget(QLabel(_t("Purchase: ") + str(self._purchase_id)))
        ctx.addStretch(1)
        outer.addLayout(ctx)

        form = QFormLayout()
        outer.addLayout(form)

        # Date with optional empty checkbox
        date_row = QHBoxLayout()
        self.dateEdit = QDateEdit()
        self.dateEdit.setCalendarPopup(True)
        self.dateEdit.setDisplayFormat("yyyy-MM-dd")
        if self._today_func:
            try:
                y, m, d = map(int, (self._today_func() or "").split("-"))
                self.dateEdit.setDate(QDate(y, m, d))
            except Exception:
                self.dateEdit.setDate(QDate.currentDate())
        else:
            self.dateEdit.setDate(QDate.currentDate())
        self.noDateCheck = QCheckBox(_t("Leave date empty (use DB default)"))
        date_row.addWidget(self.dateEdit, 1)
        date_row.addWidget(self.noDateCheck, 0)
        w_date = QWidget(); w_date.setLayout(date_row)
        lbl_date = QLabel(_t("Date")); lbl_date.setBuddy(self.dateEdit)
        form.addRow(lbl_date, w_date)

        # Amount (QLineEdit with validator to accept +/- decimals)
        self.amountEdit = QLineEdit()
        v = QDoubleValidator(-1_000_000_000.0, 1_000_000_000.0, 2)
        v.setNotation(QDoubleValidator.StandardNotation)
        self.amountEdit.setValidator(v)
        self.amountEdit.setPlaceholderText(_t("e.g., 1000.00 or -250.00"))
        lbl_amount = QLabel(_t("Amount")); lbl_amount.setBuddy(self.amountEdit)
        form.addRow(lbl_amount, self.amountEdit)

        # Method
        self.methodCombo = QComboBox()
        for m in METHODS:
            self.methodCombo.addItem(m)
        lbl_method = QLabel(_t("Method")); lbl_method.setBuddy(self.methodCombo)
        form.addRow(lbl_method, self.methodCombo)

        # Company bank
        self.companyBankCombo = QComboBox()
        lbl_cbank = QLabel(_t("Company Bank")); lbl_cbank.setBuddy(self.companyBankCombo)
        form.addRow(lbl_cbank, self.companyBankCombo)

        # Vendor bank
        self.vendorBankCombo = QComboBox()
        lbl_vbank = QLabel(_t("Vendor Bank")); lbl_vbank.setBuddy(self.vendorBankCombo)
        form.addRow(lbl_vbank, self.vendorBankCombo)

        # Instrument panel
        self.instrumentTypeCombo = QComboBox()
        for t in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.addItem(t)
        lbl_instype = QLabel(_t("Instrument Type")); lbl_instype.setBuddy(self.instrumentTypeCombo)
        form.addRow(lbl_instype, self.instrumentTypeCombo)

        self.instrumentNoEdit = QLineEdit()
        lbl_insno = QLabel(_t("Instrument No")); lbl_insno.setBuddy(self.instrumentNoEdit)
        form.addRow(lbl_insno, self.instrumentNoEdit)

        self.instrumentDateEdit = QDateEdit(); self.instrumentDateEdit.setCalendarPopup(True); self.instrumentDateEdit.setDisplayFormat("yyyy-MM-dd")
        lbl_idate = QLabel(_t("Instrument Date")); lbl_idate.setBuddy(self.instrumentDateEdit)
        form.addRow(lbl_idate, self.instrumentDateEdit)

        self.depositedDateEdit = QDateEdit(); self.depositedDateEdit.setCalendarPopup(True); self.depositedDateEdit.setDisplayFormat("yyyy-MM-dd")
        lbl_ddate = QLabel(_t("Deposited Date")); lbl_ddate.setBuddy(self.depositedDateEdit)
        form.addRow(lbl_ddate, self.depositedDateEdit)

        self.clearingStateCombo = QComboBox(); [self.clearingStateCombo.addItem(s) for s in CLEARING_STATES]
        lbl_cstate = QLabel(_t("Clearing State")); lbl_cstate.setBuddy(self.clearingStateCombo)
        form.addRow(lbl_cstate, self.clearingStateCombo)

        self.clearedDateEdit = QDateEdit(); self.clearedDateEdit.setCalendarPopup(True); self.clearedDateEdit.setDisplayFormat("yyyy-MM-dd")
        lbl_cleared = QLabel(_t("Cleared Date")); lbl_cleared.setBuddy(self.clearedDateEdit)
        form.addRow(lbl_cleared, self.clearedDateEdit)

        # Misc
        self.refNoEdit = QLineEdit(); lbl_ref = QLabel(_t("Ref No")); lbl_ref.setBuddy(self.refNoEdit)
        form.addRow(lbl_ref, self.refNoEdit)
        self.notesEdit = QPlainTextEdit(); self.notesEdit.setPlaceholderText(_t("Optional notes"))
        lbl_notes = QLabel(_t("Notes")); lbl_notes.setBuddy(self.notesEdit)
        form.addRow(lbl_notes, self.notesEdit)

        # Inline error
        self.errorLabel = QLabel("")
        self.errorLabel.setStyleSheet("color:#b00020;")
        outer.addWidget(self.errorLabel)

        # Buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.saveBtn: QPushButton = self.buttonBox.button(QDialogButtonBox.Save)
        self.cancelBtn: QPushButton = self.buttonBox.button(QDialogButtonBox.Cancel)
        self.saveBtn.setDefault(True)
        self.saveBtn.setShortcut(QKeySequence("Alt+S"))
        self.cancelBtn.setShortcut(QKeySequence("Alt+C"))
        self.saveBtn.clicked.connect(self._on_save)
        self.cancelBtn.clicked.connect(self.reject)
        outer.addWidget(self.buttonBox)

        # Labels map to toggle required asterisks
        self._label_map = {
            self.companyBankCombo: lbl_cbank,
            self.vendorBankCombo: lbl_vbank,
            self.instrumentNoEdit: lbl_insno,
            self.amountEdit: lbl_amount,
        }

    # ------------------------- Data Loading -------------------------
    def _load_company_banks(self) -> None:
        self.companyBankCombo.clear()
        self.companyBankCombo.addItem("", None)
        rows = []
        try:
            if self._list_company_bank_accounts:
                rows = list(self._list_company_bank_accounts())
        except Exception:
            rows = []
        for r in rows:
            self.companyBankCombo.addItem(str(r.get("label") or r.get("name") or r.get("title") or ""), int(r.get("account_id") if r.get("account_id") is not None else r.get("id")))
        # preselect
        if self._prefill_bank_id is not None:
            for i in range(self.companyBankCombo.count()):
                if self.companyBankCombo.itemData(i) == self._prefill_bank_id:
                    self.companyBankCombo.setCurrentIndex(i)
                    break

    def _load_vendor_banks(self) -> None:
        self.vendorBankCombo.clear()
        self.vendorBankCombo.addItem("", None)
        rows = []
        try:
            if self._list_vendor_bank_accounts and isinstance(self._vendor_id, int):
                rows = list(self._list_vendor_bank_accounts(self._vendor_id))
        except Exception:
            rows = []
        for r in rows:
            self.vendorBankCombo.addItem(str(r.get("label") or r.get("name") or ""), int(r.get("vendor_bank_account_id") if r.get("vendor_bank_account_id") is not None else r.get("id")))
        if self._prefill_vendor_bank_id is not None:
            for i in range(self.vendorBankCombo.count()):
                if self.vendorBankCombo.itemData(i) == self._prefill_vendor_bank_id:
                    self.vendorBankCombo.setCurrentIndex(i)
                    break

    # ------------------------- Prefills -------------------------
    def _apply_prefills(self) -> None:
        if self._prefill_method in METHODS:
            self.methodCombo.setCurrentIndex(METHODS.index(self._prefill_method))
        if isinstance(self._prefill_amount, (int, float)):
            self.amountEdit.setText(f"{float(self._prefill_amount):.2f}")
        if isinstance(self._prefill_date, str):
            self.noDateCheck.setChecked(False)
            self._set_date_from_str(self.dateEdit, self._prefill_date)
        if self._prefill_inst_type in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index(self._prefill_inst_type))
        if isinstance(self._prefill_inst_no, str):
            self.instrumentNoEdit.setText(self._prefill_inst_no)
        if isinstance(self._prefill_inst_date, str):
            self._set_date_from_str(self.instrumentDateEdit, self._prefill_inst_date)
        if isinstance(self._prefill_dep_date, str):
            self._set_date_from_str(self.depositedDateEdit, self._prefill_dep_date)
        if isinstance(self._prefill_cleared_date, str):
            self._set_date_from_str(self.clearedDateEdit, self._prefill_cleared_date)
        if self._prefill_clearing_state in CLEARING_STATES:
            self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index(self._prefill_clearing_state))
        if isinstance(self._prefill_ref_no, str):
            self.refNoEdit.setText(self._prefill_ref_no)
        if isinstance(self._prefill_notes, str):
            self.notesEdit.setPlainText(self._prefill_notes)

    # ------------------------- Signals -------------------------
    def _wire_signals(self) -> None:
        self.methodCombo.currentIndexChanged.connect(self._update_by_method)
        self.clearingStateCombo.currentIndexChanged.connect(self._on_clearing_changed)
        self.amountEdit.textChanged.connect(self._on_amount_changed)

    # ------------------------- Reactions -------------------------
    def _on_amount_changed(self, _txt: str) -> None:
        # Update title based on sign
        amt = self._amount_value()
        if amt is not None and amt < 0:
            self.setWindowTitle(_t("Vendor Refund"))
        else:
            self.setWindowTitle(_t("Vendor Payment"))
        self._update_by_method()
        self._validate_live()

    def _on_clearing_changed(self) -> None:
        state = self.clearingStateCombo.currentText()
        enable_cd = state == "cleared"
        self.clearedDateEdit.setEnabled(enable_cd)
        self._validate_live()

    def _update_by_method(self) -> None:
        method = self.methodCombo.currentText()
        amt = self._amount_value() or 0.0

        # Instrument type enforcement/locking for certain methods
        forced = FORCED_INST_FOR_METHOD.get(method)
        if forced:
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index(forced))
            self.instrumentTypeCombo.setEnabled(False)
        else:
            # Cash/Card/Other: allow choosing, but default to 'other'
            self.instrumentTypeCombo.setEnabled(True)
            if self.instrumentTypeCombo.currentText() not in INSTRUMENT_TYPES:
                self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index("other"))

        # Company bank enable/require
        needs_company = method in {"Bank Transfer", "Cheque"}
        self.companyBankCombo.setEnabled(needs_company or method == "Cash Deposit")  # optional for deposit
        self._set_required_label(self.companyBankCombo, needs_company)
        if method == "Cash":
            # Must be NULL for Cash
            self.companyBankCombo.setCurrentIndex(0)

        # Vendor bank requirement only when amount > 0 for bankish
        needs_vendor_bank = (amt > 0) and (method in BANKISH_METHODS)
        self.vendorBankCombo.setEnabled(method in BANKISH_METHODS)
        self._set_required_label(self.vendorBankCombo, needs_vendor_bank)
        if method == "Cash":
            self.vendorBankCombo.setCurrentIndex(0)

        # Instrument number required for bankish
        inst_req = method in BANKISH_METHODS
        self._set_required_label(self.instrumentNoEdit, inst_req)

        # For Cash: instrument type should be 'other'; no banks
        if method == "Cash":
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index("other"))

    # ------------------------- Validation -------------------------
    def _validate_live(self) -> None:
        ok, msg = self._validate()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate(self) -> tuple[bool, Optional[str]]:
        # Amount present (float)
        amt = self._amount_value()
        if amt is None:
            return False, _t("Please enter a valid amount (e.g., 1000.00 or -250.00).")

        # Method present
        method = self.methodCombo.currentText()
        if method not in METHODS:
            return False, _t("Payment method is not supported.")

        bank_id = self._current_company_bank_id()
        vendor_bank_id = self._current_vendor_bank_id()
        instype = self.instrumentTypeCombo.currentText()
        instno = self.instrumentNoEdit.text().strip()

        # Per-method rules
        if method == "Bank Transfer":
            if bank_id is None:
                return False, _t("Company bank account is required for Bank Transfer.")
            if not instno:
                return False, _t("Instrument/reference number is required for Bank Transfer.")
            if instype != "online":
                return False, _t("Instrument type must be 'online' for Bank Transfer.")
            if amt > 0 and vendor_bank_id is None:
                return False, _t("Vendor bank account is required for outgoing Bank Transfer.")
        elif method == "Cheque":
            if bank_id is None:
                return False, _t("Company bank account is required for Cheque.")
            if not instno:
                return False, _t("Cheque number is required for Cheque.")
            if instype != "cross_cheque":
                return False, _t("Instrument type must be 'cross_cheque' for Cheque.")
            if amt > 0 and vendor_bank_id is None:
                return False, _t("Vendor bank account is required for outgoing Cheque.")
        elif method == "Cash Deposit":
            if not instno:
                return False, _t("Deposit slip/reference number is required for Cash Deposit.")
            if instype != "cash_deposit":
                return False, _t("Instrument type must be 'cash_deposit' for Cash Deposit.")
            if amt > 0 and vendor_bank_id is None:
                return False, _t("Vendor bank account is required for outgoing Cash Deposit.")
            # Company bank optional here
        elif method == "Cash":
            if bank_id is not None or vendor_bank_id is not None:
                return False, _t("Cash payments must not reference any bank accounts.")
            if instype not in (None, "other"):
                return False, _t("Instrument type for Cash must be 'other'.")
        else:
            # Card / Other — no special requirements beyond general ones
            pass

        # Clearing state/date consistency
        state = self.clearingStateCombo.currentText()
        if state == "cleared":
            if not self._has_date(self.clearedDateEdit):
                return False, _t("Please select a Cleared Date for cleared payments.")

        # Date field format if provided
        if not self.noDateCheck.isChecked():
            s = self.dateEdit.date().toString("yyyy-MM-dd")
            if len(s) != 10:
                return False, _t("Please enter the Date in YYYY-MM-DD.")

        return True, None

    # ------------------------- Save / Cancel -------------------------
    def _on_save(self) -> None:
        ok, msg = self._validate()
        if not ok:
            self.errorLabel.setText(msg or "")
            QMessageBox.warning(self, _t("Payment not recorded"), msg or _t("Please correct the highlighted fields."))
            return
        self._payload = self._build_payload()
        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    # ------------------------- Helpers -------------------------
    def _amount_value(self) -> Optional[float]:
        txt = (self.amountEdit.text() or "").strip()
        if txt in ("", ".", "-", "+"):
            return None
        try:
            return float(txt)
        except Exception:
            return None

    def _current_company_bank_id(self) -> Optional[int]:
        data = self.companyBankCombo.currentData()
        return int(data) if isinstance(data, int) else None

    def _current_vendor_bank_id(self) -> Optional[int]:
        data = self.vendorBankCombo.currentData()
        return int(data) if isinstance(data, int) else None

    def _set_required_label(self, widget: QWidget, required: bool) -> None:
        label = self._label_map.get(widget)
        if not label:
            return
        base = label.text().rstrip(" *")
        label.setText(base + (" *" if required else ""))

    def _set_date_from_str(self, edit: QDateEdit, s: str) -> None:
        try:
            y, m, d = map(int, s.split("-"))
            edit.setDate(QDate(y, m, d))
        except Exception:
            pass

    def _has_date(self, edit: QDateEdit) -> bool:
        # Using QDateEdit always yields a date; presence means enabled
        return edit.isEnabled()

    # ------------------------- Build payload -------------------------
    def _build_payload(self) -> dict:
        def date_or_none(edit: QDateEdit) -> Optional[str]:
            return edit.date().toString("yyyy-MM-dd") if edit.isEnabled() else None

        payload = {
            "amount": float(self._amount_value() or 0.0),
            "method": self.methodCombo.currentText(),
            "date": (None if self.noDateCheck.isChecked() else self.dateEdit.date().toString("yyyy-MM-dd")),
            "bank_account_id": self._current_company_bank_id(),
            "vendor_bank_account_id": self._current_vendor_bank_id(),
            "instrument_type": (self.instrumentTypeCombo.currentText() or None),
            "instrument_no": (self.instrumentNoEdit.text().strip() or None),
            "instrument_date": date_or_none(self.instrumentDateEdit),
            "deposited_date": date_or_none(self.depositedDateEdit),
            "cleared_date": (self.clearedDateEdit.date().toString("yyyy-MM-dd") if self.clearedDateEdit.isEnabled() else None),
            "clearing_state": (self.clearingStateCombo.currentText() or None),
            "ref_no": (self.refNoEdit.text().strip() or None),
            "notes": (self.notesEdit.toPlainText().strip() or None),
        }
        return payload
