from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel


class CustomerDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Basic info ---
        box_basic = QGroupBox("Customer Details")
        f_basic = QFormLayout(box_basic)

        self.lab_id = QLabel("-")
        self.lab_name = QLabel("-")
        self.lab_contact = QLabel("-")
        self.lab_address = QLabel("-")
        self.lab_address.setWordWrap(True)

        f_basic.addRow("ID:", self.lab_id)
        f_basic.addRow("Name:", self.lab_name)
        f_basic.addRow("Contact:", self.lab_contact)
        f_basic.addRow("Address:", self.lab_address)

        # --- Financial snapshot ---
        box_fin = QGroupBox("Financial Snapshot")
        f_fin = QFormLayout(box_fin)

        self.lab_status = QLabel("-")             # Active / Inactive
        self.lab_credit = QLabel("-")             # v_customer_advance_balance
        self.lab_last_sale = QLabel("-")          # last sale date
        self.lab_last_payment = QLabel("-")       # last payment date
        self.lab_outstanding = QLabel("-")        # sum of (total - paid - applied advances), provided by caller

        f_fin.addRow("Status:", self.lab_status)
        f_fin.addRow("Credit Balance:", self.lab_credit)
        f_fin.addRow("Last Sale:", self.lab_last_sale)
        f_fin.addRow("Last Payment:", self.lab_last_payment)
        f_fin.addRow("Outstanding Receivables:", self.lab_outstanding)

        # Root layout
        root = QVBoxLayout(self)
        root.addWidget(box_basic)
        root.addWidget(box_fin)

    # ---------------- helpers ----------------

    @staticmethod
    def _fmt_money(val) -> str:
        if val is None:
            return "-"
        try:
            return f"{float(val):,.2f}"
        except Exception:
            return str(val)

    @staticmethod
    def _fmt_text(val) -> str:
        return "-" if val is None or val == "" else str(val)

    # ---------------- API ----------------

    def clear(self):
        # basic
        self.lab_id.setText("-")
        self.lab_name.setText("-")
        self.lab_contact.setText("-")
        self.lab_address.setText("-")
        # financial
        self.lab_status.setText("-")
        self.lab_credit.setText("-")
        self.lab_last_sale.setText("-")
        self.lab_last_payment.setText("-")
        self.lab_outstanding.setText("-")

    def set_data(self, row: dict | None):
        """
        Expects an optional payload dict (from controller) containing:
          - customer_id, name, contact_info, address
          - is_active (0/1)
          - credit_balance (float)
          - last_sale_date (YYYY-MM-DD or None)
          - last_payment_date (YYYY-MM-DD or None)
          - open_due_sum (float)  # sum over sales: total − paid − applied advances
        All fields are optional; UI falls back gracefully.
        """
        if not row:
            self.clear()
            return

        # Basic
        self.lab_id.setText(self._fmt_text(row.get("customer_id")))
        self.lab_name.setText(self._fmt_text(row.get("name")))
        self.lab_contact.setText(self._fmt_text(row.get("contact_info")))
        self.lab_address.setText(self._fmt_text(row.get("address")))

        # Financial snapshot
        is_active = row.get("is_active")
        status_text = "Active" if (is_active == 1 or is_active is True) else ("Inactive" if is_active is not None else "-")
        self.lab_status.setText(status_text)

        self.lab_credit.setText(self._fmt_money(row.get("credit_balance")))
        self.lab_last_sale.setText(self._fmt_text(row.get("last_sale_date")))
        self.lab_last_payment.setText(self._fmt_text(row.get("last_payment_date")))

        # Outstanding receivables (sum of sales: total − paid − applied advances)
        # Value should be provided by controller/service as 'open_due_sum'.
        self.lab_outstanding.setText(self._fmt_money(row.get("open_due_sum")))
