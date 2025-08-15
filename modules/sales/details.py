from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel
from ...utils.helpers import fmt_money

class SaleDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Sale Details")
        f = QFormLayout(box)

        self.lab_id = QLabel("-")
        self.lab_date = QLabel("-")
        self.lab_customer = QLabel("-")

        self.lab_total = QLabel("-")
        self.lab_discount = QLabel("-")
        self.lab_total_discount = QLabel("-")

        # New: returns summary + net after returns
        self.lab_returned_qty = QLabel("-")
        self.lab_returned_val = QLabel("-")
        self.lab_net_after = QLabel("-")

        self.lab_paid = QLabel("-")
        self.lab_remain = QLabel("-")
        self.lab_status = QLabel("-")

        f.addRow("ID:", self.lab_id)
        f.addRow("Date:", self.lab_date)
        f.addRow("Customer:", self.lab_customer)
        f.addRow("Total:", self.lab_total)
        f.addRow("Order Discount:", self.lab_discount)
        f.addRow("Total Discount:", self.lab_total_discount)
        f.addRow("Returned Qty:", self.lab_returned_qty)
        f.addRow("Returned Value:", self.lab_returned_val)
        f.addRow("Net (after returns):", self.lab_net_after)
        f.addRow("Paid:", self.lab_paid)
        f.addRow("Remaining:", self.lab_remain)
        f.addRow("Status:", self.lab_status)

        root = QVBoxLayout(self)
        root.addWidget(box)

    def set_data(self, r: dict | None):
        if not r:
            for w in (
                self.lab_id, self.lab_date, self.lab_customer,
                self.lab_total, self.lab_discount, self.lab_total_discount,
                self.lab_returned_qty, self.lab_returned_val, self.lab_net_after,
                self.lab_paid, self.lab_remain, self.lab_status
            ):
                w.setText("-")
            return

        self.lab_id.setText(r["sale_id"])
        self.lab_date.setText(r["date"])
        self.lab_customer.setText(r["customer_name"])

        self.lab_total.setText(fmt_money(r["total_amount"]))
        self.lab_discount.setText(fmt_money(r["order_discount"]))
        self.lab_total_discount.setText(fmt_money(r.get("overall_discount", 0.0)))

        # New: returns summary + net after returns
        self.lab_returned_qty.setText(f'{float(r.get("returned_qty", 0.0)):g}')
        self.lab_returned_val.setText(fmt_money(r.get("returned_value", 0.0)))
        self.lab_net_after.setText(fmt_money(r.get("net_after_returns", 0.0)))

        self.lab_paid.setText(fmt_money(r["paid_amount"]))
        self.lab_remain.setText(fmt_money(float(r["total_amount"]) - float(r["paid_amount"])))
        self.lab_status.setText(r["payment_status"])
