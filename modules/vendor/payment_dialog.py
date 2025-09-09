# inventory_management/modules/vendor/payment_dialog.py
from __future__ import annotations

from typing import Callable, Optional, Literal

try:
    # Project standard: PySide6
    from PySide6.QtCore import Qt, QDate
    from PySide6.QtGui import QIntValidator, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDateEdit,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
        QStackedWidget,
        QTabBar,
    )
except Exception:  # pragma: no cover
    raise


# -----------------------------
# i18n shim
# -----------------------------
def _t(s: str) -> str:
    return s


# -----------------------------
# Canonical constants & matrices
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

METHOD_TO_FORCED_INSTRUMENT = {
    "Cash": "other",
    "Bank Transfer": "online",
    "Card": "other",
    "Cheque": "cross_cheque",
    "Cash Deposit": "cash_deposit",
    "Other": "other",
}

METHOD_TO_DEFAULT_CLEARING = {
    "Cash": "posted",
    "Bank Transfer": "posted",
    "Card": "posted",
    "Cheque": "pending",
    "Cash Deposit": "pending",
    "Other": "posted",
}

METHODS_REQUIRE_BANK = {"Bank Transfer", "Cheque", "Cash Deposit"}
METHODS_REQUIRE_INSTR_NO = {"Bank Transfer", "Cheque", "Cash Deposit"}


# -----------------------------
# Public API
# -----------------------------
def open_vendor_money_form(
    *,
    mode: Literal["payment", "advance", "apply_advance"],
    vendor_id: int,
    purchase_id: Optional[str] = None,
    defaults: dict | None = None,
) -> dict | None:
    """
    Unified money-out dialog for vendors with three modes:
      - "payment": capture vendor payment/refund → payload for PurchasePaymentsRepo.record_payment(...)
      - "advance": record vendor advance (prepayment) → payload for VendorAdvancesRepo.grant_credit(...)
      - "apply_advance": apply advance to a purchase → payload for VendorAdvancesRepo.apply_credit_to_purchase(...)
    """
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    dlg = _VendorMoneyDialog(mode=mode, vendor_id=int(vendor_id), purchase_id=purchase_id, defaults=defaults or {})
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None

    if owns_app:
        app.quit()
    return payload


# -----------------------------
# Dialog implementation
# -----------------------------
class _VendorMoneyDialog(QDialog):
    """
    One dialog with three pages:
      - Payment (enforces bank/instrument/clearing rules)
      - Record Advance
      - Apply Advance
    Produces repo-shaped payloads.
    """

    PAGE_PAYMENT = 0
    PAGE_ADVANCE = 1
    PAGE_APPLY = 2

    def __init__(self, *, mode: str, vendor_id: int, purchase_id: Optional[str], defaults: dict) -> None:
        super().__init__(None)
        self.setWindowTitle(_t("Vendor Money"))
        self.setModal(True)

        # Common state
        self._payload: Optional[dict] = None
        self._vendor_id = int(vendor_id)
        self._locked_purchase_id = str(purchase_id) if purchase_id is not None else None
        self._defaults = defaults or {}

        # Adapters (all optional)
        self._list_company_bank_accounts: Optional[Callable[[], list]] = self._defaults.get("list_company_bank_accounts")
        self._list_vendor_bank_accounts: Optional[Callable[[int], list]] = self._defaults.get("list_vendor_bank_accounts")
        self._list_open_purchases_for_vendor: Optional[Callable[[int], list]] = self._defaults.get("list_open_purchases_for_vendor")
        self._today: Optional[Callable[[], str]] = self._defaults.get("today")

        # Prefills (payment page)
        self._prefill_method: Optional[str] = self._defaults.get("method")
        self._prefill_amount: Optional[float] = self._defaults.get("amount")
        self._prefill_date: Optional[str] = self._defaults.get("date")
        self._prefill_company_bank_id: Optional[int] = self._defaults.get("bank_account_id")
        self._prefill_vendor_bank_id: Optional[int] = self._defaults.get("vendor_bank_account_id")
        self._prefill_instrument_type: Optional[str] = self._defaults.get("instrument_type")
        self._prefill_instrument_no: Optional[str] = self._defaults.get("instrument_no")
        self._prefill_instrument_date: Optional[str] = self._defaults.get("instrument_date")
        self._prefill_deposited_date: Optional[str] = self._defaults.get("deposited_date")
        self._prefill_clearing_state: Optional[str] = self._defaults.get("clearing_state")
        self._prefill_cleared_date: Optional[str] = self._defaults.get("cleared_date")
        self._prefill_notes: Optional[str] = self._defaults.get("notes")
        self._prefill_created_by: Optional[int] = self._defaults.get("created_by")
        self._vendor_display: Optional[str] = self._defaults.get("vendor_display")

        self._build_ui()

        initial = {
            "payment": self.PAGE_PAYMENT,
            "advance": self.PAGE_ADVANCE,
            "apply_advance": self.PAGE_APPLY,
        }.get(mode, self.PAGE_PAYMENT)
        self.pageStack.setCurrentIndex(initial)
        self.tabBar.setCurrentIndex(initial)
        self._sync_window_title()

        # Load data & prefills
        self._load_purchases()
        self._load_company_banks()
        self._load_vendor_banks()
        self._apply_prefills_payment()
        self._lock_purchase_if_needed()
        self._on_method_changed()
        self._update_hint()
        self._validate_live_payment()
        self._validate_live_advance()
        self._validate_live_apply()

    # ---------- Layout ----------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # Tabs + stacked pages
        self.tabBar = QTabBar()
        self.tabBar.addTab(_t("Payment"))
        self.tabBar.addTab(_t("Record Advance"))
        self.tabBar.addTab(_t("Apply Advance"))
        self.tabBar.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabBar)

        self.pageStack = QStackedWidget()
        outer.addWidget(self.pageStack, 1)

        # Payment page
        self.page_payment = QWidget()
        self._build_payment_page(self.page_payment)
        self.pageStack.addWidget(self.page_payment)

        # Record advance page
        self.page_advance = QWidget()
        self._build_advance_page(self.page_advance)
        self.pageStack.addWidget(self.page_advance)

        # Apply advance page
        self.page_apply = QWidget()
        self._build_apply_page(self.page_apply)
        self.pageStack.addWidget(self.page_apply)

        # Hint / Error / Buttons
        self.hintLabel = QLabel("")
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setStyleSheet("color:#666;")
        outer.addWidget(self.hintLabel)

        self.errorLabel = QLabel("")
        self.errorLabel.setStyleSheet("color:#b00020;")
        outer.addWidget(self.errorLabel)

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.saveBtn: QPushButton = self.buttonBox.button(QDialogButtonBox.Save)
        self.cancelBtn: QPushButton = self.buttonBox.button(QDialogButtonBox.Cancel)
        self.saveBtn.setDefault(True)
        self.saveBtn.setShortcut(QKeySequence("Alt+S"))
        self.cancelBtn.setShortcut(QKeySequence("Alt+C"))
        self.saveBtn.clicked.connect(self._on_save)
        self.cancelBtn.clicked.connect(self.reject)
        outer.addWidget(self.buttonBox)

    # ---------- Payment page ----------
    def _build_payment_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Purchase picker
        self.purchasePicker = QComboBox()
        self.purchaseRemainingLabel = QLabel("")
        row = QWidget()
        h = QHBoxLayout(row)
        h.addWidget(self.purchasePicker, 1)
        h.addWidget(self.purchaseRemainingLabel, 0, Qt.AlignRight)
        lbl_purchase = QLabel(_t("Purchase"))
        lbl_purchase.setBuddy(self.purchasePicker)
        form.addRow(lbl_purchase, row)

        # Vendor label
        self.vendorLabel = QLabel(_t("Vendor: ") + (str(self._vendor_display or self._vendor_id)))
        form.addRow(QLabel(""), self.vendorLabel)

        # Method
        self.methodCombo = QComboBox()
        for m in METHODS:
            self.methodCombo.addItem(m)
        form.addRow(QLabel(_t("Method")), self.methodCombo)

        # Amount
        self.amountEdit = QDoubleSpinBox()
        self.amountEdit.setDecimals(2)
        self.amountEdit.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.amountEdit.setSingleStep(1.0)
        lbl_amount = QLabel(_t("Amount"))
        lbl_amount.setBuddy(self.amountEdit)
        form.addRow(lbl_amount, self.amountEdit)

        # Date
        self.dateEdit = QDateEdit()
        self.dateEdit.setCalendarPopup(True)
        self.dateEdit.setDisplayFormat("yyyy-MM-dd")
        self.dateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Date")), self.dateEdit)

        # Company bank
        self.companyBankCombo = QComboBox()
        lbl_cbank = QLabel(_t("Company Bank"))
        lbl_cbank.setBuddy(self.companyBankCombo)
        form.addRow(lbl_cbank, self.companyBankCombo)

        # Vendor bank (optional; for reconciliation/reference)
        self.vendorBankCombo = QComboBox()
        self.vendorBankCombo.addItem("", None)  # blank
        lbl_vbank = QLabel(_t("Vendor Bank (optional)"))
        lbl_vbank.setBuddy(self.vendorBankCombo)
        form.addRow(lbl_vbank, self.vendorBankCombo)

        # Instrument type
        self.instrumentTypeCombo = QComboBox()
        for t in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.addItem(t)
        form.addRow(QLabel(_t("Instrument Type")), self.instrumentTypeCombo)

        # Instrument no
        self.instrumentNoEdit = QLineEdit()
        lbl_insno = QLabel(_t("Instrument No"))
        lbl_insno.setBuddy(self.instrumentNoEdit)
        form.addRow(lbl_insno, self.instrumentNoEdit)

        # Instrument date
        self.instrumentDateEdit = QDateEdit()
        self.instrumentDateEdit.setCalendarPopup(True)
        self.instrumentDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.instrumentDateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Instrument Date")), self.instrumentDateEdit)

        # Deposited date
        self.depositedDateEdit = QDateEdit()
        self.depositedDateEdit.setCalendarPopup(True)
        self.depositedDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.depositedDateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Deposited Date")), self.depositedDateEdit)

        # Clearing state
        self.clearingStateCombo = QComboBox()
        for s in CLEARING_STATES:
            self.clearingStateCombo.addItem(s)
        form.addRow(QLabel(_t("Clearing State")), self.clearingStateCombo)

        # Cleared date
        self.clearedDateEdit = QDateEdit()
        self.clearedDateEdit.setCalendarPopup(True)
        self.clearedDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.clearedDateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Cleared Date")), self.clearedDateEdit)

        # Notes / Created by
        self.notesEdit = QPlainTextEdit()
        self.notesEdit.setPlaceholderText(_t("Optional notes"))
        self.notesEdit.setFixedHeight(80)
        form.addRow(QLabel(_t("Notes")), self.notesEdit)

        self.createdByEdit = QLineEdit()
        self.createdByEdit.setValidator(QIntValidator())
        form.addRow(QLabel(_t("Created By")), self.createdByEdit)

        # Track labels for required asterisks
        self._label_map = {
            self.companyBankCombo: lbl_cbank,
            self.instrumentNoEdit: lbl_insno,
            self.amountEdit: lbl_amount,
        }

        # Wire
        self.purchasePicker.currentIndexChanged.connect(self._update_remaining)
        self.methodCombo.currentIndexChanged.connect(self._on_method_changed)
        self.clearingStateCombo.currentIndexChanged.connect(self._on_clearing_changed)
        self.amountEdit.valueChanged.connect(self._validate_live_payment)
        self.companyBankCombo.currentIndexChanged.connect(self._validate_live_payment)
        self.instrumentNoEdit.textChanged.connect(self._validate_live_payment)
        self.instrumentTypeCombo.currentIndexChanged.connect(self._validate_live_payment)
        self.clearedDateEdit.dateChanged.connect(self._validate_live_payment)

    # ---------- Record Advance page ----------
    def _build_advance_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Vendor label
        self.vendorLabel2 = QLabel(_t("Vendor: ") + (str(self._vendor_display or self._vendor_id)))
        form.addRow(QLabel(""), self.vendorLabel2)

        # Amount (>0)
        self.advAmountEdit = QDoubleSpinBox()
        self.advAmountEdit.setDecimals(2)
        self.advAmountEdit.setRange(0.0, 1_000_000_000.0)
        self.advAmountEdit.setSingleStep(1.0)
        form.addRow(QLabel(_t("Amount *")), self.advAmountEdit)

        # Date
        self.advDateEdit = QDateEdit()
        self.advDateEdit.setCalendarPopup(True)
        self.advDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.advDateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Date")), self.advDateEdit)

        # Notes / Created by
        self.advNotesEdit = QPlainTextEdit()
        self.advNotesEdit.setPlaceholderText(_t("Optional notes"))
        self.advNotesEdit.setFixedHeight(80)
        form.addRow(QLabel(_t("Notes")), self.advNotesEdit)

        self.advCreatedByEdit = QLineEdit()
        self.advCreatedByEdit.setValidator(QIntValidator())
        form.addRow(QLabel(_t("Created By")), self.advCreatedByEdit)

        # Wire
        self.advAmountEdit.valueChanged.connect(self._validate_live_advance)

    # ---------- Apply Advance page ----------
    def _build_apply_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Purchase picker (or preselected)
        self.applyPurchasePicker = QComboBox()
        lbl_purchase2 = QLabel(_t("Purchase *"))
        lbl_purchase2.setBuddy(self.applyPurchasePicker)
        form.addRow(lbl_purchase2, self.applyPurchasePicker)

        # Remaining due
        self.applyRemainingLabel = QLabel("")
        form.addRow(QLabel(_t("Remaining Due")), self.applyRemainingLabel)

        # Amount (>0)
        self.applyAmountEdit = QDoubleSpinBox()
        self.applyAmountEdit.setDecimals(2)
        self.applyAmountEdit.setRange(0.0, 1_000_000_000.0)
        self.applyAmountEdit.setSingleStep(1.0)
        form.addRow(QLabel(_t("Amount *")), self.applyAmountEdit)

        # Date
        self.applyDateEdit = QDateEdit()
        self.applyDateEdit.setCalendarPopup(True)
        self.applyDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.applyDateEdit.setDate(QDate.currentDate())
        form.addRow(QLabel(_t("Date")), self.applyDateEdit)

        # Notes / Created by
        self.applyNotesEdit = QPlainTextEdit()
        self.applyNotesEdit.setPlaceholderText(_t("Optional notes"))
        self.applyNotesEdit.setFixedHeight(80)
        form.addRow(QLabel(_t("Notes")), self.applyNotesEdit)

        self.applyCreatedByEdit = QLineEdit()
        self.applyCreatedByEdit.setValidator(QIntValidator())
        form.addRow(QLabel(_t("Created By")), self.applyCreatedByEdit)

        # Wire
        self.applyPurchasePicker.currentIndexChanged.connect(self._update_apply_remaining)
        self.applyAmountEdit.valueChanged.connect(self._validate_live_apply)

    # ---------- Tab events ----------
    def _on_tab_changed(self, idx: int) -> None:
        self.pageStack.setCurrentIndex(idx)
        self._sync_window_title()
        self._update_hint()
        self._validate_live_payment()
        self._validate_live_advance()
        self._validate_live_apply()

    def _sync_window_title(self) -> None:
        titles = {
            self.PAGE_PAYMENT: _t("Record Vendor Payment"),
            self.PAGE_ADVANCE: _t("Record Vendor Advance"),
            self.PAGE_APPLY: _t("Apply Vendor Advance to Purchase"),
        }
        self.setWindowTitle(titles.get(self.pageStack.currentIndex(), _t("Vendor Money")))

    # ---------- Data loaders ----------
    def _load_purchases(self) -> None:
        rows: list[dict] = []
        try:
            if self._list_open_purchases_for_vendor:
                rows = list(self._list_open_purchases_for_vendor(self._vendor_id))
        except Exception:
            rows = []

        # Payment picker
        if hasattr(self, "purchasePicker"):
            self.purchasePicker.clear()
            for r in rows:
                pid = str(r.get("purchase_id", ""))
                doc = str(r.get("doc_no", pid))
                date = str(r.get("date", ""))
                total = float(r.get("total", 0.0))
                paid = float(r.get("paid", 0.0))
                rem = total - paid
                self.purchasePicker.addItem(f"{doc} — {date} — Total {total:.2f} Paid {paid:.2f} Rem {rem:.2f}", r)
            self._update_remaining()

        # Apply picker
        if hasattr(self, "applyPurchasePicker"):
            self.applyPurchasePicker.clear()
            for r in rows:
                pid = str(r.get("purchase_id", ""))
                doc = str(r.get("doc_no", pid))
                date = str(r.get("date", ""))
                total = float(r.get("total", 0.0))
                paid = float(r.get("paid", 0.0))
                rem = total - paid
                self.applyPurchasePicker.addItem(f"{doc} — {date} — Total {total:.2f} Paid {paid:.2f} Rem {rem:.2f}", r)
            self._update_apply_remaining()

    def _load_company_banks(self) -> None:
        if not hasattr(self, "companyBankCombo"):
            return
        self.companyBankCombo.clear()
        self.companyBankCombo.addItem("", None)
        rows: list[dict] = []
        try:
            if self._list_company_bank_accounts:
                rows = list(self._list_company_bank_accounts())
        except Exception:
            rows = []
        for a in rows:
            self.companyBankCombo.addItem(str(a.get("name", "")), int(a.get("id")))

        # Preselect
        if self._prefill_company_bank_id is not None:
            for i in range(self.companyBankCombo.count()):
                if self.companyBankCombo.itemData(i) == self._prefill_company_bank_id:
                    self.companyBankCombo.setCurrentIndex(i)
                    break

    def _load_vendor_banks(self) -> None:
        if not hasattr(self, "vendorBankCombo"):
            return
        self.vendorBankCombo.clear()
        self.vendorBankCombo.addItem("", None)
        rows: list[dict] = []
        try:
            if self._list_vendor_bank_accounts:
                rows = list(self._list_vendor_bank_accounts(self._vendor_id))
        except Exception:
            rows = []
        for a in rows:
            # some adapters may not coerce id to int — try safely
            try:
                vid = int(a.get("id"))
            except Exception:
                vid = a.get("id")
            self.vendorBankCombo.addItem(str(a.get("name", "")), vid)

        # Preselect
        if self._prefill_vendor_bank_id is not None:
            for i in range(self.vendorBankCombo.count()):
                if self.vendorBankCombo.itemData(i) == self._prefill_vendor_bank_id:
                    self.vendorBankCombo.setCurrentIndex(i)
                    break

    def _lock_purchase_if_needed(self) -> None:
        if self._locked_purchase_id is None:
            return
        # Payment page
        for i in range(self.purchasePicker.count()):
            data = self.purchasePicker.itemData(i)
            if isinstance(data, dict) and str(data.get("purchase_id", "")) == self._locked_purchase_id:
                self.purchasePicker.setCurrentIndex(i)
                break
        else:
            placeholder = {"purchase_id": self._locked_purchase_id, "doc_no": self._locked_purchase_id, "date": "", "total": 0.0, "paid": 0.0}
            self.purchasePicker.addItem(self._locked_purchase_id, placeholder)
            self.purchasePicker.setCurrentIndex(self.purchasePicker.count() - 1)
        self.purchasePicker.setEnabled(False)

        # Apply page
        for i in range(self.applyPurchasePicker.count()):
            data = self.applyPurchasePicker.itemData(i)
            if isinstance(data, dict) and str(data.get("purchase_id", "")) == self._locked_purchase_id:
                self.applyPurchasePicker.setCurrentIndex(i)
                self.applyPurchasePicker.setEnabled(False)
                break

    # ---------- Prefills (payment page) ----------
    def _apply_prefills_payment(self) -> None:
        if self._prefill_method in METHODS:
            self.methodCombo.setCurrentIndex(METHODS.index(self._prefill_method))

        if isinstance(self._prefill_amount, (int, float)):
            self.amountEdit.setValue(float(self._prefill_amount))

        if self._prefill_date:
            self._set_date_from_str(self.dateEdit, self._prefill_date)
        elif self._today:
            self._set_date_from_str(self.dateEdit, self._today())

        if self._prefill_instrument_type in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index(self._prefill_instrument_type))

        if self._prefill_instrument_no:
            self.instrumentNoEdit.setText(str(self._prefill_instrument_no))

        if self._prefill_instrument_date:
            self._set_date_from_str(self.instrumentDateEdit, self._prefill_instrument_date)
        if self._prefill_deposited_date:
            self._set_date_from_str(self.depositedDateEdit, self._prefill_deposited_date)

        if self._prefill_clearing_state in CLEARING_STATES:
            self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index(self._prefill_clearing_state))

        if self._prefill_cleared_date:
            self._set_date_from_str(self.clearedDateEdit, self._prefill_cleared_date)

        if self._prefill_notes:
            self.notesEdit.setPlainText(str(self._prefill_notes))

        if self._prefill_created_by is not None:
            self.createdByEdit.setText(str(self._prefill_created_by))

    # ---------- Signals / UX (payment) ----------
    def _on_method_changed(self) -> None:
        method = self.methodCombo.currentText()

        # Force/default instrument type
        forced = METHOD_TO_FORCED_INSTRUMENT.get(method)
        if forced in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index(forced))

        # Default clearing state
        default_clear = METHOD_TO_DEFAULT_CLEARING.get(method, "posted")
        if default_clear in CLEARING_STATES:
            self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index(default_clear))

        # Bank requirement (company)
        needs_bank = method in METHODS_REQUIRE_BANK
        self.companyBankCombo.setEnabled(needs_bank)
        self._set_required_label(self.companyBankCombo, needs_bank)
        if method == "Cash":
            self.companyBankCombo.setCurrentIndex(0)  # blank

        # Instrument number required?
        req_inst = method in METHODS_REQUIRE_INSTR_NO
        self._set_required_label(self.instrumentNoEdit, req_inst)

        # UX focus
        if needs_bank:
            self.companyBankCombo.setFocus()
        elif req_inst:
            self.instrumentNoEdit.setFocus()
        else:
            self.amountEdit.setFocus()

        self._update_hint()
        self._validate_live_payment()

    def _on_clearing_changed(self) -> None:
        state = self.clearingStateCombo.currentText()
        enable_cd = state == "cleared"
        self.clearedDateEdit.setEnabled(enable_cd)
        if not enable_cd:
            self._clear_date(self.clearedDateEdit)
        self._validate_live_payment()

    def _update_hint(self) -> None:
        idx = self.pageStack.currentIndex()
        hint = ""
        if idx == self.PAGE_PAYMENT:
            method = self.methodCombo.currentText()
            if method == "Cash":
                hint = _t("Negative amounts allowed. Company bank must be blank. Instrument no optional.")
            elif method == "Bank Transfer":
                hint = _t("Outgoing only (>0). Company bank required. Instrument type 'online'. Instrument no required.")
            elif method == "Cheque":
                hint = _t("Outgoing only (>0). Company bank required. Type 'cross_cheque'. Cheque no required.")
            elif method == "Cash Deposit":
                hint = _t("Outgoing only (>0). Company bank required. Type 'cash_deposit'. Deposit slip no required.")
            elif method in ("Card", "Other"):
                hint = _t("Outgoing only (>0). Bank optional. Instrument no optional.")
        elif idx == self.PAGE_ADVANCE:
            hint = _t("Record a positive vendor advance (prepayment). No method or bank needed here.")
        elif idx == self.PAGE_APPLY:
            hint = _t("Apply available advance to an open purchase. Amount must not exceed vendor credit or remaining due.")
        self.hintLabel.setText(hint)

    def _update_remaining(self) -> None:
        data = self.purchasePicker.currentData()
        if isinstance(data, dict):
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            rem = total - paid
            self.purchaseRemainingLabel.setText(_t(f"Remaining: ${rem:.2f}"))
        else:
            self.purchaseRemainingLabel.setText("")

    # ---------- Apply page helpers ----------
    def _update_apply_remaining(self) -> None:
        data = self.applyPurchasePicker.currentData()
        if isinstance(data, dict):
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            rem = total - paid
            self.applyRemainingLabel.setText(f"{rem:.2f}")
        else:
            self.applyRemainingLabel.setText("")

    # ---------- Validation (payment) ----------
    def _validate_live_payment(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_PAYMENT:
            return
        ok, msg = self._validate_payment()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_payment(self) -> tuple[bool, Optional[str]]:
        # 1) Purchase present
        p = self.purchasePicker.currentData()
        if not isinstance(p, dict) or not str(p.get("purchase_id", "")):
            return False, _t("Please select a purchase for this payment.")

        # 2) Method supported
        method = self.methodCombo.currentText()
        if method not in METHODS:
            return False, _t("Payment method is not supported.")

        # 3) Amount sign/zero
        amount = float(self.amountEdit.value())
        if abs(amount) < 1e-9:
            return False, _t("Amount cannot be zero.")
        if amount < 0 and method != "Cash":
            return False, _t("Refunds (negative amounts) are only allowed with the Cash method.")

        # 4) Bank rules
        cbank_id = self._current_company_bank_id()
        if method == "Cash":
            if cbank_id is not None:
                return False, _t("Company bank must be empty when method is Cash.")
        elif method in METHODS_REQUIRE_BANK and cbank_id is None:
            return False, _t("Company bank account is required for this method.")

        # 5) Instrument type enforcement
        instype = self.instrumentTypeCombo.currentText()
        if instype not in INSTRUMENT_TYPES:
            return False, _t("Payment method is not supported.")
        forced = METHOD_TO_FORCED_INSTRUMENT.get(method)
        if method in ("Bank Transfer", "Cheque", "Cash Deposit") and instype != forced:
            if method == "Bank Transfer":
                return False, _t("Instrument type must be 'online' for Bank Transfer.")
            if method == "Cheque":
                return False, _t("Instrument type must be 'cross_cheque' for Cheque.")
            if method == "Cash Deposit":
                return False, _t("Instrument type must be 'cash_deposit' for Cash Deposit.")

        # 6) Instrument number requirement
        inst_no = self.instrumentNoEdit.text().strip()
        if method in METHODS_REQUIRE_INSTR_NO and not inst_no:
            return False, _t("Please enter instrument/reference number.")

        # 7) Clearing state & dates
        state = self.clearingStateCombo.currentText()
        if state == "cleared":
            if not self._has_date(self.clearedDateEdit):
                return False, _t("Please select a cleared date.")

        # 8) Date format safety
        for de in (self.dateEdit, self.instrumentDateEdit, self.depositedDateEdit, self.clearedDateEdit):
            if self._has_date(de):
                s = de.date().toString("yyyy-MM-dd")
                if len(s) != 10:
                    return False, _t("Please enter dates in YYYY-MM-DD.")

        return True, None

    # ---------- Validation (advance) ----------
    def _validate_live_advance(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_ADVANCE:
            return
        ok, msg = self._validate_advance()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_advance(self) -> tuple[bool, Optional[str]]:
        amt = float(self.advAmountEdit.value())
        if amt <= 0.0:
            return False, _t("Amount must be greater than zero.")
        return True, None

    # ---------- Validation (apply) ----------
    def _validate_live_apply(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_APPLY:
            return
        ok, msg = self._validate_apply()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_apply(self) -> tuple[bool, Optional[str]]:
        data = self.applyPurchasePicker.currentData()
        if not isinstance(data, dict) or not str(data.get("purchase_id", "")):
            return False, _t("Please select a purchase to apply the advance.")

        amt = float(self.applyAmountEdit.value())
        if amt <= 0.0:
            return False, _t("Amount must be greater than zero.")

        # Client-side bound against remaining due if present in picker rows
        try:
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            remaining = total - paid
            if amt - remaining > 1e-9:
                return False, _t("Amount exceeds remaining due for the selected purchase.")
        except Exception:
            pass

        return True, None

    # ---------- Save ----------
    def _on_save(self) -> None:
        idx = self.pageStack.currentIndex()
        if idx == self.PAGE_PAYMENT:
            ok, msg = self._validate_payment()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_payment()
        elif idx == self.PAGE_ADVANCE:
            ok, msg = self._validate_advance()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_advance()
        elif idx == self.PAGE_APPLY:
            ok, msg = self._validate_apply()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_apply()

        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    # ---------- Helpers ----------
    def _warn(self, msg: Optional[str]) -> None:
        self.errorLabel.setText(msg or "")
        QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))

    def _current_company_bank_id(self) -> Optional[int]:
        data = self.companyBankCombo.currentData()
        return int(data) if isinstance(data, int) else None

    def _current_vendor_bank_id(self) -> Optional[int]:
        data = self.vendorBankCombo.currentData()
        # vendor bank may not always be int-typed
        try:
            return int(data)
        except Exception:
            return data if data is not None else None

    def _set_required_label(self, widget: QWidget, required: bool) -> None:
        label = getattr(self, "_label_map", {}).get(widget)
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
        return True  # QDateEdit always has a date unless using special values

    def _clear_date(self, edit: QDateEdit) -> None:
        edit.setDate(QDate.currentDate())

    # ---------- Build payloads ----------
    def _build_payload_payment(self) -> dict:
        pdata = self.purchasePicker.currentData() or {}

        def date_or_none(edit: QDateEdit) -> Optional[str]:
            if edit.isEnabled():
                return edit.date().toString("yyyy-MM-dd")
            return None

        payload = {
            "purchase_id": str(pdata.get("purchase_id")),
            "amount": float(self.amountEdit.value()),
            "method": self.methodCombo.currentText(),
            "date": self.dateEdit.date().toString("yyyy-MM-dd"),
            "bank_account_id": self._current_company_bank_id(),
            "vendor_bank_account_id": self._current_vendor_bank_id(),
            "instrument_type": self.instrumentTypeCombo.currentText() or None,
            "instrument_no": (self.instrumentNoEdit.text().strip() or None),
            "instrument_date": date_or_none(self.instrumentDateEdit),
            "deposited_date": date_or_none(self.depositedDateEdit),
            "clearing_state": self.clearingStateCombo.currentText() or None,
            "cleared_date": (self.clearedDateEdit.date().toString("yyyy-MM-dd") if self.clearedDateEdit.isEnabled() else None),
            "notes": (self.notesEdit.toPlainText().strip() or None),
            "created_by": (int(self.createdByEdit.text()) if self.createdByEdit.text().strip() else None),
        }
        return payload

    def _build_payload_advance(self) -> dict:
        payload = {
            "vendor_id": self._vendor_id,
            "amount": float(self.advAmountEdit.value()),
            "date": self.advDateEdit.date().toString("yyyy-MM-dd"),
            "notes": (self.advNotesEdit.toPlainText().strip() or None),
            "created_by": (int(self.advCreatedByEdit.text()) if self.advCreatedByEdit.text().strip() else None),
        }
        return payload

    def _build_payload_apply(self) -> dict:
        pdata = self.applyPurchasePicker.currentData() or {}
        payload = {
            "vendor_id": self._vendor_id,
            "purchase_id": str(pdata.get("purchase_id")),
            "amount": float(self.applyAmountEdit.value()),
            "date": self.applyDateEdit.date().toString("yyyy-MM-dd"),
            "notes": (self.applyNotesEdit.toPlainText().strip() or None),
            "created_by": (int(self.applyCreatedByEdit.text()) if self.applyCreatedByEdit.text().strip() else None),
        }
        return payload
