# ⚠️ VENDOR MODULE ONLY: Add tooltips to vendor toolbar buttons. Do not modify other modules or shared components.
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPlainTextEdit, QDialogButtonBox, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import Signal
from ...utils.validators import non_empty

# ⚠️ VENDOR MODULE ONLY: safe signal (dis)connect; do not touch other modules
class VendorForm(QDialog):
    # emitted when user wants to manage bank accounts for this vendor
    manageBankAccounts = Signal(int)
    # emitted when user wants to grant credit to this vendor
    grantVendorCredit = Signal(int)
    # emitted when we need to ensure a vendor exists (for Add flow)
    ensureVendorExists = Signal(dict)  # payload for creating vendor when none exists

    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Vendor")
        self.setModal(True)

        # --- remember vendor_id (only present in edit mode) ---
        self._vendor_id = int(initial["vendor_id"]) if initial and initial.get("vendor_id") else None

        self.name = QLineEdit()
        self.contact = QPlainTextEdit()
        self.contact.setPlaceholderText("Phone, email, etc.")
        self.addr = QPlainTextEdit()
        self.addr.setPlaceholderText("Address (optional)")

        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Name*", self.name)
        form.addRow("Contact Info*", self.contact)
        form.addRow("Address", self.addr)
        lay.addLayout(form)

        # --- Small toolbar for operational actions (entry points) ---
        ops_bar = QHBoxLayout()
        ops_bar.addStretch(1)

        self.btn_manage_accounts = QPushButton("Manage Bank Accounts…")
        self.btn_grant_credit = QPushButton("Grant Credit…")

        # Always enabled; _ensure_and_open(...) will save-on-demand if needed
        self.btn_manage_accounts.setEnabled(True)
        self.btn_grant_credit.setEnabled(True)

        # Set tooltip text on both buttons
        tooltip_text = "Requires a saved vendor; on first use, we'll save and continue."
        self.btn_manage_accounts.setToolTip(tooltip_text)
        self.btn_grant_credit.setToolTip(tooltip_text)

        # In add mode, we need to ensure the vendor exists first before enabling these actions
        # Emit signals (controller will handle dialogs/DB work)
        # Safe (PySide6): receivers() with SignalInstance is invalid. Use try/except on disconnects.
        try:
            self.btn_manage_accounts.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.btn_manage_accounts.clicked.connect(self._on_manage_accounts_clicked)

        try:
            self.btn_grant_credit.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.btn_grant_credit.clicked.connect(self._on_grant_credit_clicked)

        ops_bar.addWidget(self.btn_manage_accounts)
        ops_bar.addWidget(self.btn_grant_credit)
        lay.addLayout(ops_bar)

        # OK/Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        if initial:
            self.name.setText(initial.get("name", ""))
            self.contact.setPlainText(initial.get("contact_info", ""))
            self.addr.setPlainText(initial.get("address", "") or "")

        self._payload = None

    def _on_manage_accounts_clicked(self):
        self._ensure_and_open("manage_accounts")

    def _on_grant_credit_clicked(self):
        self._ensure_and_open("grant_credit")

    def _ensure_and_open(self, action: str):
        # 1) Validate inputs first
        payload = self.get_payload()  # existing method; must focus invalid fields and return/raise on invalid
        if payload is None:
            return  # invalid; form retains focus as per existing behavior

        # 2) If vendor not yet created, request ensureVendorExists
        if getattr(self, "_vendor_id", None) is None:
            # Controller will create and call back set_vendor_id
            self.ensureVendorExists.emit(payload)
            if getattr(self, "_vendor_id", None) is None:
                # Controller failed or user cancelled — stay put
                return

        # 3) Fire the existing, already-wired signals for the action
        if action == "manage_accounts" and hasattr(self, "manageBankAccounts"):
            self.manageBankAccounts.emit(self._vendor_id)
        elif action == "grant_credit" and hasattr(self, "grantVendorCredit"):
            self.grantVendorCredit.emit(self._vendor_id)

    def set_vendor_id(self, vendor_id: int) -> None:
        """Enable operational actions once a vendor record exists (optional helper)."""
        self._vendor_id = int(vendor_id)
        self.btn_manage_accounts.setEnabled(True)
        self.btn_grant_credit.setEnabled(True)

    def get_payload(self) -> dict | None:
        if not non_empty(self.name.text()):
            self.name.setFocus(); return None
        if not non_empty(self.contact.toPlainText()):
            self.contact.setFocus(); return None
        return {
            "name": self.name.text().strip(),
            "contact_info": self.contact.toPlainText().strip(),
            "address": (self.addr.toPlainText().strip() or None)
        }

    def accept(self):
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload
