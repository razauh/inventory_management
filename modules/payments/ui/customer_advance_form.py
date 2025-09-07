from __future__ import annotations

from typing import Callable, Optional

try:
    # Prefer PySide6 per spec
    from PySide6.QtCore import Qt, QDate
    from PySide6.QtGui import QIntValidator, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
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
except Exception:  # pragma: no cover
    raise


# -----------------------------
# i18n shim
# -----------------------------

def _t(s: str) -> str:
    """Trivial translation shim (replace with Qt tr() if you wire it)."""
    return s


# -----------------------------
# Public API
# -----------------------------

def open_record_advance_form(
    customer_id: int,
    defaults: Optional[dict] = None,
) -> Optional[dict]:
    """
    Show a modal dialog to record a customer's ADVANCE / DEPOSIT (store credit).
    Return a payload dict on Save, or None on Cancel.
    """
    app = QApplication.instance()
    owns_app = False
    if app is None:
        app = QApplication([])
        owns_app = True
    dlg = CustomerAdvanceForm(parent=None, customer_id=customer_id, defaults=defaults or {})
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None
    if owns_app:
        app.quit()
    return payload


class CustomerAdvanceForm(QDialog):
    """
    Dialog for recording customer advances (deposits / store credit).

    Exposes:
      - exec() -> int (Accepted/Rejected)
      - payload() -> dict | None (None iff canceled)
    """

    def __init__(self, parent: Optional[QWidget] = None, customer_id: Optional[int] = None, defaults: Optional[dict] = None):  # type: ignore[override]
        super().__init__(parent)
        self.setWindowTitle(_t("Record Customer Advance (Deposit)"))
        self.setModal(True)
        self._payload: Optional[dict] = None
        self._customer_id = customer_id
        self._defaults = defaults or {}

        # Adapters (optional)
        self._get_balance: Optional[Callable[[int], float]] = self._defaults.get("get_balance")
        self._today_func: Optional[Callable[[], str]] = self._defaults.get("today")

        # Prefills (optional)
        self._prefill_amount: Optional[float] = self._defaults.get("amount")
        self._prefill_date: Optional[str] = self._defaults.get("date")
        self._prefill_notes: Optional[str] = self._defaults.get("notes")
        self._prefill_created_by: Optional[int] = self._defaults.get("created_by")
        self._customer_display: Optional[str] = self._defaults.get("customer_display")

        self._build_ui()
        self._apply_prefills()
        self._wire_signals()
        self._refresh_balance()
        self._validate_live()

    # ------------------------- UI -------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        title = QLabel(_t("Record Customer Advance (Deposit)"))
        title.setObjectName("dlgTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(title)

        # Customer label
        cust_text = str(self._customer_display or self._customer_id or "")
        self.customerLabel = QLabel(_t("Customer: ") + cust_text)
        outer.addWidget(self.customerLabel)

        form = QFormLayout()
        outer.addLayout(form)

        # Amount
        self.amountSpin = QDoubleSpinBox()
        self.amountSpin.setDecimals(2)
        self.amountSpin.setRange(0.00, 1_000_000_000.00)  # validation enforces > 0
        self.amountSpin.setSingleStep(1.00)
        lbl_amount = QLabel(_t("Amount"))
        lbl_amount.setBuddy(self.amountSpin)
        form.addRow(lbl_amount, self.amountSpin)

        # Date controls (with option to leave empty so repo uses CURRENT_DATE)
        date_row = QHBoxLayout()
        self.dateEdit = QDateEdit()
        self.dateEdit.setCalendarPopup(True)
        self.dateEdit.setDisplayFormat("yyyy-MM-dd")
        # Initialize to 'today'
        if self._today_func:
            try:
                y, m, d = map(int, (self._today_func() or "").split("-"))
                self.dateEdit.setDate(QDate(y, m, d))
            except Exception:
                self.dateEdit.setDate(QDate.currentDate())
        else:
            self.dateEdit.setDate(QDate.currentDate())

        self.noDateCheck = QCheckBox(_t("Leave date empty (use DB default)"))
        self.noDateCheck.setChecked(False)
        date_row.addWidget(self.dateEdit, 1)
        date_row.addWidget(self.noDateCheck, 0)
        date_row_w = QWidget(); date_row_w.setLayout(date_row)
        lbl_date = QLabel(_t("Date"))
        lbl_date.setBuddy(self.dateEdit)
        form.addRow(lbl_date, date_row_w)

        # Notes
        self.notesEdit = QPlainTextEdit()
        self.notesEdit.setPlaceholderText(_t("Optional notes"))
        self.notesEdit.setFixedHeight(80)
        lbl_notes = QLabel(_t("Notes"))
        lbl_notes.setBuddy(self.notesEdit)
        form.addRow(lbl_notes, self.notesEdit)

        # Created by
        self.createdByEdit = QLineEdit()
        self.createdByEdit.setValidator(QIntValidator())
        lbl_created = QLabel(_t("Created By"))
        lbl_created.setBuddy(self.createdByEdit)
        form.addRow(lbl_created, self.createdByEdit)

        # Hint under amount
        self.hintLabel = QLabel(_t("This creates store credit for the customer (source_type=deposit). You can apply it later to a sale."))
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setStyleSheet("color:#666;")
        outer.addWidget(self.hintLabel)

        # Optional balance label
        self.balanceLabel = QLabel("")
        self.balanceLabel.setObjectName("balanceLabel")
        self.balanceLabel.setStyleSheet("color:#444;")
        outer.addWidget(self.balanceLabel)

        # Inline error label
        self.errorLabel = QLabel("")
        self.errorLabel.setObjectName("errorLabel")
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

    # ------------------------- Prefills -------------------------
    def _apply_prefills(self) -> None:
        if isinstance(self._prefill_amount, (int, float)):
            self.amountSpin.setValue(float(self._prefill_amount))
        if isinstance(self._prefill_created_by, int):
            self.createdByEdit.setText(str(self._prefill_created_by))
        if isinstance(self._prefill_notes, str):
            self.notesEdit.setPlainText(self._prefill_notes)
        if isinstance(self._prefill_date, str):
            # If an explicit date is provided via defaults, prefer it and uncheck 'no date'
            self.noDateCheck.setChecked(False)
            try:
                y, m, d = map(int, self._prefill_date.split("-"))
                self.dateEdit.setDate(QDate(y, m, d))
            except Exception:
                # keep current
                pass

    # ------------------------- Wiring -------------------------
    def _wire_signals(self) -> None:
        self.amountSpin.valueChanged.connect(self._validate_live)
        self.noDateCheck.toggled.connect(self._on_no_date_toggled)

    def _on_no_date_toggled(self, checked: bool) -> None:
        self.dateEdit.setEnabled(not checked)
        self._validate_live()

    # ------------------------- Balance -------------------------
    def _refresh_balance(self) -> None:
        # Only show if adapter is provided and we have a customer id
        if self._get_balance and isinstance(self._customer_id, int):
            try:
                bal = float(self._get_balance(self._customer_id))
                self.balanceLabel.setText(_t(f"Current Balance: ${bal:.2f}"))
                self.balanceLabel.setVisible(True)
            except Exception:
                self.balanceLabel.setVisible(False)
        else:
            self.balanceLabel.setVisible(False)

    # ------------------------- Validation -------------------------
    def _validate_live(self) -> None:
        ok, msg = self._validate()
        self.errorLabel.setText(msg or "")
        self.saveBtn.setEnabled(ok)

    def _validate(self) -> tuple[bool, Optional[str]]:
        # 1) Amount present and positive (> 0)
        amt = float(self.amountSpin.value())
        if amt <= 0.0:
            return False, _t("Deposit amount must be a positive number.")

        # 2) Date format if provided
        if not self.noDateCheck.isChecked():
            # Using QDateEdit ensures a valid date; still ensure format serializes to YYYY-MM-DD
            s = self.dateEdit.date().toString("yyyy-MM-dd")
            if len(s) != 10:
                return False, _t("Please enter the date in YYYY-MM-DD.")

        return True, None

    # ------------------------- Save / Cancel -------------------------
    def _on_save(self) -> None:
        ok, msg = self._validate()
        if not ok:
            self.errorLabel.setText(msg or "")
            QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))
            return
        self._payload = self._build_payload()
        self.accept()

    def payload(self) -> Optional[dict]:
        return self._payload

    # ------------------------- Build payload -------------------------
    def _build_payload(self) -> dict:
        date_value: Optional[str]
        if self.noDateCheck.isChecked():
            date_value = None  # Controller/repo uses DB CURRENT_DATE
        else:
            date_value = self.dateEdit.date().toString("yyyy-MM-dd")

        created_by_val: Optional[int]
        txt = self.createdByEdit.text().strip()
        created_by_val = int(txt) if txt.isdigit() else None

        payload = {
            "amount": float(self.amountSpin.value()),
            "date": date_value,
            "notes": (self.notesEdit.toPlainText().strip() or None),
            "created_by": created_by_val,
        }
        return payload
