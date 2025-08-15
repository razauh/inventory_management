from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel
from PySide6.QtCore import Qt
from ...utils.helpers import fmt_money

class PurchaseDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Purchase Details")
        f = QFormLayout(box)
        self.lab_id = QLabel("-")
        self.lab_date = QLabel("-")
        self.lab_vendor = QLabel("-")
        self.lab_total = QLabel("-")
        self.lab_discount = QLabel("-")
        self.lab_paid = QLabel("-")
        self.lab_remain = QLabel("-")
        self.lab_status = QLabel("-")
        # Removed notes label as per update
        f.addRow("ID:", self.lab_id)
        f.addRow("Date:", self.lab_date)
        f.addRow("Vendor:", self.lab_vendor)
        f.addRow("Total:", self.lab_total)
        f.addRow("Order Discount:", self.lab_discount)
        f.addRow("Paid:", self.lab_paid)
        f.addRow("Remaining:", self.lab_remain)
        f.addRow("Status:", self.lab_status)
        # Removed notes row as per update
        root = QVBoxLayout(self)
        root.addWidget(box, 0)
        
    def set_data(self, row: dict | None):
        if not row:
            for w in (self.lab_id, self.lab_date, self.lab_vendor, self.lab_total,
                      self.lab_discount, self.lab_paid, self.lab_remain, self.lab_status):
                w.setText("-")
            return
            
        self.lab_id.setText(row["purchase_id"])
        self.lab_date.setText(row["date"])
        self.lab_vendor.setText(row["vendor_name"])
        self.lab_total.setText(fmt_money(row["total_amount"]))
        self.lab_discount.setText(f'{float(row["order_discount"]):g}')
        self.lab_paid.setText(fmt_money(row["paid_amount"]))
        remaining = float(row["total_amount"]) - float(row["paid_amount"])
        self.lab_remain.setText(fmt_money(remaining))
        self.lab_status.setText(row["payment_status"])
        # Notes are no longer displayed as per update