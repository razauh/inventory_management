from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)


class CompanyInfoForm(QDialog):
    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Company Info")
        self._payload = None
        initial = initial or {}

        self.company_name = QLineEdit(initial.get("company_name") or "")
        self.address_line1 = QLineEdit(initial.get("address_line1") or initial.get("address") or "")
        self.address_line2 = QLineEdit(initial.get("address_line2") or "")
        self.city = QLineEdit(initial.get("city") or "")
        self.state_region = QLineEdit(initial.get("state_region") or "")
        self.postal_code = QLineEdit(initial.get("postal_code") or "")
        self.country = QLineEdit(initial.get("country") or "")
        self.phone = QLineEdit(initial.get("phone") or "")
        self.email = QLineEdit(initial.get("email") or "")
        self.website = QLineEdit(initial.get("website") or "")
        self.tax_number = QLineEdit(initial.get("tax_number") or "")
        self.logo_path = QLineEdit(initial.get("logo_path") or "")
        self.footer = QLineEdit(initial.get("invoice_footer_note") or "")
        self.terms = QTextEdit(initial.get("terms_text") or "")
        self.is_active = QCheckBox("Active")
        self.is_active.setChecked(bool(initial.get("is_active", 1)))

        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_path, 1)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_logo)
        logo_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Company Name*", self.company_name)
        form.addRow("Address Line 1", self.address_line1)
        form.addRow("Address Line 2", self.address_line2)
        form.addRow("City", self.city)
        form.addRow("State/Region", self.state_region)
        form.addRow("Postal Code", self.postal_code)
        form.addRow("Country", self.country)
        form.addRow("Phone", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Website", self.website)
        form.addRow("Tax/NTN/Reg No", self.tax_number)
        form.addRow("Logo Path", logo_row)
        form.addRow("Invoice Footer", self.footer)
        form.addRow("Terms", self.terms)
        form.addRow("", self.is_active)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

    def _browse_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Logo",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
        )
        if path:
            self.logo_path.setText(path)

    def accept(self):
        name = self.company_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Company name is required.")
            return
        self._payload = {
            "company_name": name,
            "address_line1": self.address_line1.text().strip(),
            "address_line2": self.address_line2.text().strip(),
            "city": self.city.text().strip(),
            "state_region": self.state_region.text().strip(),
            "postal_code": self.postal_code.text().strip(),
            "country": self.country.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),
            "website": self.website.text().strip(),
            "tax_number": self.tax_number.text().strip(),
            "logo_path": self.logo_path.text().strip(),
            "invoice_footer_note": self.footer.text().strip(),
            "terms_text": self.terms.toPlainText().strip(),
            "is_active": 1 if self.is_active.isChecked() else 0,
        }
        super().accept()

    def payload(self):
        return self._payload


class BankAccountForm(QDialog):
    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Company Bank Account")
        self._payload = None
        initial = initial or {}

        self.label = QLineEdit(initial.get("label") or "")
        self.bank_name = QLineEdit(initial.get("bank_name") or "")
        self.account_no = QLineEdit(initial.get("account_no") or "")
        self.iban = QLineEdit(initial.get("iban") or "")
        self.branch_name = QLineEdit(initial.get("branch_name") or "")
        self.routing_no = QLineEdit(initial.get("routing_no") or "")
        self.swift_code = QLineEdit(initial.get("swift_code") or "")
        self.notes = QLineEdit(initial.get("notes") or "")
        self.is_primary = QCheckBox("Primary")
        self.is_primary.setChecked(bool(initial.get("is_primary", 0)))
        self.is_active = QCheckBox("Active")
        self.is_active.setChecked(bool(initial.get("is_active", 1)))

        form = QFormLayout()
        form.addRow("Account Title*", self.label)
        form.addRow("Bank Name", self.bank_name)
        form.addRow("Account No", self.account_no)
        form.addRow("IBAN", self.iban)
        form.addRow("Branch Name/Code", self.branch_name)
        form.addRow("Routing No", self.routing_no)
        form.addRow("SWIFT Code", self.swift_code)
        form.addRow("Notes", self.notes)
        form.addRow("", self.is_primary)
        form.addRow("", self.is_active)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

    def accept(self):
        label = self.label.text().strip()
        if not label:
            QMessageBox.warning(self, "Required", "Account title is required.")
            return
        if self.is_primary.isChecked() and not self.is_active.isChecked():
            QMessageBox.warning(self, "Invalid", "Primary bank account must be active.")
            return
        self._payload = {
            "label": label,
            "bank_name": self.bank_name.text().strip(),
            "account_no": self.account_no.text().strip(),
            "iban": self.iban.text().strip(),
            "branch_name": self.branch_name.text().strip(),
            "routing_no": self.routing_no.text().strip(),
            "swift_code": self.swift_code.text().strip(),
            "notes": self.notes.text().strip(),
            "is_primary": 1 if self.is_primary.isChecked() else 0,
            "is_active": 1 if self.is_active.isChecked() else 0,
        }
        super().accept()

    def payload(self):
        return self._payload


class ProprietorForm(QDialog):
    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Company Proprietor")
        self._payload = None
        initial = initial or {}

        self.name = QLineEdit(initial.get("name") or "")
        self.phone = QLineEdit(initial.get("phone") or "")
        self.sort_order = QSpinBox()
        self.sort_order.setRange(0, 999)
        self.sort_order.setValue(int(initial.get("sort_order") or 0))
        self.is_active = QCheckBox("Active")
        self.is_active.setChecked(bool(initial.get("is_active", 1)))

        form = QFormLayout()
        form.addRow("Name*", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Order", self.sort_order)
        form.addRow("", self.is_active)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

    def accept(self):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Proprietor name is required.")
            return
        self._payload = {
            "name": name,
            "phone": self.phone.text().strip(),
            "sort_order": self.sort_order.value(),
            "is_active": 1 if self.is_active.isChecked() else 0,
        }
        super().accept()

    def payload(self):
        return self._payload
