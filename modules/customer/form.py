from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QLineEdit, QPlainTextEdit
from ...utils.validators import non_empty

class CustomerForm(QDialog):
    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Customer")
        self.setModal(True)

        self.name = QLineEdit()
        self.contact = QPlainTextEdit()
        self.contact.setPlaceholderText("Phone, email, etc.")
        self.addr = QPlainTextEdit()
        self.addr.setPlaceholderText("Address (optional)")

        form = QFormLayout()
        form.addRow("Name*", self.name)
        form.addRow("Contact Info*", self.contact)
        form.addRow("Address", self.addr)

        root = QVBoxLayout(self)
        root.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        if initial:
            self.name.setText(initial.get("name",""))
            self.contact.setPlainText(initial.get("contact_info",""))
            self.addr.setPlainText(initial.get("address","") or "")

        self._payload = None

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
        if p is None: return
        self._payload = p
        super().accept()

    def payload(self): return self._payload
