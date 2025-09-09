# inventory_management/modules/customer/receipt_dialog.py
from __future__ import annotations

from typing import Callable, Optional, Literal

try:
    # Prefer PySide6 per project spec
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
# Public APIs
# -----------------------------
def open_payment_or_advance_form(
    *,
    mode: Literal["receipt", "advance", "apply_advance"],
    customer_id: int,
    sale_id: Optional[str] = None,
    defaults: dict | None = None,
) -> dict | None:
    """
    Unified money-in dialog for customers with three modes:
      - "receipt": capture sale payment → payload for SalePaymentsRepo.record_payment(...)
      - "advance": record customer advance → payload for CustomerAdvancesRepo.grant_credit(...)
      - "apply_advance": apply advance to a sale → payload for CustomerAdvancesRepo.apply_credit_to_sale(...)
    """
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    dlg = _CustomerMoneyDialog(mode=mode, customer_id=customer_id, sale_id=sale_id, defaults=defaults or {})
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None

    if owns_app:
        app.quit()
    return payload


def open_receipt_form(
    *,
    sale_id: str,
    customer_id: int,
    defaults: dict | None = None,
) -> dict | None:
    """
    Backward-compatible API for legacy callers.
    """
    return open_payment_or_advance_form(
        mode="receipt",
        customer_id=customer_id,
        sale_id=sale_id,
        defaults=defaults or {},
    )

