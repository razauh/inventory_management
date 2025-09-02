from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView
)
from PySide6.QtCore import Qt
from ...utils.helpers import fmt_money


class SaleDetails(QWidget):
    """
    Read-only panel showing the selected sale’s/quotation’s header facts, returns summary
    (hidden for quotations), a compact payments list (hidden for quotations), and the
    customer’s credit balance (if provided).

    Expected keys in set_data(dict):
      sale_id, date, customer_name, total_amount, order_discount, overall_discount,
      returned_qty, returned_value, net_after_returns, paid_amount, payment_status,
      doc_type ('sale' | 'quotation'),
      (optional) payments: list[dict] with columns such as date, method, amount,
                           clearing_state, ref_no/instrument_no, bank_name/account_title/account_no/bank_account_id
      (optional) customer_credit_balance: float
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Sale facts box -------------------------------------------------
        self.box = QGroupBox("Sale Details")
        f = QFormLayout(self.box)

        self.lab_id = QLabel("-")
        self.lab_date = QLabel("-")
        self.lab_customer = QLabel("-")

        self.lab_total = QLabel("-")
        self.lab_discount = QLabel("-")
        self.lab_total_discount = QLabel("-")

        # Returns summary + net after returns
        self.lab_returned_qty = QLabel("-")
        self.lab_returned_val = QLabel("-")
        self.lab_net_after = QLabel("-")

        self.lab_paid = QLabel("-")
        self.lab_remain = QLabel("-")
        self.lab_status = QLabel("-")

        # Optional: customer credit balance
        self.lab_credit = QLabel("-")

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
        f.addRow("Customer Credit:", self.lab_credit)

        self._form = f  # keep a handle for row visibility control

        # --- Payments list (compact, read-only) -----------------------------
        self.pay_box = QGroupBox("Payments (read-only)")
        pay_layout = QVBoxLayout(self.pay_box)

        self.tbl_payments = QTableWidget(0, 6)
        self.tbl_payments.setHorizontalHeaderLabels(["Date", "Method", "Amount", "State", "Ref #", "Bank"])
        self.tbl_payments.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_payments.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_payments.setFocusPolicy(Qt.NoFocus)
        self.tbl_payments.verticalHeader().setVisible(False)
        self.tbl_payments.setAlternatingRowColors(True)
        pay_layout.addWidget(self.tbl_payments)

        # Root layout
        root = QVBoxLayout(self)
        root.addWidget(self.box)
        root.addWidget(self.pay_box)

    # ----------------------------------------------------------------------

    def _reset(self):
        for w in (
            self.lab_id, self.lab_date, self.lab_customer,
            self.lab_total, self.lab_discount, self.lab_total_discount,
            self.lab_returned_qty, self.lab_returned_val, self.lab_net_after,
            self.lab_paid, self.lab_remain, self.lab_status, self.lab_credit
        ):
            w.setText("-")
        self._load_payments([])
        # Default to 'sale' visibility when nothing is selected
        self._apply_doc_type_visibility("sale")

    def _load_payments(self, rows: list[dict]):
        """Populate the compact payments table from a list of dict-like rows."""
        self.tbl_payments.setRowCount(0)
        if not rows:
            return

        def _text(x) -> str:
            return "" if x is None else str(x)

        for r, row in enumerate(rows):
            self.tbl_payments.insertRow(r)

            # Date
            date = row.get("date") or row.get("tx_date") or ""
            self.tbl_payments.setItem(r, 0, self._cell(_text(date)))

            # Method
            method = row.get("method", "")
            self.tbl_payments.setItem(r, 1, self._cell(_text(method)))

            # Amount (±)
            try:
                amt_val = float(row.get("amount", 0.0) or 0.0)
            except Exception:
                amt_val = 0.0
            amt_cell = self._cell(fmt_money(amt_val))
            if amt_val < 0:
                amt_cell.setForeground(Qt.red)  # subtle hint for refunds
            self.tbl_payments.setItem(r, 2, amt_cell)

            # State
            state = row.get("clearing_state", "")
            self.tbl_payments.setItem(r, 3, self._cell(_text(state)))

            # Ref #
            ref = row.get("ref_no") or row.get("instrument_no") or ""
            self.tbl_payments.setItem(r, 4, self._cell(_text(ref)))

            # Bank (best-effort label)
            bank_label = ""
            if row.get("bank_name"):
                acct_bits = []
                if row.get("account_title"):
                    acct_bits.append(row["account_title"])
                if row.get("account_no"):
                    acct_bits.append(f"({row['account_no']})")
                bank_label = f"{row['bank_name']} " + " ".join(acct_bits) if acct_bits else row["bank_name"]
            elif row.get("bank_account_id"):
                bank_label = f"#{row['bank_account_id']}"
            self.tbl_payments.setItem(r, 5, self._cell(bank_label))

        self.tbl_payments.resizeColumnsToContents()

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        return it

    # --- visibility helpers ------------------------------------------------

    def _set_row_visible(self, field_widget: QWidget, visible: bool):
        """Hide/show a row in the QFormLayout by hiding both the value and its label."""
        try:
            label = self._form.labelForField(field_widget)
            if label is not None:
                label.setVisible(visible)
        except Exception:
            pass
        field_widget.setVisible(visible)

    def _apply_doc_type_visibility(self, doc_type: str):
        """
        For quotations: hide returns summary rows and the payments box.
        For sales: show them.
        """
        is_quote = (str(doc_type).lower() == "quotation")
        # Returns rows
        self._set_row_visible(self.lab_returned_qty, not is_quote)
        self._set_row_visible(self.lab_returned_val, not is_quote)
        self._set_row_visible(self.lab_net_after, not is_quote)
        # Payments panel
        self.pay_box.setVisible(not is_quote)

    # ----------------------------------------------------------------------

    def set_data(self, r: dict | None):
        if not r:
            self._reset()
            return

        # Toggle sections based on doc_type
        self._apply_doc_type_visibility(r.get("doc_type", "sale"))

        # Header
        self.lab_id.setText(r.get("sale_id", "-"))
        self.lab_date.setText(r.get("date", "-"))
        self.lab_customer.setText(r.get("customer_name", "-"))

        # Money (header-level)
        total_amount = float(r.get("total_amount", 0.0) or 0.0)
        order_discount = float(r.get("order_discount", 0.0) or 0.0)
        paid_amount = float(r.get("paid_amount", 0.0) or 0.0)

        self.lab_total.setText(fmt_money(total_amount))
        self.lab_discount.setText(fmt_money(order_discount))
        self.lab_total_discount.setText(fmt_money(r.get("overall_discount", 0.0)))

        # Returns summary
        self.lab_returned_qty.setText(f"{float(r.get('returned_qty', 0.0) or 0.0):g}")
        self.lab_returned_val.setText(fmt_money(r.get("returned_value", 0.0)))
        self.lab_net_after.setText(fmt_money(r.get("net_after_returns", 0.0)))

        # Paid / remaining / status
        self.lab_paid.setText(fmt_money(paid_amount))
        self.lab_remain.setText(fmt_money(max(0.0, total_amount - paid_amount)))
        self.lab_status.setText(r.get("payment_status", "-"))

        # Optional: customer credit balance
        if "customer_credit_balance" in r and r["customer_credit_balance"] is not None:
            try:
                self.lab_credit.setText(fmt_money(float(r["customer_credit_balance"])))
            except Exception:
                self.lab_credit.setText(fmt_money(0.0))
        else:
            self.lab_credit.setText("-")

        # Optional: payments list
        payments = r.get("payments") or []
        norm_rows = []
        for row in payments:
            try:
                if isinstance(row, dict):
                    norm_rows.append(row)
                else:
                    norm_rows.append(dict(row))  # sqlite3.Row → dict
            except Exception:
                continue
        self._load_payments(norm_rows)
