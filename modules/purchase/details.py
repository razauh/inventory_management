from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel
from PySide6.QtCore import Qt
from ...utils.helpers import fmt_money

class PurchaseDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        box = QGroupBox("Purchase Summary")
        f = QFormLayout(box)
        self.lab_id = QLabel("-")
        self.lab_date = QLabel("-")
        self.lab_vendor = QLabel("-")
        self.lab_total = QLabel("-")
        self.lab_paid = QLabel("-")
        self.lab_remain = QLabel("-")
        self.lab_status = QLabel("-")
        # Payment info fields added to main summary
        self.lblPayMethod = QLabel("—")
        self.lblPayAmount = QLabel("—")
        self.lblPayStatus = QLabel("—")
        self.lblOverpay = QLabel("—")
        self.lblOverpay.setObjectName("overpayLabel")
        self.lblOverpay.setStyleSheet("color: #0a7;")

        f.addRow("ID:", self.lab_id)
        f.addRow("Date:", self.lab_date)
        f.addRow("Vendor:", self.lab_vendor)
        f.addRow("Total:", self.lab_total)
        f.addRow("Paid:", self.lab_paid)
        f.addRow("Remaining:", self.lab_remain)
        f.addRow("Status:", self.lab_status)
        f.addRow("Method:", self.lblPayMethod)
        f.addRow("Last Payment:", self.lblPayAmount)
        f.addRow("Payment Status:", self.lblPayStatus)
        f.addRow("Overpayment:", self.lblOverpay)

        root = QVBoxLayout(self)
        root.addWidget(box, 0)

    def set_data(self, row: dict | None):
        if not row:
            self.clear_data()
            return

        purchase_id = row.get("purchase_id", "-")
        purchase_id = purchase_id if purchase_id else "-"
        self.lab_id.setText(str(purchase_id))
        
        date = row.get("date", "-")
        date = date if date else "-"
        self.lab_date.setText(str(date))
        
        vendor_name = row.get("vendor_name", "-")
        vendor_name = vendor_name if vendor_name else "-"
        self.lab_vendor.setText(str(vendor_name))
        
        try:
            total_amount = float(row.get("total_amount", 0.0))
        except (TypeError, ValueError):
            total_amount = 0.0
        self.lab_total.setText(fmt_money(total_amount))
        
        try:
            paid_amount = float(row.get("paid_amount", 0.0))
        except (TypeError, ValueError):
            paid_amount = 0.0
        self.lab_paid.setText(fmt_money(paid_amount))
        
        try:
            advance_payment_applied = float(row.get("advance_payment_applied", 0.0))
        except (TypeError, ValueError):
            advance_payment_applied = 0.0
            
        remaining = total_amount - paid_amount - advance_payment_applied
        self.lab_remain.setText(fmt_money(remaining))
        
        payment_status = row.get("payment_status", "-")
        payment_status = payment_status if payment_status else "-"
        self.lab_status.setText(str(payment_status))

    def clear_data(self):
        for w in (
            self.lab_id,
            self.lab_date,
            self.lab_vendor,
            self.lab_total,
            self.lab_paid,
            self.lab_remain,
            self.lab_status,
        ):
            w.setText("-")

    def clear_payment_summary(self):
        self.lblPayMethod.setText("—")
        self.lblPayAmount.setText("—")
        self.lblPayStatus.setText("—")
        self.lblOverpay.setText("—")

    def set_payment_summary(self, data: dict | None):
        if not data:
            self.clear_payment_summary()
            return
        method = data.get("method") or "—"
        method = method if method else "—"
        self.lblPayMethod.setText(str(method))
        
        amount = data.get("amount", 0.0)
        self.lblPayAmount.setText(f'{float(amount or 0.0):.2f}')
        
        status = data.get("status") or "—"
        status = status if status else "—"
        self.lblPayStatus.setText(str(status))
        
        over = float(data.get("overpayment", 0.0) or 0.0)
        if over > 0:
            ent = data.get("counterparty_label") or "Vendor"
            ent = ent if ent else "Vendor"
            self.lblOverpay.setText(f"{over:.2f} — Excess credited to {str(ent)} account")
        else:
            self.lblOverpay.setText("—")