# -----------------------------
# Dialog Implementation (3 pages via QStackedWidget)
# -----------------------------
class _CustomerMoneyDialog(QDialog):
    """
    One dialog with three pages:
      - Receipt (existing behavior preserved)
      - Record Advance
      - Apply Advance
    Returns a payload tailored to the selected mode.
    """

    PAGE_RECEIPT = 0
    PAGE_ADVANCE = 1
    PAGE_APPLY = 2

    def __init__(self, *, mode: str, customer_id: int, sale_id: Optional[str], defaults: dict) -> None:
        super().__init__(None)
        self.setWindowTitle(_t("Customer Money"))
        self.setModal(True)

        # --- common state ---
        self._payload: Optional[dict] = None
        self._customer_id = int(customer_id)
        self._locked_sale_id = str(sale_id) if sale_id is not None else None
        self._defaults = defaults or {}

        # --- adapters via defaults (all optional) ---
        self._list_sales_for_customer: Optional[Callable[[int], list]] = self._defaults.get("list_sales_for_customer")
        self._sales_seed: Optional[list] = self._defaults.get("sales")
        self._list_company_bank_accounts: Optional[Callable[[], list]] = self._defaults.get("list_company_bank_accounts")
        self._today: Optional[Callable[[], str]] = self._defaults.get("today")
        self._get_available_advance: Optional[Callable[[int], float]] = self._defaults.get("get_available_advance")
        self._get_sale_due: Optional[Callable[[str], float]] = self._defaults.get("get_sale_due")

        # --- Prefills shared for receipt page ---
        self._prefill_method: Optional[str] = self._defaults.get("method")
        self._prefill_amount: Optional[float] = self._defaults.get("amount")
        self._prefill_date: Optional[str] = self._defaults.get("date")
        self._prefill_bank_id: Optional[int] = self._defaults.get("bank_account_id")
        self._prefill_instrument_type: Optional[str] = self._defaults.get("instrument_type")
        self._prefill_instrument_no: Optional[str] = self._defaults.get("instrument_no")
        self._prefill_instrument_date: Optional[str] = self._defaults.get("instrument_date")
        self._prefill_deposited_date: Optional[str] = self._defaults.get("deposited_date")
        self._prefill_clearing_state: Optional[str] = self._defaults.get("clearing_state")
        self._prefill_cleared_date: Optional[str] = self._defaults.get("cleared_date")
        self._prefill_ref_no: Optional[str] = self._defaults.get("ref_no")
        self._prefill_notes: Optional[str] = self._defaults.get("notes")
        self._prefill_created_by: Optional[int] = self._defaults.get("created_by")
        self._customer_display: Optional[str] = self._defaults.get("customer_display")

        # build UI
        self._build_ui()

        # initial page
        initial = {
            "receipt": self.PAGE_RECEIPT,
            "advance": self.PAGE_ADVANCE,
            "apply_advance": self.PAGE_APPLY,
        }.get(mode, self.PAGE_RECEIPT)
        self.pageStack.setCurrentIndex(initial)
        self.tabBar.setCurrentIndex(initial)
        self._sync_window_title()

        # load data and prefills
        self._load_sales()
        self._load_bank_accounts()
        self._apply_prefills_receipt()
        self._lock_sale_if_needed()
        self._on_method_changed()    # sets defaults for instrument/clearing
        self._update_hint()
        self._validate_live()        # receipt page
        self._validate_live_advance()
        self._validate_live_apply()

    # ---------- overall layout ----------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # Tab-like bar controlling a stacked widget
        self.tabBar = QTabBar()
        self.tabBar.addTab(_t("Receipt"))
        self.tabBar.addTab(_t("Record Advance"))
        self.tabBar.addTab(_t("Apply Advance"))
        self.tabBar.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabBar)

        self.pageStack = QStackedWidget()
        outer.addWidget(self.pageStack, 1)

        # Build three pages
        self.page_receipt = QWidget()
        self._build_receipt_page(self.page_receipt)
        self.pageStack.addWidget(self.page_receipt)

        self.page_advance = QWidget()
        self._build_advance_page(self.page_advance)
        self.pageStack.addWidget(self.page_advance)

        self.page_apply = QWidget()
        self._build_apply_page(self.page_apply)
        self.pageStack.addWidget(self.page_apply)

        # Common hint/error/buttons
        self.hintLabel = QLabel("")
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setStyleSheet("color: #666;")
        outer.addWidget(self.hintLabel)

        self.errorLabel = QLabel("")
        self.errorLabel.setStyleSheet("color: #b00020;")
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

    # ---------- Receipt Page (existing behavior) ----------
    def _build_receipt_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Sale row
        self.salePicker = QComboBox()
        self.saleRemainingLabel = QLabel("")
        sale_row = QWidget()
        h = QHBoxLayout(sale_row)
        h.addWidget(self.salePicker, 1)
        h.addWidget(self.saleRemainingLabel, 0, Qt.AlignRight)
        lbl_sale = QLabel(_t("Sale"))
        lbl_sale.setBuddy(self.salePicker)
        form.addRow(lbl_sale, sale_row)

        # Customer label
        self.customerLabel = QLabel(_t("Customer: ") + (str(self._customer_display or self._customer_id)))
        form.addRow(QLabel(""), self.customerLabel)

        # Method
        self.methodCombo = QComboBox()
        for m in METHODS:
            self.methodCombo.addItem(m)
        form.addRow(QLabel(_t("Method")), self.methodCombo)

        # Amount
        self.amountEdit = QDoubleSpinBox()
        self.amountEdit.setDecimals(2)
        self.amountEdit.setRange(-1_000_000_000.00, 1_000_000_000.00)
        self.amountEdit.setSingleStep(1.00)
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
        self.bankAccountCombo = QComboBox()
        lbl_bank = QLabel(_t("Company Bank"))
        lbl_bank.setBuddy(self.bankAccountCombo)
        form.addRow(lbl_bank, self.bankAccountCombo)

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

        # Ref / Notes / Created by
        self.refNoEdit = QLineEdit()
        form.addRow(QLabel(_t("Ref No")), self.refNoEdit)

        self.notesEdit = QPlainTextEdit()
        self.notesEdit.setPlaceholderText(_t("Optional notes"))
        self.notesEdit.setFixedHeight(80)
        form.addRow(QLabel(_t("Notes")), self.notesEdit)

        self.createdByEdit = QLineEdit()
        self.createdByEdit.setValidator(QIntValidator())
        form.addRow(QLabel(_t("Created By")), self.createdByEdit)

        # For toggling required asterisks
        self._label_map = {
            self.bankAccountCombo: lbl_bank,
            self.instrumentNoEdit: lbl_insno,
            self.amountEdit: lbl_amount,
        }

        # wire
        self.salePicker.currentIndexChanged.connect(self._update_remaining)
        self.methodCombo.currentIndexChanged.connect(self._on_method_changed)
        self.clearingStateCombo.currentIndexChanged.connect(self._on_clearing_changed)
        self.amountEdit.valueChanged.connect(self._validate_live)
        self.bankAccountCombo.currentIndexChanged.connect(self._validate_live)
        self.instrumentNoEdit.textChanged.connect(self._validate_live)
        self.instrumentTypeCombo.currentIndexChanged.connect(self._validate_live)
        self.clearedDateEdit.dateChanged.connect(self._validate_live)

    # ---------- Record Advance Page ----------
    def _build_advance_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Customer label
        self.customerLabel2 = QLabel(_t("Customer: ") + (str(self._customer_display or self._customer_id)))
        form.addRow(QLabel(""), self.customerLabel2)

        # Amount (>0)
        self.advAmountEdit = QDoubleSpinBox()
        self.advAmountEdit.setDecimals(2)
        self.advAmountEdit.setRange(0.00, 1_000_000_000.00)
        self.advAmountEdit.setSingleStep(1.00)
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

        # available credit (if adapter provided)
        self.availableLabel = QLabel("")
        form.addRow(QLabel(_t("Available Credit")), self.availableLabel)

        # wire
        self.advAmountEdit.valueChanged.connect(self._validate_live_advance)

    # ---------- Apply Advance Page ----------
    def _build_apply_page(self, page: QWidget) -> None:
        form = QFormLayout(page)

        # Sale pick (or preselected)
        self.applySalePicker = QComboBox()
        lbl_sale2 = QLabel(_t("Sale *"))
        lbl_sale2.setBuddy(self.applySalePicker)
        form.addRow(lbl_sale2, self.applySalePicker)

        self.applySaleRemainingLabel = QLabel("")
        form.addRow(QLabel(_t("Remaining Due")), self.applySaleRemainingLabel)

        # Amount (>0)
        self.applyAmountEdit = QDoubleSpinBox()
        self.applyAmountEdit.setDecimals(2)
        self.applyAmountEdit.setRange(0.00, 1_000_000_000.00)
        self.applyAmountEdit.setSingleStep(1.00)
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

        # info labels (if adapters provided)
        self.applyAvailLabel = QLabel("")
        form.addRow(QLabel(_t("Available Credit")), self.applyAvailLabel)

        # wire
        self.applySalePicker.currentIndexChanged.connect(self._update_apply_remaining)
        self.applyAmountEdit.valueChanged.connect(self._validate_live_apply)

    # ---------- Tab events ----------
    def _on_tab_changed(self, idx: int) -> None:
        self.pageStack.setCurrentIndex(idx)
        self._sync_window_title()
        self._update_hint()
        self._validate_live()
        self._validate_live_advance()
        self._validate_live_apply()

    def _sync_window_title(self) -> None:
        titles = {
            self.PAGE_RECEIPT: _t("Record Customer Receipt"),
            self.PAGE_ADVANCE: _t("Record Customer Advance"),
            self.PAGE_APPLY: _t("Apply Customer Advance to Sale"),
        }
        self.setWindowTitle(titles.get(self.pageStack.currentIndex(), _t("Customer Money")))

    # ---------- Data loaders ----------
    def _load_sales(self) -> None:
        # used by both receipt and apply pages
        sales: list[dict] = []
        try:
            if self._list_sales_for_customer:
                sales = list(self._list_sales_for_customer(self._customer_id))
            elif isinstance(self._sales_seed, list):
                sales = list(self._sales_seed)
        except Exception:
            sales = []

        # Receipt sale picker
        if hasattr(self, "salePicker"):
            self.salePicker.clear()
            for row in sales:
                sid = str(row.get("sale_id", ""))
                doc = str(row.get("doc_no", sid))
                date = str(row.get("date", ""))
                total = float(row.get("total", 0.0))
                paid = float(row.get("paid", 0.0))
                rem = total - paid
                display = f"{doc} — {date} — Total {total:.2f} Paid {paid:.2f} Rem {rem:.2f}"
                self.salePicker.addItem(display, row)
            self._update_remaining()

        # Apply sale picker
        if hasattr(self, "applySalePicker"):
            self.applySalePicker.clear()
            for row in sales:
                sid = str(row.get("sale_id", ""))
                doc = str(row.get("doc_no", sid))
                date = str(row.get("date", ""))
                total = float(row.get("total", 0.0))
                paid = float(row.get("paid", 0.0))
                rem = total - paid
                display = f"{doc} — {date} — Total {total:.2f} Paid {paid:.2f} Rem {rem:.2f}"
                self.applySalePicker.addItem(display, row)
            self._update_apply_remaining()

        # Available credit labels (if adapter)
        if self._get_available_advance:
            try:
                bal = float(self._get_available_advance(self._customer_id))
                if hasattr(self, "availableLabel"):
                    self.availableLabel.setText(f"{bal:.2f}")
                if hasattr(self, "applyAvailLabel"):
                    self.applyAvailLabel.setText(f"{bal:.2f}")
            except Exception:
                pass

    def _load_bank_accounts(self) -> None:
        if not hasattr(self, "bankAccountCombo"):
            return
        self.bankAccountCombo.clear()
        self.bankAccountCombo.addItem("", None)  # blank row
        accounts: list[dict] = []
        try:
            if self._list_company_bank_accounts:
                accounts = list(self._list_company_bank_accounts())
        except Exception:
            accounts = []
        for acc in accounts:
            self.bankAccountCombo.addItem(str(acc.get("name", "")), int(acc.get("id")))

        # Preselect bank by id if provided
        if self._prefill_bank_id is not None:
            for i in range(self.bankAccountCombo.count()):
                if self.bankAccountCombo.itemData(i) == self._prefill_bank_id:
                    self.bankAccountCombo.setCurrentIndex(i)
                    break

    def _lock_sale_if_needed(self) -> None:
        if self._locked_sale_id is None:
            return
        # Receipt page
        for i in range(self.salePicker.count()):
            data = self.salePicker.itemData(i)
            if isinstance(data, dict) and str(data.get("sale_id", "")) == self._locked_sale_id:
                self.salePicker.setCurrentIndex(i)
                break
        else:
            placeholder = {"sale_id": self._locked_sale_id, "doc_no": self._locked_sale_id, "date": "", "total": 0.0, "paid": 0.0}
            self.salePicker.addItem(self._locked_sale_id, placeholder)
            self.salePicker.setCurrentIndex(self.salePicker.count() - 1)
        self.salePicker.setEnabled(False)

        # Apply page
        for i in range(self.applySalePicker.count()):
            data = self.applySalePicker.itemData(i)
            if isinstance(data, dict) and str(data.get("sale_id", "")) == self._locked_sale_id:
                self.applySalePicker.setCurrentIndex(i)
                self.applySalePicker.setEnabled(False)
                break

    # ---------- Prefills (receipt page only) ----------
    def _apply_prefills_receipt(self) -> None:
        if not hasattr(self, "methodCombo"):
            return
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

        if self._prefill_ref_no:
            self.refNoEdit.setText(str(self._prefill_ref_no))

        if self._prefill_notes:
            self.notesEdit.setPlainText(str(self._prefill_notes))

        if self._prefill_created_by is not None:
            self.createdByEdit.setText(str(self._prefill_created_by))

    # ---------- Signals / UX (receipt) ----------
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

        # Bank requirement
        needs_bank = method in METHODS_REQUIRE_BANK
        self.bankAccountCombo.setEnabled(needs_bank)
        self._set_required_label(self.bankAccountCombo, needs_bank)
        if method == "Cash":
            self.bankAccountCombo.setCurrentIndex(0)  # blank

        # Instrument number required?
        req_inst = method in METHODS_REQUIRE_INSTR_NO
        self._set_required_label(self.instrumentNoEdit, req_inst)

        # UX focus
        if needs_bank:
            self.bankAccountCombo.setFocus()
        elif req_inst:
            self.instrumentNoEdit.setFocus()
        else:
            self.amountEdit.setFocus()

        self._update_hint()
        self._validate_live()

    def _on_clearing_changed(self) -> None:
        state = self.clearingStateCombo.currentText()
        enable_cd = state == "cleared"
        self.clearedDateEdit.setEnabled(enable_cd)
        if not enable_cd:
            self._clear_date(self.clearedDateEdit)
        self._validate_live()

    def _update_hint(self) -> None:
        idx = self.pageStack.currentIndex()
        hint = ""
        if idx == self.PAGE_RECEIPT:
            method = self.methodCombo.currentText()
            if method == "Cash":
                hint = _t("Negative amounts allowed. Bank must be blank. Instrument no optional.")
            elif method == "Bank Transfer":
                hint = _t("Incoming only (>0). Company bank required. Instrument type 'online'. Instrument no required.")
            elif method == "Cheque":
                hint = _t("Incoming only (>0). Company bank required. Type 'cross_cheque'. Cheque no required.")
            elif method == "Cash Deposit":
                hint = _t("Incoming only (>0). Company bank required. Type 'cash_deposit'. Deposit slip no required.")
            elif method in ("Card", "Other"):
                hint = _t("Incoming only (>0). Bank optional. Instrument no optional.")
        elif idx == self.PAGE_ADVANCE:
            hint = _t("Record a positive customer advance (store credit). No method or bank needed.")
        elif idx == self.PAGE_APPLY:
            hint = _t("Apply available advance to an open sale. Amount must not exceed available credit or remaining due.")
        self.hintLabel.setText(hint)

    def _update_remaining(self) -> None:
        data = self.salePicker.currentData()
        if isinstance(data, dict):
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            rem = total - paid
            self.saleRemainingLabel.setText(_t(f"Remaining: ${rem:.2f}"))
        else:
            self.saleRemainingLabel.setText("")

    # ---------- Apply page helpers ----------
    def _update_apply_remaining(self) -> None:
        data = self.applySalePicker.currentData()
        if isinstance(data, dict):
            total = float(data.get("total", 0.0))
            paid = float(data.get("paid", 0.0))
            rem = total - paid
            # If adapter exists, prefer it for more accurate due
            if self._get_sale_due and str(data.get("sale_id", "")):
                try:
                    rem = float(self._get_sale_due(str(data.get("sale_id"))))
                except Exception:
                    pass
            self.applySaleRemainingLabel.setText(f"{rem:.2f}")
        else:
            self.applySaleRemainingLabel.setText("")

    # ---------- Validation (receipt) ----------
    def _validate_live(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_RECEIPT:
            return
        ok, msg = self._validate_receipt()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_receipt(self) -> tuple[bool, Optional[str]]:
        # 1) Sale present
        sale_dict = self.salePicker.currentData()
        if not isinstance(sale_dict, dict) or not str(sale_dict.get("sale_id", "")):
            return False, _t("Please select a sale for this receipt.")

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
        bank_id = self._current_bank_id()
        if method == "Cash":
            if bank_id is not None:
                return False, _t("Bank must be empty when method is Cash.")
        elif method in METHODS_REQUIRE_BANK and bank_id is None:
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

        # 8) Dates string format safety
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
        # no upper bound for grant_credit (business rules allow any positive)
        return True, None

    # ---------- Validation (apply advance) ----------
    def _validate_live_apply(self) -> None:
        if self.pageStack.currentIndex() != self.PAGE_APPLY:
            return
        ok, msg = self._validate_apply()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate_apply(self) -> tuple[bool, Optional[str]]:
        # Sale present
        data = self.applySalePicker.currentData()
        if not isinstance(data, dict) or not str(data.get("sale_id", "")):
            return False, _t("Please select a sale to apply the advance.")

        amt = float(self.applyAmountEdit.value())
        if amt <= 0.0:
            return False, _t("Amount must be greater than zero.")

        # Bounds (best-effort via adapters; repo will enforce again)
        # available credit
        if self._get_available_advance:
            try:
                bal = float(self._get_available_advance(self._customer_id))
                if amt - bal > 1e-9:
                    return False, _t("Amount exceeds available customer advance.")
            except Exception:
                pass
        # sale due
        try:
            rem = None
            if self._get_sale_due and str(data.get("sale_id", "")):
                rem = float(self._get_sale_due(str(data.get("sale_id"))))
            else:
                total = float(data.get("total", 0.0))
                paid = float(data.get("paid", 0.0))
                rem = total - paid
            if amt - rem > 1e-9:
                return False, _t("Amount exceeds remaining due for the selected sale.")
        except Exception:
            pass

        return True, None

    # ---------- Save ----------
    def _on_save(self) -> None:
        idx = self.pageStack.currentIndex()
        if idx == self.PAGE_RECEIPT:
            ok, msg = self._validate_receipt()
            if not ok:
                self._warn(msg); return
            self._payload = self._build_payload_receipt()
        elif idx == self.PAGE_ADVANCE:
            ok, msg = self._validate_advance()
            if not ok:
                self._warn(msg); return
            self._payload = self._build_payload_advance()
        elif idx == self.PAGE_APPLY:
            ok, msg = self._validate_apply()
            if not ok:
                self._warn(msg); return
            self._payload = self._build_payload_apply()

        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    # ---------- Helpers ----------
    def _warn(self, msg: Optional[str]) -> None:
        self.errorLabel.setText(msg or "")
        QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))

    def _current_bank_id(self) -> Optional[int]:
        data = self.bankAccountCombo.currentData()
        return int(data) if isinstance(data, int) else None

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
    def _build_payload_receipt(self) -> dict:
        sale_dict = self.salePicker.currentData() or {}

        def date_or_none(edit: QDateEdit) -> Optional[str]:
            if edit.isEnabled():
                return edit.date().toString("yyyy-MM-dd")
            return None

        payload = {
            "sale_id": str(sale_dict.get("sale_id")),
            "amount": float(self.amountEdit.value()),
            "method": self.methodCombo.currentText(),
            "date": self.dateEdit.date().toString("yyyy-MM-dd"),
            "bank_account_id": self._current_bank_id(),
            "instrument_type": self.instrumentTypeCombo.currentText() or None,
            "instrument_no": (self.instrumentNoEdit.text().strip() or None),
            "instrument_date": date_or_none(self.instrumentDateEdit),
            "deposited_date": date_or_none(self.depositedDateEdit),
            "clearing_state": self.clearingStateCombo.currentText() or None,
            "cleared_date": (self.clearedDateEdit.date().toString("yyyy-MM-dd") if self.clearedDateEdit.isEnabled() else None),
            "ref_no": (self.refNoEdit.text().strip() or None),
            "notes": (self.notesEdit.toPlainText().strip() or None),
            "created_by": (int(self.createdByEdit.text()) if self.createdByEdit.text().strip() else None),
        }
        return payload

    def _build_payload_advance(self) -> dict:
        payload = {
            "customer_id": self._customer_id,
            "amount": float(self.advAmountEdit.value()),
            "date": self.advDateEdit.date().toString("yyyy-MM-dd"),
            "notes": (self.advNotesEdit.toPlainText().strip() or None),
            "created_by": (int(self.advCreatedByEdit.text()) if self.advCreatedByEdit.text().strip() else None),
        }
        return payload

    def _build_payload_apply(self) -> dict:
        sale_dict = self.applySalePicker.currentData() or {}
        payload = {
            "customer_id": self._customer_id,
            "sale_id": str(sale_dict.get("sale_id")),
            "amount": float(self.applyAmountEdit.value()),
            "date": self.applyDateEdit.date().toString("yyyy-MM-dd"),
            "notes": (self.applyNotesEdit.toPlainText().strip() or None),
            "created_by": (int(self.applyCreatedByEdit.text()) if self.applyCreatedByEdit.text().strip() else None),
        }
        return payload
