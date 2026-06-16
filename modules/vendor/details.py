# ⚠️ VENDOR MODULE ONLY: Do not modify other modules or shared components. Credit label addition only.
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout
from PySide6.QtCore import Qt


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return getattr(obj, key)
    except Exception:
        try:
            return obj[key]
        except Exception:
            return default

class VendorDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Vendor Details")
        f = QFormLayout(box)
        self.lab_id = QLabel("No vendor selected")
        self.lab_name = QLabel("-")
        self.lab_name.setWordWrap(True)
        self.lab_contact = QLabel("-")
        self.lab_contact.setWordWrap(True)
        self.lab_address = QLabel("-")
        self.lab_address.setWordWrap(True)
        self.lblAvailableAdvanceValue = QLabel("0.00")
        self.lblAvailableAdvanceValue.setObjectName("lblAvailableAdvance")
        self.lblAvailableAdvanceValue.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.addRow("Vendor ID:", self.lab_id)
        f.addRow("Name:", self.lab_name)
        f.addRow("Contact:", self.lab_contact)
        f.addRow("Address:", self.lab_address)
        f.addRow("Available Advance:", self.lblAvailableAdvanceValue)

        root = QVBoxLayout(self)
        root.addWidget(box, 1)

    def clear(self):
        self.lab_id.setText("No vendor selected")
        self.lab_name.setText("-")
        self.lab_contact.setText("-")
        self.lab_address.setText("-")
        self.lblAvailableAdvanceValue.setText("-")
        self.lblAvailableAdvanceValue.setToolTip("")
        self.lblAvailableAdvanceValue.setStyleSheet("")

    def set_data(self, vendor: dict | None):
        if not vendor:
            self.clear(); return
        vendor_id = _get(vendor, "vendor_id")
        self.lab_id.setText(f"Vendor #{vendor_id}" if vendor_id is not None else "-")
        self.lab_name.setText(_get(vendor, "name") or "-")
        self.lab_contact.setText(_get(vendor, "contact_info") or "-")
        self.lab_address.setText(_get(vendor, "address") or "-")

    def set_credit(self, amount: float) -> None:
        try:
            val = 0.0 if amount is None else float(amount)
        except Exception:
            val = 0.0
        self.lblAvailableAdvanceValue.setToolTip("")
        self.lblAvailableAdvanceValue.setStyleSheet("")
        self.lblAvailableAdvanceValue.setText(f"{val:,.2f}")

    def set_credit_error(self, message: str) -> None:
        self.lblAvailableAdvanceValue.setText("Unavailable")
        self.lblAvailableAdvanceValue.setToolTip(message)
        self.lblAvailableAdvanceValue.setStyleSheet("color:#b00020; font-weight:600;")
