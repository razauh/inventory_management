# ⚠️ VENDOR MODULE ONLY: Do not modify other modules or shared components. Credit label addition only.
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout
from PySide6.QtCore import Qt

class VendorDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Vendor Details")
        f = QFormLayout(box)
        self.lab_id = QLabel("-")
        self.lab_name = QLabel("-")
        self.lab_contact = QLabel("-")
        self.lab_address = QLabel("-")
        self.lab_address.setWordWrap(True)
        self.lblAvailableAdvanceValue = QLabel("0.00")
        self.lblAvailableAdvanceValue.setObjectName("lblAvailableAdvance")
        self.lblAvailableAdvanceValue.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.addRow("ID:", self.lab_id)
        f.addRow("Name:", self.lab_name)
        f.addRow("Contact:", self.lab_contact)
        f.addRow("Address:", self.lab_address)
        f.addRow("Available Advance:", self.lblAvailableAdvanceValue)

        root = QVBoxLayout(self)
        root.addWidget(box, 1)

    def clear(self):
        self.lab_id.setText("-")
        self.lab_name.setText("-")
        self.lab_contact.setText("-")
        self.lab_address.setText("-")

    def set_data(self, vendor: dict | None):
        if not vendor:
            self.clear(); return
        self.lab_id.setText(str(vendor["vendor_id"]))
        self.lab_name.setText(vendor["name"] or "")
        self.lab_contact.setText(vendor["contact_info"] or "")
        self.lab_address.setText(vendor.get("address") or "")

    def set_credit(self, amount: float) -> None:
        # Defensive: normalize None/invalid to 0.00
        try:
            val = 0.0 if amount is None else float(amount)
        except Exception:
            val = 0.0
        # Two-decimal formatting (thousands separators if you prefer)
        self.lblAvailableAdvanceValue.setText(f"{val:,.2f}")
