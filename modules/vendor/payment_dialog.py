from __future__ import annotations

from typing import Callable, Optional, Literal

try:
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
except Exception:
    raise


def _t(s: str) -> str:
    return s


METHODS = [
    "Cash",
    "Bank Transfer",
    "Cheque",
    "Cross Cheque",
    "Cash Deposit",
    "Other",
]

INSTRUMENT_TYPES = [
    "online",
    "cheque",
    "cross_cheque",
    "cash_deposit",
    "pay_order",
    "other",
]

CLEARING_STATES = ["posted", "pending", "cleared", "bounced"]

METHOD_TO_FORCED_INSTRUMENT = {
    "Cash": "other",
    "Bank Transfer": "online",
    "Cheque": "cheque",
    "Cross Cheque": "cross_cheque",
    "Cash Deposit": "cash_deposit",
    "Other": "other",
}
METHOD_TO_DEFAULT_CLEARING = {
    "Cash": "cleared",
    "Bank Transfer": "cleared",
    "Cheque": "pending",
    "Cross Cheque": "pending",
    "Cash Deposit": "pending",
    "Other": "cleared",
}

METHODS_REQUIRE_BANK = {"Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit"}
METHODS_REQUIRE_INSTR_NO = {"Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit"}


def open_vendor_money_form(
    *,
    mode: Literal["payment", "advance", "apply_advance"],
    vendor_id: int,
    purchase_id: Optional[str] = None,
    defaults: dict | None = None,
) -> dict | None:
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


