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

        f.addRow("ID:", self.lab_id)
        f.addRow("Date:", self.lab_date)
        f.addRow("Vendor:", self.lab_vendor)
        f.addRow("Total:", self.lab_total)
        f.addRow("Order Discount:", self.lab_discount)
        f.addRow("Paid:", self.lab_paid)
        f.addRow("Remaining:", self.lab_remain)
        f.addRow("Status:", self.lab_status)

        # --- Payment Summary panel ---
        self.grpPaymentSummary = QGroupBox("Payment Summary", self)
        self.frmPaymentSummary = QFormLayout(self.grpPaymentSummary)
        self.lblPayMethod = QLabel("—")
        self.lblPayAmount = QLabel("—")
        self.lblPayStatus = QLabel("—")
        self.lblOverpay = QLabel("—")
        self.lblOverpay.setObjectName("overpayLabel")
        self.lblOverpay.setStyleSheet("color: #0a7;")

        self.frmPaymentSummary.addRow("Method", self.lblPayMethod)
        self.frmPaymentSummary.addRow("Amount Paid", self.lblPayAmount)
        self.frmPaymentSummary.addRow("Payment Status", self.lblPayStatus)
        self.frmPaymentSummary.addRow("Overpayment", self.lblOverpay)

        root = QVBoxLayout(self)
        root.addWidget(box, 0)
        root.addWidget(self.grpPaymentSummary, 0)

    def set_data(self, row: dict | None):
        if not row:
            for w in (
                self.lab_id,
                self.lab_date,
                self.lab_vendor,
                self.lab_total,
                self.lab_discount,
                self.lab_paid,
                self.lab_remain,
                self.lab_status,
            ):
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

    def clear_payment_summary(self):
        self.lblPayMethod.setText("—")
        self.lblPayAmount.setText("—")
        self.lblPayStatus.setText("—")
        self.lblOverpay.setText("—")

    def set_payment_summary(self, data: dict | None):
        if not data:
            self.clear_payment_summary()
            return
        self.lblPayMethod.setText(data.get("method") or "—")
        self.lblPayAmount.setText(f'{float(data.get("amount", 0.0)):.2f}')
        self.lblPayStatus.setText(data.get("status") or "—")
        over = float(data.get("overpayment", 0.0) or 0.0)
        if over > 0:
            ent = data.get("counterparty_label") or "Vendor"
            self.lblOverpay.setText(f"{over:.2f} — Excess credited to {ent} account")
        else:
            self.lblOverpay.setText("—")
