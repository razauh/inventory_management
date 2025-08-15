from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel

class CustomerDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Customer Details")
        f = QFormLayout(box)
        self.lab_id = QLabel("-")
        self.lab_name = QLabel("-")
        self.lab_contact = QLabel("-")
        self.lab_address = QLabel("-")
        self.lab_address.setWordWrap(True)
        f.addRow("ID:", self.lab_id)
        f.addRow("Name:", self.lab_name)
        f.addRow("Contact:", self.lab_contact)
        f.addRow("Address:", self.lab_address)

        root = QVBoxLayout(self)
        root.addWidget(box)

    def clear(self):
        self.lab_id.setText("-")
        self.lab_name.setText("-")
        self.lab_contact.setText("-")
        self.lab_address.setText("-")

    def set_data(self, row: dict | None):
        if not row:
            self.clear(); return
        self.lab_id.setText(str(row["customer_id"]))
        self.lab_name.setText(row["name"] or "")
        self.lab_contact.setText(row["contact_info"] or "")
        self.lab_address.setText(row.get("address") or "")
