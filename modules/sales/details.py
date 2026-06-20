import logging

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHBoxLayout,
    QRadioButton,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal
from ...utils.helpers import fmt_money
from ...utils.ui_helpers import info


class SaleDetails(QWidget):
    """
    Read-only panel showing the selected sale’s/quotation’s header facts, returns summary
    (hidden for quotations), a compact payments list (hidden for quotations), and the
    customer’s credit balance (if provided).

    Expected keys in set_data(dict):
      sale_id, date, customer_name, gross_total_amount, order_discount,
      overall_discount, returned_qty, returned_value, net_total_amount,
      paid_amount, advance_payment_applied, remaining_due, payment_status,
      doc_type ('sale' | 'quotation'),
      (optional) payments: list[dict] with columns such as date, method, amount,
                           clearing_state, ref_no/instrument_no, bank_name/account_title/account_no/bank_account_id
      (optional) customer_credit_balance: float
    """
    # Emitted when user requests a state change for a pending payment
    # Args: payment_id (int), new_state ('cleared' | 'bounced')
    paymentStatusChangeRequested = Signal(int, str)

    # Methods that can produce pending payments where clearing_state can change
    PENDING_METHODS = {
        "bank transfer",
        "card",
        "cheque",
        "cross cheque",
        "cash deposit",
        "other",
    }

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
        self.lab_credit_applied = QLabel("-")
        self.lab_return_credit = QLabel("-")
        self.lab_remain = QLabel("-")
        self.lab_status = QLabel("-")

        # Optional: customer credit balance
        self.lab_credit = QLabel("-")

        f.addRow("ID:", self.lab_id)
        f.addRow("Date:", self.lab_date)
        f.addRow("Customer:", self.lab_customer)
        f.addRow("Gross Total:", self.lab_total)
        f.addRow("Order Discount:", self.lab_discount)
        f.addRow("Total Discount:", self.lab_total_discount)
        f.addRow("Returned Qty:", self.lab_returned_qty)
        f.addRow("Returns:", self.lab_returned_val)
        f.addRow("Net Total:", self.lab_net_after)
        f.addRow("Paid:", self.lab_paid)
        f.addRow("Credit Applied:", self.lab_credit_applied)
        f.addRow("Return Credit:", self.lab_return_credit)
        f.addRow("Due:", self.lab_remain)
        f.addRow("Status:", self.lab_status)
        f.addRow("Customer Credit:", self.lab_credit)

        self._form = f  # keep a handle for row visibility control

        # --- Payments list (compact, read-only) -----------------------------
        self.pay_box = QGroupBox("Payments")
        pay_layout = QVBoxLayout(self.pay_box)

        self.tbl_payments = QTableWidget(0, 7)
        self.tbl_payments.setAccessibleName("Payments for selected sale")
        self.tbl_payments.setAccessibleDescription(
            "Select a payment to hear audit details or change a pending payment state."
        )
        self.tbl_payments.setHorizontalHeaderLabels([
            "ID", "Date", "Method", "Amount", "State", "Ref #", "Bank"
        ])
        self.tbl_payments.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_payments.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_payments.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_payments.verticalHeader().setVisible(False)
        self.tbl_payments.setAlternatingRowColors(True)
        pay_layout.addWidget(self.tbl_payments)
        self.lbl_payment_audit_detail = QLabel("Select a payment to view audit details.")
        self.lbl_payment_audit_detail.setWordWrap(True)
        self.lbl_payment_audit_detail.setStyleSheet("color: #555555;")
        pay_layout.addWidget(self.lbl_payment_audit_detail)

        # Payment status update controls (only visible when there is a pending payment)
        self._pending_payment_id: int | None = None
        self._current_sale_id: str | None = None
        self._payment_rows: list[dict] = []
        self._payments_are_for_sale: bool = False
        self._apply_state_wired: bool = False
        self.update_box = QWidget()
        upd_layout = QHBoxLayout(self.update_box)
        upd_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_payment_state_preview = QLabel("")
        self.lbl_payment_state_preview.setWordWrap(True)
        upd_layout.addWidget(self.lbl_payment_state_preview, 2)
        upd_layout.addWidget(QLabel("Change to:"))
        self.rb_cleared = QRadioButton("Cleared")
        self.rb_bounced = QRadioButton("Bounced")
        self.rb_cleared.setAccessibleName("Mark selected payment cleared")
        self.rb_bounced.setAccessibleName("Mark selected payment bounced")
        upd_layout.addWidget(self.rb_cleared)
        upd_layout.addWidget(self.rb_bounced)
        self.btn_apply_state = QPushButton("Apply")
        self.btn_apply_state.setAccessibleName("Apply payment state change")
        self.btn_apply_state.setAccessibleDescription(
            "Apply the selected cleared or bounced state to the pending payment."
        )
        upd_layout.addWidget(self.btn_apply_state)
        upd_layout.addStretch(1)
        pay_layout.addWidget(self.update_box)
        self.update_box.setVisible(False)

        self.btn_apply_state.clicked.connect(self._on_apply_status_clicked)
        self.tbl_payments.itemSelectionChanged.connect(self._on_payment_selected)

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
            self.lab_paid, self.lab_credit_applied, self.lab_return_credit, self.lab_remain,
            self.lab_status, self.lab_credit
        ):
            w.setText("-")
        self._load_payments([])
        # Default to 'sale' visibility when nothing is selected
        self._apply_doc_type_visibility("sale")
        self._pending_payment_id = None
        self._current_sale_id = None
        self._payment_rows = []
        self._payments_are_for_sale = False
        self.update_box.setVisible(False)
        self.rb_cleared.setChecked(False)
        self.rb_bounced.setChecked(False)
        self.btn_apply_state.setEnabled(False)
        self.lbl_payment_state_preview.clear()
        self.lbl_payment_audit_detail.setText("Select a payment to view audit details.")

    def _load_payments(self, rows: list[dict]):
        """Populate the compact payments table from a list of dict-like rows."""
        self._payment_rows = rows
        self.tbl_payments.blockSignals(True)
        self.tbl_payments.clearSelection()
        self.tbl_payments.setRowCount(0)
        if not rows:
            self.tbl_payments.blockSignals(False)
            return

        def _text(x) -> str:
            return "" if x is None else str(x)

        for r, row in enumerate(rows):
            self.tbl_payments.insertRow(r)

            self.tbl_payments.setItem(r, 0, self._cell(_text(row.get("payment_id"))))

            # Date
            date = row.get("date") or row.get("tx_date") or ""
            self.tbl_payments.setItem(r, 1, self._cell(_text(date)))

            # Method
            method = row.get("method", "")
            self.tbl_payments.setItem(r, 2, self._cell(_text(method)))

            # Amount (±)
            try:
                amt_val = float(row.get("amount", 0.0) or 0.0)
            except Exception:
                amt_val = 0.0
            amt_cell = self._cell(fmt_money(amt_val))
            if amt_val < 0:
                amt_cell.setForeground(Qt.red)  # subtle hint for refunds
            self.tbl_payments.setItem(r, 3, amt_cell)

            # State
            state = row.get("clearing_state", "")
            self.tbl_payments.setItem(r, 4, self._cell(_text(state)))

            # Ref #
            ref = row.get("ref_no") or row.get("instrument_no") or ""
            self.tbl_payments.setItem(r, 5, self._cell(_text(ref)))

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
            self.tbl_payments.setItem(r, 6, self._cell(bank_label))

        self.tbl_payments.resizeColumnsToContents()
        self.tbl_payments.blockSignals(False)

    def _on_payment_selected(self):
        self._pending_payment_id = None
        preview = ""
        audit_detail = "Select a payment to view audit details."
        selected = self.tbl_payments.selectionModel().selectedRows()
        if selected and self._payments_are_for_sale:
            row_index = selected[0].row()
            if 0 <= row_index < len(self._payment_rows):
                row = self._payment_rows[row_index]
                state = str(row.get("clearing_state") or "").lower()
                method = str(row.get("method") or "").lower()
                payment_id = row.get("payment_id") or "-"
                ref = row.get("ref_no") or row.get("instrument_no") or "-"
                notes = str(row.get("notes") or "No notes")
                audit_detail = (
                    f"Payment #{payment_id} | Ref: {ref} | Notes: {notes}"
                )
                if state == "pending" and method in self.PENDING_METHODS:
                    try:
                        self._pending_payment_id = int(row.get("payment_id"))
                        amount = fmt_money(float(row.get("amount", 0.0) or 0.0))
                        method_label = str(row.get("method") or "Unknown")
                        preview = (
                            f"Sale {self._current_sale_id or '-'} | "
                            f"Payment #{self._pending_payment_id} | "
                            f"{method_label} | {amount} | Current state: Pending"
                        )
                    except (TypeError, ValueError):
                        self._pending_payment_id = None

        can_update = self._pending_payment_id is not None
        self.update_box.setVisible(can_update)
        self.rb_cleared.setChecked(False)
        self.rb_bounced.setChecked(False)
        self.rb_cleared.setEnabled(can_update)
        self.rb_bounced.setEnabled(can_update)
        self.btn_apply_state.setEnabled(False)
        self.lbl_payment_state_preview.setText(preview)
        self.lbl_payment_audit_detail.setText(audit_detail)

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
        self._current_sale_id = str(r.get("sale_id") or "") or None
        self.lab_id.setText(r.get("sale_id", "-"))
        self.lab_date.setText(r.get("date", "-"))
        self.lab_customer.setText(r.get("customer_name", "-"))

        # Money (header-level)
        gross_total = float(
            r.get("gross_total_amount", r.get("total_amount", 0.0)) or 0.0
        )
        order_discount = float(r.get("order_discount", 0.0) or 0.0)
        paid_amount = float(r.get("paid_amount", 0.0) or 0.0)
        credit_applied = float(r.get("advance_payment_applied", 0.0) or 0.0)
        return_credit = float(r.get("return_credit_amount", 0.0) or 0.0)
        net_total = float(
            r.get(
                "net_total_amount",
                r.get("calculated_total_amount", r.get("net_after_returns", 0.0)),
            )
            or 0.0
        )
        remaining_due = float(r.get("remaining_due", 0.0) or 0.0)

        self.lab_total.setText(fmt_money(gross_total))
        self.lab_discount.setText(fmt_money(order_discount))
        self.lab_total_discount.setText(fmt_money(r.get("overall_discount", 0.0)))

        # Returns summary
        self.lab_returned_qty.setText(f"{float(r.get('returned_qty', 0.0) or 0.0):g}")
        self.lab_returned_val.setText(fmt_money(r.get("returned_value", 0.0)))
        self.lab_net_after.setText(fmt_money(net_total))

        # Settlement summary
        self.lab_paid.setText(fmt_money(paid_amount))
        self.lab_credit_applied.setText(fmt_money(credit_applied))
        self.lab_return_credit.setText(fmt_money(return_credit))
        self.lab_remain.setText(fmt_money(remaining_due))
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
        self._payments_are_for_sale = str(r.get("doc_type", "sale")).lower() == "sale"
        self._load_payments(norm_rows)
        self._pending_payment_id = None
        self.lbl_payment_state_preview.clear()
        self.lbl_payment_audit_detail.setText("Select a payment to view audit details.")
        self.update_box.setVisible(False)
        self.rb_cleared.setChecked(False)
        self.rb_bounced.setChecked(False)
        self.rb_cleared.setEnabled(False)
        self.rb_bounced.setEnabled(False)
        self.btn_apply_state.setEnabled(False)

        # Tie Apply button enablement to radio selection when pending exists.
        # Wire signals only once to avoid accumulating connections.
        if not self._apply_state_wired:
            def _update_apply_enabled():
                enabled = self._pending_payment_id is not None and (
                    self.rb_cleared.isChecked() or self.rb_bounced.isChecked()
                )
                self.btn_apply_state.setEnabled(enabled)

            self.rb_cleared.toggled.connect(lambda _=None: _update_apply_enabled())
            self.rb_bounced.toggled.connect(lambda _=None: _update_apply_enabled())
            self._apply_state_wired = True

    # ----------------------------------------------------------------------

    def _on_apply_status_clicked(self):
        if not self._pending_payment_id:
            return
        new_state = None
        if self.rb_cleared.isChecked():
            new_state = "cleared"
        elif self.rb_bounced.isChecked():
            new_state = "bounced"
        if not new_state:
            return
        # Emit only; any exceptions from slots should propagate.
        # The receiver is responsible for refreshing the view and updating/hiding
        # the controls once the status change succeeds.
        self.paymentStatusChangeRequested.emit(self._pending_payment_id, new_state)
