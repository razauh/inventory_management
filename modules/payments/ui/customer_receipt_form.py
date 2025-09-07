from __future__ import annotations

from typing import Callable, Iterable, Optional

try:
    # Prefer PySide6 per spec
    from PySide6.QtCore import Qt, QDate
    from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeySequence
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
    )
except Exception:  # pragma: no cover - fallback if PySide6 not installed at import-time
    # Lazy import error will occur only when this file is actually executed without PySide6
    raise


# -----------------------------
# i18n shim
# -----------------------------

def _t(s: str) -> str:
    """Trivial translation shim (replace with Qt tr() if you wire it)."""
    return s


# -----------------------------
# Constants — canonical values per contract
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

# Method → enforced/default instrument type
METHOD_TO_FORCED_INSTRUMENT = {
    "Cash": "other",
    "Bank Transfer": "online",
    "Card": "other",
    "Cheque": "cross_cheque",
    "Cash Deposit": "cash_deposit",
    "Other": "other",
}

# Method → default clearing state
METHOD_TO_DEFAULT_CLEARING = {
    "Cash": "posted",
    "Bank Transfer": "posted",
    "Card": "posted",
    "Cheque": "pending",
    "Cash Deposit": "pending",
    "Other": "posted",
}

# Methods that require a company bank account
METHODS_REQUIRE_BANK = {"Bank Transfer", "Cheque", "Cash Deposit"}
# Methods for which instrument number is required
METHODS_REQUIRE_INSTR_NO = {"Bank Transfer", "Cheque", "Cash Deposit"}


# -----------------------------
# Public API
# -----------------------------

def open_receipt_form(
    customer_id: int,
    sale_id: Optional[str] = None,
    defaults: Optional[dict] = None,
) -> Optional[dict]:
    """
    Shows a modal dialog to capture a customer receipt.
    Returns a payload dict on Save, or None on Cancel.
    """
    app = QApplication.instance()
    owns_app = False
    if app is None:
        # Allow standalone manual testing
        app = QApplication([])
        owns_app = True
    dlg = CustomerReceiptForm(parent=None, sale_id=sale_id, defaults=defaults or {}, customer_id=customer_id)
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None
    if owns_app:
        app.quit()
    return payload


def open_receipt_form_and_record(
    db_path: str,
    *,
    customer_id: int,
    sale_id: Optional[str] = None,
    defaults: Optional[dict] = None,
) -> Optional[int]:
    """
    Convenience entrypoint that opens the receipt form, gathers the UI dict,
    and immediately persists it using SalePaymentsRepo via the
    customer_payments.sale_payments_model.record_from_ui(...) façade.

    Returns:
        payment_id (int) on success, or None if the dialog was cancelled.

    Example usage (controller handler):

        new_id = open_receipt_form_and_record(DB_PATH, customer_id=cid, sale_id=sale_no, defaults=prefills)

    This mirrors the snippet:

        payload = {...}
        new_id = record_from_ui(DB_PATH, payload)
    """
    payload = open_receipt_form(customer_id=customer_id, sale_id=sale_id, defaults=defaults or {})
    if payload is None:
        return None

    # Lazy import to avoid hard dependency when this UI is imported in design-time tools
    from inventory_management.modules.payments.customer_payments.sale_payments_model import (  # type: ignore
        record_from_ui,
    )

    return record_from_ui(db_path, payload)


class CustomerReceiptForm(QDialog):
    """
    Customer receipt entry dialog.

    Constructor tolerant to: (parent), (parent, sale_id), (parent, sale_id, db_path), (parent, sale_id, conn)
    We ignore db_path/conn in this standalone UI; use adapters via `defaults`.

    Exposed methods:
      - set_sale_id(sale_id: str) -> None
      - exec() -> int  (QDialog.Accepted / Rejected)
      - payload() -> dict | None  (None iff canceled)
    """

    def __init__(self, parent: Optional[QWidget] = None, sale_id: Optional[str] = None, db_path: Optional[str] = None, conn: Optional[object] = None, defaults: Optional[dict] = None, customer_id: Optional[int] = None):  # type: ignore[override]
        super().__init__(parent)
        self.setWindowTitle(_t("Record Customer Receipt"))
        self.setModal(True)
        self._payload: Optional[dict] = None
        self._sale_locked = sale_id is not None
        self._customer_id = customer_id
        self._defaults = defaults or {}

        # Data adapters
        self._list_sales_for_customer: Optional[Callable[[int], list]] = self._defaults.get("list_sales_for_customer")
        self._sales_seed: Optional[list] = self._defaults.get("sales")  # fallback list[dict]
        self._list_company_bank_accounts: Optional[Callable[[], list]] = self._defaults.get("list_company_bank_accounts")

        # Prefill defaults
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

        # Build UI
        self._build_ui()

        # Populate combos and apply defaults
        self._load_sales(customer_id=customer_id)
        if sale_id:
            self.set_sale_id(sale_id)
        self._load_bank_accounts()
        self._apply_prefills()

        # Wire signals after defaults
        self._wire_signals()
        self._on_method_changed()  # ensure matrix enforced initially
        self._update_hint()
        self._validate_live()  # initial save button state

    # ------------------------- UI -------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # Title
        title = QLabel(_t("Record Customer Receipt"))
        title.setObjectName("dlgTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(title)

        # Form
        form = QFormLayout()
        outer.addLayout(form)

        # Section A — Document context
        self.salePicker = QComboBox()
        self.salePicker.setEditable(False)
        self.saleRemainingLabel = QLabel("")
        h_sale = QHBoxLayout()
        h_sale.addWidget(self.salePicker, 1)
        h_sale.addWidget(self.saleRemainingLabel, 0, Qt.AlignRight)
        sale_row = QWidget()
        sale_row.setLayout(h_sale)
        lbl_sale = QLabel(_t("Sale"))
        lbl_sale.setBuddy(self.salePicker)
        form.addRow(lbl_sale, sale_row)

        self.customerLabel = QLabel(_t("Customer: ") + (str(self._customer_display or self._customer_id or "")))
        form.addRow(QLabel(""), self.customerLabel)

        # Section B — Payment core
        self.methodCombo = QComboBox()
        for m in METHODS:
            self.methodCombo.addItem(m)
        lbl_method = QLabel(_t("Method"))
        lbl_method.setBuddy(self.methodCombo)
        form.addRow(lbl_method, self.methodCombo)

        self.amountEdit = QDoubleSpinBox()
        self.amountEdit.setDecimals(2)
        self.amountEdit.setRange(-1_000_000_000.00, 1_000_000_000.00)
        self.amountEdit.setSingleStep(1.00)
        lbl_amount = QLabel(_t("Amount"))
        lbl_amount.setBuddy(self.amountEdit)
        form.addRow(lbl_amount, self.amountEdit)

        self.dateEdit = QDateEdit()
        self.dateEdit.setCalendarPopup(True)
        self.dateEdit.setDisplayFormat("yyyy-MM-dd")
        self.dateEdit.setDate(QDate.currentDate())
        lbl_date = QLabel(_t("Date"))
        lbl_date.setBuddy(self.dateEdit)
        form.addRow(lbl_date, self.dateEdit)

        # Section C — Bank & instrument details
        self.bankAccountCombo = QComboBox()
        lbl_bank = QLabel(_t("Company Bank"))
        lbl_bank.setBuddy(self.bankAccountCombo)
        form.addRow(lbl_bank, self.bankAccountCombo)

        self.instrumentTypeCombo = QComboBox()
        for t in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.addItem(t)
        lbl_instype = QLabel(_t("Instrument Type"))
        lbl_instype.setBuddy(self.instrumentTypeCombo)
        form.addRow(lbl_instype, self.instrumentTypeCombo)

        self.instrumentNoEdit = QLineEdit()
        lbl_insno = QLabel(_t("Instrument No"))
        lbl_insno.setBuddy(self.instrumentNoEdit)
        form.addRow(lbl_insno, self.instrumentNoEdit)

        self.instrumentDateEdit = QDateEdit()
        self.instrumentDateEdit.setCalendarPopup(True)
        self.instrumentDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.instrumentDateEdit.setSpecialValueText("")
        self.instrumentDateEdit.setDate(QDate.currentDate())
        lbl_insdate = QLabel(_t("Instrument Date"))
        lbl_insdate.setBuddy(self.instrumentDateEdit)
        form.addRow(lbl_insdate, self.instrumentDateEdit)

        self.depositedDateEdit = QDateEdit()
        self.depositedDateEdit.setCalendarPopup(True)
        self.depositedDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.depositedDateEdit.setSpecialValueText("")
        self.depositedDateEdit.setDate(QDate.currentDate())
        lbl_depdate = QLabel(_t("Deposited Date"))
        lbl_depdate.setBuddy(self.depositedDateEdit)
        form.addRow(lbl_depdate, self.depositedDateEdit)

        self.clearingStateCombo = QComboBox()
        for s in CLEARING_STATES:
            self.clearingStateCombo.addItem(s)
        lbl_clr = QLabel(_t("Clearing State"))
        lbl_clr.setBuddy(self.clearingStateCombo)
        form.addRow(lbl_clr, self.clearingStateCombo)

        self.clearedDateEdit = QDateEdit()
        self.clearedDateEdit.setCalendarPopup(True)
        self.clearedDateEdit.setDisplayFormat("yyyy-MM-dd")
        self.clearedDateEdit.setSpecialValueText("")
        self.clearedDateEdit.setDate(QDate.currentDate())
        lbl_clre = QLabel(_t("Cleared Date"))
        lbl_clre.setBuddy(self.clearedDateEdit)
        form.addRow(lbl_clre, self.clearedDateEdit)

        # Section D — Misc
        self.refNoEdit = QLineEdit()
        lbl_ref = QLabel(_t("Ref No"))
        lbl_ref.setBuddy(self.refNoEdit)
        form.addRow(lbl_ref, self.refNoEdit)

        self.notesEdit = QPlainTextEdit()
        self.notesEdit.setPlaceholderText(_t("Optional notes"))
        self.notesEdit.setFixedHeight(80)
        lbl_notes = QLabel(_t("Notes"))
        lbl_notes.setBuddy(self.notesEdit)
        form.addRow(lbl_notes, self.notesEdit)

        self.createdByEdit = QLineEdit()
        self.createdByEdit.setValidator(QIntValidator())
        lbl_created = QLabel(_t("Created By"))
        lbl_created.setBuddy(self.createdByEdit)
        form.addRow(lbl_created, self.createdByEdit)

        # Dynamic hint + inline error
        self.hintLabel = QLabel("")
        self.hintLabel.setObjectName("hintLabel")
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setStyleSheet("color: #666;")
        outer.addWidget(self.hintLabel)

        self.errorLabel = QLabel("")
        self.errorLabel.setObjectName("errorLabel")
        self.errorLabel.setStyleSheet("color: #b00020;")
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

        # Keep label refs to toggle required asterisks
        self._label_map = {
            self.bankAccountCombo: lbl_bank,
            self.instrumentNoEdit: lbl_insno,
            self.amountEdit: lbl_amount,
        }

    # ------------------------- Data loading -------------------------
    def _load_sales(self, customer_id: Optional[int]) -> None:
        self.salePicker.clear()
        sales: list[dict] = []
        try:
            if self._list_sales_for_customer and customer_id is not None:
                sales = list(self._list_sales_for_customer(customer_id))
            elif isinstance(self._sales_seed, list):
                sales = list(self._sales_seed)
        except Exception:
            sales = []

        # Expect keys: sale_id, doc_no, date, total, paid
        for row in sales:
            sid = str(row.get("sale_id", ""))
            doc = str(row.get("doc_no", sid))
            date = str(row.get("date", ""))
            total = float(row.get("total", 0.0))
            paid = float(row.get("paid", 0.0))
            remaining = total - paid
            display = f"{doc} — {date} — Total {total:.2f} Paid {paid:.2f} Rem {remaining:.2f}"
            self.salePicker.addItem(display, row)
        if self._sale_locked:
            self.salePicker.setEnabled(False)
        self.salePicker.currentIndexChanged.connect(self._update_remaining)
        self._update_remaining()

    def _load_bank_accounts(self) -> None:
        self.bankAccountCombo.clear()
        accounts: list[dict] = []
        try:
            if self._list_company_bank_accounts:
                accounts = list(self._list_company_bank_accounts())
        except Exception:
            accounts = []
        # Add blank row for optional cases
        self.bankAccountCombo.addItem("", None)
        for acc in accounts:
            self.bankAccountCombo.addItem(str(acc.get("name", "")), int(acc.get("id")))

        # Preselect by id if given
        if self._prefill_bank_id is not None:
            for i in range(self.bankAccountCombo.count()):
                if self.bankAccountCombo.itemData(i) == self._prefill_bank_id:
                    self.bankAccountCombo.setCurrentIndex(i)
                    break

    # ------------------------- Prefills -------------------------
    def _apply_prefills(self) -> None:
        if self._prefill_method in METHODS:
            self.methodCombo.setCurrentIndex(METHODS.index(self._prefill_method))
        elif self._prefill_method:
            # Keep method as-is (first item) if invalid; validation will catch unsupported
            pass

        if isinstance(self._prefill_amount, (int, float)):
            self.amountEdit.setValue(float(self._prefill_amount))

        if self._prefill_date:
            self._set_date_from_str(self.dateEdit, self._prefill_date)

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

    # ------------------------- Signals & reactions -------------------------
    def _wire_signals(self) -> None:
        self.methodCombo.currentIndexChanged.connect(self._on_method_changed)
        self.clearingStateCombo.currentIndexChanged.connect(self._on_clearing_changed)
        self.amountEdit.valueChanged.connect(self._validate_live)
        self.bankAccountCombo.currentIndexChanged.connect(self._validate_live)
        self.instrumentNoEdit.textChanged.connect(self._validate_live)
        self.instrumentTypeCombo.currentIndexChanged.connect(self._validate_live)
        self.clearedDateEdit.dateChanged.connect(self._validate_live)

    def _on_method_changed(self) -> None:
        method = self.methodCombo.currentText()

        # Instrument type default / forced selection (user can change; validation will enforce)
        forced = METHOD_TO_FORCED_INSTRUMENT.get(method)
        if forced in INSTRUMENT_TYPES:
            self.instrumentTypeCombo.setCurrentIndex(INSTRUMENT_TYPES.index(forced))

        # Clearing state default per method
        default_clear = METHOD_TO_DEFAULT_CLEARING.get(method, "posted")
        if default_clear in CLEARING_STATES:
            self.clearingStateCombo.setCurrentIndex(CLEARING_STATES.index(default_clear))

        # Bank account enabled/required
        needs_bank = method in METHODS_REQUIRE_BANK
        self.bankAccountCombo.setEnabled(needs_bank)
        self._set_required_label(self.bankAccountCombo, needs_bank)
        if method == "Cash":
            # Force blank for Cash
            self.bankAccountCombo.setCurrentIndex(0)  # the blank row

        # Instrument number required?
        req_inst = method in METHODS_REQUIRE_INSTR_NO
        self._set_required_label(self.instrumentNoEdit, req_inst)

        # Amount can be negative only for Cash → live validation will handle

        # Focus next required field for UX
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
            # Clear when disabled
            self._clear_date(self.clearedDateEdit)
        self._validate_live()

    def _update_hint(self) -> None:
        method = self.methodCombo.currentText()
        hint = ""
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

    # ------------------------- Validation -------------------------
    def _validate_live(self) -> None:
        ok, msg = self._validate(check_live=True)
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate(self, check_live: bool = False) -> tuple[bool, Optional[str]]:
        # 1) Sale selection
        sale_dict = self.salePicker.currentData()
        if not isinstance(sale_dict, dict) or not str(sale_dict.get("sale_id", "")):
            return False, _t("Please select a sale for this receipt.")

        # 2) Method validity
        method = self.methodCombo.currentText()
        if method not in METHODS:
            return False, _t("Payment method is not supported.")

        # 3) Amount present & sign
        amount = float(self.amountEdit.value())
        if abs(amount) < 1e-9:
            return False, _t("Amount cannot be zero.")
        if amount < 0 and method != "Cash":
            return False, _t("Refunds (negative amounts) are only allowed with the Cash method.")
        if amount > 0 and method == "Cash":
            # Positive is fine for Cash as well; spec allows any non-zero for Cash
            pass

        # 4) Bank account rules
        bank_id = self._current_bank_id()
        if method == "Cash":
            if bank_id is not None:
                return False, _t("Bank must be empty when method is Cash.")
        elif method in METHODS_REQUIRE_BANK:
            if bank_id is None:
                return False, _t("Company bank account is required for this method.")
        # Card/Other optional → no check

        # 5) Instrument type enforcement
        instype = self.instrumentTypeCombo.currentText()
        if instype not in INSTRUMENT_TYPES:
            return False, _t("Payment method is not supported.")  # generic guard
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

        # 7) Clearing / dates
        state = self.clearingStateCombo.currentText()
        if state == "cleared":
            if not self._has_date(self.clearedDateEdit):
                return False, _t("Please select a cleared date.")
        else:
            # UI already clears when not cleared
            pass

        # 8) Dates format — QDateEdits already constrain; if user typed, ensure toString is valid
        for de in (self.dateEdit, self.instrumentDateEdit, self.depositedDateEdit, self.clearedDateEdit):
            if self._has_date(de):
                s = de.date().toString("yyyy-MM-dd")
                if len(s) != 10:
                    return False, _t("Please enter dates in YYYY-MM-DD.")

        return True, None

    # ------------------------- Save / Cancel -------------------------
    def _on_save(self) -> None:
        ok, msg = self._validate(check_live=False)
        if not ok:
            self.errorLabel.setText(msg or "")
            # Also show a dialog for clarity
            QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))
            return
        self._payload = self._build_payload()
        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    def set_sale_id(self, sale_id: str) -> None:
        # Find sale id in combo's data
        for i in range(self.salePicker.count()):
            data = self.salePicker.itemData(i)
            if isinstance(data, dict) and str(data.get("sale_id")) == str(sale_id):
                self.salePicker.setCurrentIndex(i)
                return
        # If not found, add a minimal placeholder to satisfy locked selection
        placeholder = {"sale_id": str(sale_id), "doc_no": str(sale_id), "date": "", "total": 0.0, "paid": 0.0}
        self.salePicker.addItem(str(sale_id), placeholder)
        self.salePicker.setCurrentIndex(self.salePicker.count() - 1)

    # ------------------------- Helpers -------------------------
    def _current_bank_id(self) -> Optional[int]:
        data = self.bankAccountCombo.currentData()
        return int(data) if isinstance(data, int) else None

    def _set_required_label(self, widget: QWidget, required: bool) -> None:
        label = self._label_map.get(widget)
        if not label:
            return
        text = label.text().rstrip(" *")
        if required:
            label.setText(text + " *")
        else:
            label.setText(text)

    def _set_date_from_str(self, edit: QDateEdit, s: str) -> None:
        try:
            parts = s.split("-")
            if len(parts) == 3:
                y, m, d = map(int, parts)
                edit.setDate(QDate(y, m, d))
        except Exception:
            pass

    def _has_date(self, edit: QDateEdit) -> bool:
        # Always true for QDateEdit unless we decide to use special value; keep simple
        return True

    def _clear_date(self, edit: QDateEdit) -> None:
        # Reset to today but treat as visually blank by clearing special text if needed
        edit.setDate(QDate.currentDate())

    def _build_payload(self) -> dict:
        sale_dict = self.salePicker.currentData() or {}
        def date_or_none(edit: QDateEdit) -> Optional[str]:
            # For simplicity, always serialize. If you prefer tri-state, add UI affordance.
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
