from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPlainTextEdit, QDialogButtonBox, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import Signal
from ...utils.validators import non_empty


class VendorForm(QDialog):
    # emitted when user wants to manage bank accounts for this vendor
    manageBankAccounts = Signal(int)
    # emitted when user wants to grant credit to this vendor
    grantVendorCredit = Signal(int)

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

        # Disable when creating a new vendor (no id yet)
        enabled = self._vendor_id is not None
        self.btn_manage_accounts.setEnabled(enabled)
        self.btn_grant_credit.setEnabled(enabled)

        # Emit signals (controller will handle dialogs/DB work)
        self.btn_manage_accounts.clicked.connect(
            lambda: self.manageBankAccounts.emit(self._vendor_id)
        )
        self.btn_grant_credit.clicked.connect(
            lambda: self.grantVendorCredit.emit(self._vendor_id)
        )

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