class _VendorMoneyDialog(QDialog):
    PAGE_PAYMENT = 0
    PAGE_ADVANCE = 1
    PAGE_APPLY = 2

    def __init__(self, *, mode: str, vendor_id: int, purchase_id: Optional[str], defaults: dict) -> None:
        super().__init__(None)
        self.setWindowTitle(_t("Vendor Money"))
        self.setModal(True)

        self._payload: Optional[dict] = None
        self._vendor_id = int(vendor_id)
        self._locked_purchase_id = str(purchase_id) if purchase_id is not None else None
        self._defaults = defaults or {}

        self._list_company_bank_accounts: Optional[Callable[[], list]] = self._defaults.get("list_company_bank_accounts")
        self._list_vendor_bank_accounts: Optional[Callable[[int], list]] = self._defaults.get("list_vendor_bank_accounts")
        self._list_open_purchases_for_vendor: Optional[Callable[[int], list]] = self._defaults.get("list_open_purchases_for_vendor")
        self._today: Optional[Callable[[], str]] = self._defaults.get("today")

        self._submit_payment: Optional[Callable[[dict], None]] = self._defaults.get("submit_payment")
        self._submit_advance: Optional[Callable[[dict], None]] = self._defaults.get("submit_advance")
        self._submit_apply: Optional[Callable[[dict], None]] = self._defaults.get("submit_apply")

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
        self._prefill_temp_bank_name: Optional[str] = self._defaults.get("temp_vendor_bank_name")
        self._prefill_temp_bank_number: Optional[str] = self._defaults.get("temp_vendor_bank_number")

        self._build_ui()

        initial = {
            "payment": self.PAGE_PAYMENT,
            "advance": self.PAGE_ADVANCE,
            "apply_advance": self.PAGE_APPLY,
        }.get(mode, self.PAGE_PAYMENT)
        self.pageStack.setCurrentIndex(initial)
        self.tabBar.setCurrentIndex(initial)
        self._sync_window_title()

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

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        self.tabBar = QTabBar()
        self.tabBar.addTab(_t("Payment"))
        self.tabBar.addTab(_t("Record Advance"))
        self.tabBar.addTab(_t("Apply Advance"))
        self.tabBar.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabBar)

        self.pageStack = QStackedWidget()
        outer.addWidget(self.pageStack, 1)

        self.page_payment = QWidget()
        self._build_payment_page(self.page_payment)
        self.pageStack.addWidget(self.page_payment)

        self.page_advance = QWidget()
        self._build_advance_page(self.page_advance)
        self.pageStack.addWidget(self.page_advance)

        self.page_apply = QWidget()
        self._build_apply_page(self.page_apply)
        self.pageStack.addWidget(self.page_apply)

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

        # Vendor bank (for reconciliation/reference)
        self.vendorBankCombo = QComboBox()
        self.vendorBankCombo.addItem("", None)  # blank
        lbl_vbank = QLabel(_t("Vendor Bank"))
        lbl_vbank.setBuddy(self.vendorBankCombo)
        form.addRow(lbl_vbank, self.vendorBankCombo)
        
        # Temporary external bank account fields (appear when "Temporary Account" is selected)
        self.tempBankNameEdit = QLineEdit()
        self.tempBankNameEdit.setPlaceholderText("Bank Name")
        lbl_temp_name = QLabel(_t("Temp Bank Name"))
        lbl_temp_name.setBuddy(self.tempBankNameEdit)
        form.addRow(lbl_temp_name, self.tempBankNameEdit)
        
        self.tempBankNumberEdit = QLineEdit()
        self.tempBankNumberEdit.setPlaceholderText("Account Number")  
        lbl_temp_number = QLabel(_t("Temp Bank Number"))
        lbl_temp_number.setBuddy(self.tempBankNumberEdit)
        form.addRow(lbl_temp_number, self.tempBankNumberEdit)
        
        # Hide temporary bank fields by default
        self.tempBankNameEdit.setVisible(False)
        self.tempBankNumberEdit.setVisible(False)
        lbl_temp_name.setVisible(False)
        lbl_temp_number.setVisible(False)

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

        # Clearing state (hidden from UI, default to 'cleared' for immediate methods)
        self.clearingStateCombo = QComboBox()
        for s in CLEARING_STATES:
            self.clearingStateCombo.addItem(s)
        # Set default value to 'cleared' for Cash method and hide the field
        self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index("cleared"))
        # Add the field to the form but hide it
        clear_state_label = QLabel(_t("Clearing State"))
        clear_state_label.setVisible(False)  # Hide the label
        self.clearingStateCombo.setVisible(False)  # Hide the combo box
        form.addRow(clear_state_label, self.clearingStateCombo)

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
            self.vendorBankCombo: lbl_vbank,
            self.instrumentNoEdit: lbl_insno,
            self.amountEdit: lbl_amount,
        }
        
        # Track temporary bank labels as well
        self.temp_bank_name_label = lbl_temp_name
        self.temp_bank_number_label = lbl_temp_number
        
        # Store original label texts to avoid corruption during asterisk manipulation
        self._orig_temp_bank_name_label_text = lbl_temp_name.text()
        self._orig_temp_bank_number_label_text = lbl_temp_number.text()

        # Wire
        self.purchasePicker.currentIndexChanged.connect(self._update_remaining)
        self.purchasePicker.currentIndexChanged.connect(self._apply_payment_amount_limits)
        self.methodCombo.currentIndexChanged.connect(self._on_method_changed)
        self.vendorBankCombo.currentIndexChanged.connect(self._on_vendor_bank_account_changed)
        self.clearingStateCombo.currentIndexChanged.connect(self._on_clearing_changed)
        self.amountEdit.valueChanged.connect(self._validate_live_payment)
        self.companyBankCombo.currentIndexChanged.connect(self._validate_live_payment)
        self.instrumentNoEdit.textChanged.connect(self._validate_live_payment)
        self.tempBankNameEdit.textChanged.connect(self._validate_live_payment)
        self.tempBankNumberEdit.textChanged.connect(self._validate_live_payment)
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
        self.applyPurchasePicker.currentIndexChanged.connect(self._apply_apply_amount_limits)
        self.applyAmountEdit.valueChanged.connect(self._validate_live_apply)

    # ---------- Tab events ----------
    def _on_tab_changed(self, idx: int) -> None:
        self.pageStack.setCurrentIndex(idx)
        self._sync_window_title()
        self._update_hint()
        self._validate_live_payment()
        self._validate_live_advance()
        self._validate_live_apply()
        # Re-apply limits in case user switched tabs
        if idx == self.PAGE_PAYMENT:
            self._apply_payment_amount_limits()
        elif idx == self.PAGE_APPLY:
            self._apply_apply_amount_limits()

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
            self._apply_payment_amount_limits()

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
            self._apply_apply_amount_limits()

    def _load_company_banks(self) -> None:
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
        current_text = self.vendorBankCombo.currentText()
        
        self.vendorBankCombo.clear()
        self.vendorBankCombo.addItem("", None)
        rows: list[dict] = []
        
        # Try to load vendor bank accounts using the provided function
        if self._list_vendor_bank_accounts:
            try:
                rows = list(self._list_vendor_bank_accounts(self._vendor_id))
            except Exception as e:
                # Log the error but allow loading to continue with available data
                import logging
                logging.error(f"Error loading vendor bank accounts for vendor {self._vendor_id}: {e}")
                # Provide user feedback about the issue
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, _t("Bank Accounts"), _t("Could not load vendor bank accounts. Using basic options only."))
                rows = []
        else:
            # If no function provided, log a warning and use empty rows
            import logging
            logging.warning("No list_vendor_bank_accounts function provided, vendor bank accounts will not be loaded")
            rows = []
        
        for a in rows:
            try:
                vid = int(a.get("id"))
            except Exception:
                vid = a.get("id")
            self.vendorBankCombo.addItem(str(a.get("name", "")), vid)
        
        self.vendorBankCombo.addItem(_t("Temporary/External Bank Account"), "TEMP_BANK")
        
        previous_selection_restored = False
        if current_text and current_text != "":
            index = self.vendorBankCombo.findText(current_text)
            if index >= 0:
                self.vendorBankCombo.setCurrentIndex(index)
                previous_selection_restored = True

        if self._prefill_vendor_bank_id is not None:
            for i in range(self.vendorBankCombo.count()):
                if self.vendorBankCombo.itemData(i) == self._prefill_vendor_bank_id:
                    self.vendorBankCombo.setCurrentIndex(i)
                    previous_selection_restored = True
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

        if self._prefill_temp_bank_name:
            self.tempBankNameEdit.setText(str(self._prefill_temp_bank_name))
            
        if self._prefill_temp_bank_number:
            self.tempBankNumberEdit.setText(str(self._prefill_temp_bank_number))

    # ---------- Signals / UX (payment) ----------
    def _on_method_changed(self) -> None:
        method = self.methodCombo.currentText()

        # Default clearing state
        default_clear = METHOD_TO_DEFAULT_CLEARING.get(method, "posted")
        if default_clear in CLEARING_STATES:
            self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index(default_clear))

        # Bank requirement (company)
        needs_bank = method in METHODS_REQUIRE_BANK
        # For "Other" method, enable bank accounts but don't require them
        if method == "Other":
            self.companyBankCombo.setEnabled(True)
            self._set_required_label(self.companyBankCombo, False)  # Not required
        else:
            self.companyBankCombo.setEnabled(needs_bank)
            self._set_required_label(self.companyBankCombo, needs_bank)
        
        if method == "Cash":
            self.companyBankCombo.setCurrentIndex(0)  # blank

        # Bank requirement (vendor)
        needs_vendor_bank = method in METHODS_REQUIRE_BANK
        # For "Other" method, enable vendor bank account but don't require it
        if method == "Other":
            self.vendorBankCombo.setEnabled(True)
            self._set_required_label(self.vendorBankCombo, False)  # Not required
        else:
            # Only enable vendor bank for methods that require it
            enable_vendor = needs_vendor_bank and method != "Cheque"  # Cheque doesn't require vendor bank
            self.vendorBankCombo.setEnabled(enable_vendor)
            self._set_required_label(self.vendorBankCombo, enable_vendor)
            
            # If switching to Cheque method, clear any temporary account selection
            if method == "Cheque":
                if self.vendorBankCombo.currentData() == "TEMP_BANK":
                    self.vendorBankCombo.setCurrentIndex(0)  # Select the blank option

        # Instrument number required?
        req_inst = method in METHODS_REQUIRE_INSTR_NO
        # For "Other" method, instrument is not required
        if method == "Other":
            self._set_required_label(self.instrumentNoEdit, False)
        elif method == "Cash":
            # For Cash method, disable instrument fields completely
            self.instrumentNoEdit.setEnabled(False)
            self.instrumentDateEdit.setEnabled(False)
            self._set_required_label(self.instrumentNoEdit, False)
        else:
            self.instrumentNoEdit.setEnabled(req_inst)
            self.instrumentDateEdit.setEnabled(req_inst)
            self._set_required_label(self.instrumentNoEdit, req_inst)

        # UX focus
        if needs_bank:
            self.companyBankCombo.setFocus()
        elif req_inst and method != "Cash":
            self.instrumentNoEdit.setFocus()
        else:
            self.amountEdit.setFocus()

        # Update limits & validations
        self._apply_payment_amount_limits()
        self._update_hint()
        self._validate_live_payment()
        # Update temporary bank field visibility after method change
        self._update_temp_bank_visibility()

    def _on_clearing_changed(self) -> None:
        state = self.clearingStateCombo.currentText()
        enable_cd = state == "cleared"
        self.clearedDateEdit.setEnabled(enable_cd)
        if not enable_cd:
            self._clear_date(self.clearedDateEdit)
        self._validate_live_payment()

    def _on_vendor_bank_account_changed(self):
        """Show/hide temporary bank fields based on selection"""
        self._update_temp_bank_visibility()

    def _get_instrument_type_for_method(self, method: str) -> Optional[str]:
        """Derive instrument type from payment method using the established METHOD_TO_FORCED_INSTRUMENT mapping."""
        # Use the existing constant as the single source of truth
        return METHOD_TO_FORCED_INSTRUMENT.get(method, "other")

    def _update_temp_bank_visibility(self):
        """
        Helper method to update temporary bank field visibility and styling.
        """
        selected_value = self.vendorBankCombo.currentData()
        is_temp_account = selected_value == "TEMP_BANK"
        
        # Check if current method requires a vendor bank account
        # Note: "Cheque" doesn't require vendor bank (only outgoing company bank)
        method = self.methodCombo.currentText()
        need_vendor = method in METHODS_REQUIRE_BANK and method != "Cheque"
        
        # Update required indicators based on whether method requires vendor bank
        temp_name_label = getattr(self, 'temp_bank_name_label', None)
        temp_number_label = getattr(self, 'temp_bank_number_label', None)
        
        should_be_required = is_temp_account and need_vendor
        self._set_required_label(temp_name_label, should_be_required, '_orig_temp_bank_name_label_text')
        self._set_required_label(temp_number_label, should_be_required, '_orig_temp_bank_number_label_text')
        
        # Show temp fields whenever temp account is selected (for reference/reconciliation)
        self.tempBankNameEdit.setVisible(is_temp_account)
        self.tempBankNumberEdit.setVisible(is_temp_account)
        if temp_name_label:
            temp_name_label.setVisible(is_temp_account)
        if temp_number_label:
            temp_number_label.setVisible(is_temp_account)
        
        # Trigger validation since required fields may have changed
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
            self.purchaseRemainingLabel.setText(_t(f"Remaining: {rem:.2f}"))
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

    # ---------- Amount limit helpers ----------
    def _remaining_from_data(self, data: Optional[dict]) -> float:
        if not isinstance(data, dict):
            return 0.0
        try:
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            rem = total - paid
            return max(0.0, rem)
        except Exception:
            return 0.0

    def _apply_payment_amount_limits(self) -> None:
        data = self.purchasePicker.currentData()
        remaining = self._remaining_from_data(data)
        method = self.methodCombo.currentText()
        if method == "Cash":
            self.amountEdit.setRange(-1_000_000_000.0, max(0.0, remaining))
        else:
            self.amountEdit.setRange(0.0, max(0.0, remaining))

    def _apply_apply_amount_limits(self) -> None:
        data = self.applyPurchasePicker.currentData()
        remaining = self._remaining_from_data(data)
        self.applyAmountEdit.setRange(0.0, max(0.0, remaining))

    def _validate_live_payment(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_PAYMENT:
            return
        ok, msg = self._validate_payment()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_payment(self) -> tuple[bool, Optional[str]]:
        p = self.purchasePicker.currentData()
        if not isinstance(p, dict) or not str(p.get("purchase_id", "")):
            return False, _t("Please select a purchase for this payment.")

        method = self.methodCombo.currentText()
        if method not in METHODS:
            return False, _t("Payment method is not supported.")

        amount = float(self.amountEdit.value())
        if abs(amount) < 1e-9:
            return False, _t("Amount cannot be zero.")
        if amount < 0 and method != "Cash":
            return False, _t("Refunds (negative amounts) are only allowed with the Cash method.")

        cbank_id = self._current_company_bank_id()
        if method == "Cash":
            if cbank_id is not None:
                return False, _t("Company bank must be empty when method is Cash.")
        elif method in METHODS_REQUIRE_BANK and cbank_id is None:
            return False, _t("Company bank account is required for this method.")
        # For "Other" method, company bank is optional, so no validation needed

        inst_no = self.instrumentNoEdit.text().strip()
        if method in METHODS_REQUIRE_INSTR_NO and not inst_no:
            return False, _t("Please enter instrument/reference number.")
        # For "Other" method, instrument is optional, so no validation needed

        selected_vendor_account = self.vendorBankCombo.currentData()
        is_temp_account = selected_vendor_account == "TEMP_BANK"
        need_vendor = method in METHODS_REQUIRE_BANK
        # For "Other" method, temporary bank validation only applies if a temporary account is selected AND a vendor bank is required
        if is_temp_account and need_vendor:
            temp_bank_name = self.tempBankNameEdit.text().strip()
            temp_bank_number = self.tempBankNumberEdit.text().strip()
            if not temp_bank_name:
                return False, _t("For temporary account, please enter bank name.")
            if not temp_bank_number:
                return False, _t("For temporary account, please enter account number.")

        state = self.clearingStateCombo.currentText()
        if state == "cleared":
            if not self._has_date(self.clearedDateEdit):
                return False, _t("Please select a cleared date.")



        remaining = self._remaining_from_data(p)
        if method != "Cash" and amount - remaining > 1e-9:
            return False, _t("Amount exceeds remaining due for the selected purchase.")

        return True, None

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
        cb: Optional[Callable[[dict], None]] = None

        if idx == self.PAGE_PAYMENT:
            ok, msg = self._validate_payment()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_payment()
            cb = self._submit_payment
        elif idx == self.PAGE_ADVANCE:
            ok, msg = self._validate_advance()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_advance()
            cb = self._submit_advance
        elif idx == self.PAGE_APPLY:
            ok, msg = self._validate_apply()
            if not ok:
                self._warn(msg)
                return
            self._payload = self._build_payload_apply()
            cb = self._submit_apply

        # If submit callback provided, use it to persist and surface any DB constraint errors.
        if callable(cb):
            try:
                cb(self._payload or {})
            except Exception as e:
                self._handle_submit_error(e)
                self._payload = None
                return

        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    # ---------- Helpers ----------
    def _warn(self, msg: Optional[str]) -> None:
        """
        Show an error message in the error label.
        
        Modal dialogs are now only for critical errors that require immediate attention.
        """
        self.errorLabel.setText(msg or "")
        # For this specific dialog, keep using QMessageBox for consistency with the existing approach
        QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))

    def _handle_submit_error(self, exc: Exception) -> None:
        # Show a friendly message but preserve the DB-provided detail if available
        message = str(exc).strip() or _t("A database rule prevented saving.")
        # Common cases (best-effort string match without importing domain exceptions)
        lowered = message.lower()
        if "cannot apply credit beyond remaining due" in lowered:
            message = _t("Amount exceeds remaining due for the selected purchase.")
        elif "insufficient vendor credit" in lowered:
            message = _t("Insufficient vendor credit to apply.")
        elif "payments cannot be recorded against quotations" in lowered:
            message = _t("Payments cannot be recorded against quotations.")
        self._warn(message)

    def _current_company_bank_id(self) -> Optional[int]:
        data = self.companyBankCombo.currentData()
        return int(data) if isinstance(data, int) else None

    def _current_vendor_bank_id(self) -> Optional[int | str]:
        data = self.vendorBankCombo.currentData()
        # vendor bank may not always be int-typed (e.g., "TEMP_BANK")
        try:
            return int(data)
        except Exception:
            return data if data is not None else None

    def _set_required_label(self, widget_or_label, required: bool, original_attr: str = None) -> None:
        """
        Set a label as required (with asterisk and styling) or normal.
        
        Args:
            widget_or_label: Either a widget from _label_map or a direct label reference
            required: True to make the label required, False to make it normal
            original_attr: Optional attribute name to get original text (for temporary labels)
        """
        # First check if widget_or_label is a key in _label_map (an actual mapped widget)
        if hasattr(self, "_label_map") and widget_or_label in (getattr(self, "_label_map") or {}):
            # It's a widget that maps to a label
            label = self._label_map.get(widget_or_label)
        else:
            # It's a direct label reference
            label = widget_or_label
            
        if not label:
            return
            
        if original_attr:
            # For temporary bank labels, use stored original text
            original_text = getattr(self, original_attr, label.text().rstrip(" *"))
            if required:
                if not label.text().endswith('*'):
                    label.setText(original_text + "*")
                label.setStyleSheet("color: red; font-weight: bold;")
            else:
                label.setText(original_text)
                label.setStyleSheet("")
        else:
            # For regular labels, use simple asterisk approach
            base = label.text().rstrip(" *")
            label.setText(base + (" *" if required else ""))
            # Clear the stylesheet when not required to remove any previous required styling
            if not required:
                label.setStyleSheet("")

    def _set_date_from_str(self, edit: QDateEdit, s: str) -> None:
        try:
            parts = s.split("-")
            if len(parts) != 3:
                import logging
                logging.warning(f"Invalid date format: {s}. Expected YYYY-MM-DD.")
                return  # Invalid format (not YYYY-MM-DD)
            y, m, d = map(int, parts)
            # QDate constructor will validate the date values
            date_obj = QDate(y, m, d)
            if not date_obj.isValid():
                import logging
                logging.warning(f"Invalid date values: {s}. Date not valid in QDate.")
                return  # Invalid date (e.g., Feb 30)
            edit.setDate(date_obj)
        except ValueError:
            # Raised when s.split("-") doesn't have 3 parts that can be converted to int
            import logging
            logging.error(f"Error parsing date string: {s}")
            pass

    def _has_date(self, edit: QDateEdit) -> bool:
        return edit.date().isValid() and edit.date() != QDate()

    def _clear_date(self, edit: QDateEdit) -> None:
        edit.setDate(QDate())

    def _build_payload_payment(self) -> dict:
        pdata = self.purchasePicker.currentData() or {}

        def date_or_none(edit: QDateEdit) -> Optional[str]:
            return edit.date().toString("yyyy-MM-dd") if edit.date().isValid() else None

        selected_vendor_account = self.vendorBankCombo.currentData()
        is_temp_account = selected_vendor_account == "TEMP_BANK"
        
        # Derive instrument type from method like in PO window
        method = self.methodCombo.currentText()
        instrument_type = self._get_instrument_type_for_method(method)
        
        payload = {
            "purchase_id": str(pdata.get("purchase_id")),
            "amount": float(self.amountEdit.value()),
            "method": method,
            "date": self.dateEdit.date().toString("yyyy-MM-dd"),
            "bank_account_id": self._current_company_bank_id(),
            "vendor_bank_account_id": self._current_vendor_bank_id() if not is_temp_account else None,
            "instrument_type": instrument_type,
            "instrument_no": (self.instrumentNoEdit.text().strip() or None),
            "instrument_date": date_or_none(self.instrumentDateEdit),
            "deposited_date": date_or_none(self.depositedDateEdit),
            "clearing_state": self.clearingStateCombo.currentText() or None,
            "cleared_date": date_or_none(self.clearedDateEdit),
            "notes": (self.notesEdit.toPlainText().strip() or None),
            "created_by": (int(self.createdByEdit.text()) if self.createdByEdit.text().strip() else None),
            "temp_vendor_bank_name": self.tempBankNameEdit.text().strip() or None if is_temp_account else None,
            "temp_vendor_bank_number": self.tempBankNumberEdit.text().strip() or None if is_temp_account else None,
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
