import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel, 
    QComboBox, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt
from ...utils.helpers import fmt_money

_log = logging.getLogger(__name__)

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
        self.vlPaymentSummary = QVBoxLayout(self.grpPaymentSummary)  # Changed to QVBoxLayout to allow for dynamic content
        
        # Main payment summary labels
        self.frmPaymentSummary = QFormLayout()
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
        
        self.vlPaymentSummary.addLayout(self.frmPaymentSummary)
        
        # Individual payment details with clearing status controls
        self.paymentControlsLayout = QVBoxLayout()
        self.vlPaymentSummary.addLayout(self.paymentControlsLayout)

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

    def set_individual_payments(self, payments: list[dict], controller):
        """Set individual payment details with clearing status controls."""
        if controller is None:
            _log.error("set_individual_payments called with None controller")
            return
        # Clear existing payment controls - handle all types of layout items
        while self.paymentControlsLayout.count():
            child = self.paymentControlsLayout.takeAt(0)
            if child.widget():
                # If it's a widget, delete it
                child.widget().deleteLater()
            elif child.layout():
                # If it's a layout, recursively clear it and then delete it
                self._clear_and_delete_layout(child.layout())
            # For spacers and other items, they are handled automatically when the parent is deleted
        
        # Always show the section, even if no payments exist
        if not payments:
            no_payments_label = QLabel("No payments recorded for this order")
            no_payments_label.setStyleSheet("font-style: italic; color: #666;")
            self.paymentControlsLayout.addWidget(no_payments_label)
            return
        
        # Add a label indicating this section
        label = QLabel("Individual Payment Status:")
        self.paymentControlsLayout.addWidget(label)
        
        # Add individual payment controls
        for payment in payments:
            payment_layout = QHBoxLayout()
            
            # Payment details - safely read keys and validate amount
            method = payment.get('method', 'Unknown')
            raw_amount = payment.get('amount', 0)
            try:
                amount = float(raw_amount)
            except (TypeError, ValueError):
                amount = 0.0
            payment_details = QLabel(f"{method} - {amount:.2f}")
            payment_layout.addWidget(payment_details)
            
            # Clearing status dropdown - only enabled for non-cash payments
            clearing_combo = QComboBox()
            clearing_combo.addItems(["posted", "pending", "cleared", "bounced"])
            current_state = payment.get('clearing_state', 'posted')
            clearing_combo.setCurrentText(current_state)
            
            # Compute if payment method is cash to avoid duplicate checks
            is_cash = payment.get('method', '').lower() == 'cash'
            
            # Disable clearing_combo if cash payment OR already cleared
            clearing_combo.setEnabled(not is_cash and current_state != 'cleared')
            
            payment_layout.addWidget(QLabel("Status:"))
            payment_layout.addWidget(clearing_combo)
            
            # Update button - disable if cash payment OR already cleared
            update_btn = QPushButton("Update")
            update_btn.setEnabled(not is_cash and current_state != 'cleared')
            
            # Connect button to update function
            def make_update_handler(payment_id, combo):
                def update_status():
                    try:
                        new_status = combo.currentText()
                        success = controller.update_payment_clearing_status(payment_id, new_status)
                        if success:
                            # Refresh the payment list after successful update
                            try:
                                controller.load_purchase_payments()
                            except Exception as refresh_error:
                                _log.exception("Error refreshing payment list after status update for payment_id %s", payment_id)
                                from PySide6.QtWidgets import QMessageBox
                                QMessageBox.critical(self, "Refresh Failed", f"Payment status updated successfully, but failed to refresh the payment list:\n{str(refresh_error)}")
                        else:
                            # Optionally inform user if update didn't succeed but didn't raise exception
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.warning(self, "Update Failed", f"Could not update payment status to '{new_status}'.")
                    except Exception as e:
                        _log.exception("Error updating payment status for payment_id %s", payment_id)
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.critical(self, "Update Failed", f"An error occurred while updating payment status:\n{str(e)}")
                return update_status
            
            payment_id = payment.get('payment_id')
            if payment_id is not None:
                update_btn.clicked.connect(make_update_handler(payment_id, clearing_combo))
            else:
                # Disable the button if payment_id is missing
                update_btn.setEnabled(False)
                _log.warning("Payment control created without payment_id for payment method: %s", payment.get('method', 'Unknown'))
            payment_layout.addWidget(update_btn)
            
            # Add to main layout
            self.paymentControlsLayout.addLayout(payment_layout)
    
    def _clear_and_delete_layout(self, layout):
        """Recursively clear and delete all items in a layout."""
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # Recursively clear nested layouts
                self._clear_and_delete_layout(child.layout())
            # Allow spacers and other items to be cleaned up
        # After all children are handled, delete the layout itself
        layout.deleteLater()
