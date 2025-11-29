from __future__ import annotations

import logging
import re
from typing import Callable, Optional, Literal

try:
    from PySide6.QtCore import Qt, QDate
    from PySide6.QtGui import QIntValidator, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFormLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
        QDateEdit,
        QGroupBox,
        QGridLayout,
        QComboBox,
        QScrollArea,
    )
except Exception:
    raise

from ...database.repositories.vendors_repo import VendorsRepo
from ...utils.helpers import today_str


def _t(s: str) -> str:
    return s


def open_vendor_money_form(
    *,
    mode: Literal["payment", "advance"] = "advance",
    vendor_id: int,
    vendors: VendorsRepo | None = None,
    purchase_id: Optional[str] = None,
    defaults: dict | None = None,
) -> dict | None:
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    dlg = _VendorMoneyDialog(mode=mode, vendor_id=int(vendor_id), vendors=vendors, purchase_id=purchase_id, defaults=defaults or {})
    result = dlg.exec()
    payload = dlg.payload() if result == QDialog.Accepted else None

    if owns_app:
        app.quit()
    return payload


class _VendorMoneyDialog(QDialog):
    PAYMENT_METHODS = {
        'CASH': 'Cash',
        'BANK_TRANSFER': 'Bank Transfer', 
        'CHEQUE': 'Cheque',
        'CROSS_CHEQUE': 'Cross Cheque',
        'CASH_DEPOSIT': 'Cash Deposit',
        'OTHER': 'Other'
    }
    
    PAYMENT_METHODS_REQUIRE_COMPANY_BANK = {'BANK_TRANSFER', 
                                           'CHEQUE', 
                                           'CROSS_CHEQUE'}
    PAYMENT_METHODS_REQUIRE_VENDOR_BANK = {'BANK_TRANSFER', 
                                          'CROSS_CHEQUE', 
                                          'CASH_DEPOSIT'}
    PAYMENT_METHODS_REQUIRE_INSTRUMENT = {'BANK_TRANSFER', 
                                         'CHEQUE', 
                                         'CROSS_CHEQUE', 
                                         'CASH_DEPOSIT'}
    TEMP_BANK_KEY = "TEMP_BANK"

    def _get_method_key(self, display_value: str) -> str | None:
        """Convert a payment method display value to its corresponding key."""
        return self._method_display_to_key.get(display_value)

    def __init__(self, *, mode: str, vendor_id: int, vendors: VendorsRepo | None = None, purchase_id: Optional[str] = None, defaults: dict) -> None:
        super().__init__(None)
        self._mode = mode
        self.setWindowTitle(_t("Record Vendor Payment" if self._mode == "payment" else "Record Vendor Advance"))
        self.setModal(True)

        self._payload: Optional[dict] = None
        self._vendor_id = int(vendor_id)
        self._defaults = defaults or {}
        self.vendors = vendors  # Added vendors connection
        self._purchase_id = purchase_id

        self._submit_payment: Optional[Callable[[dict], None]] = self._defaults.get("submit_payment")
        self._submit_advance: Optional[Callable[[dict], None]] = self._defaults.get("submit_advance")

        self._prefill_amount: Optional[float] = self._defaults.get("amount")
        self._prefill_date: Optional[str] = self._defaults.get("date")
        self._prefill_notes: Optional[str] = self._defaults.get("notes")
        self._prefill_created_by: Optional[int] = self._defaults.get("created_by")
        self._vendor_display: Optional[str] = self._defaults.get("vendor_display")

        # Create reverse mapping from display values to keys for payment methods
        self._method_display_to_key = {v: k for k, v in self.PAYMENT_METHODS.items()}

        self._build_ui()
        self._apply_prefills()
        
        # Load bank accounts after UI is built (need the widgets to exist)
        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_visibility()
        self._toggle_fields_by_amount()
        
        # Calculate and display remaining amount if in payment mode
        if self._mode == "payment":
            self._calculate_remaining_amount()

    def _build_ui(self) -> None:
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Vendor information display
        vendor_info_box = QGroupBox("Vendor Information")
        vendor_info_layout = QVBoxLayout(vendor_info_box)
        self.vendorLabel = QLabel(f"Vendor: {self._vendor_id if self._vendor_display is None else self._vendor_display}")
        vendor_info_layout.addWidget(self.vendorLabel)
        main_layout.addWidget(vendor_info_box)

        # Payment fields group box
        payment_box = QGroupBox("Advance Payment Details")
        payment_layout = QGridLayout(payment_box)
        payment_layout.setHorizontalSpacing(10)  # Reduced horizontal spacing
        payment_layout.setVerticalSpacing(2)   # Further reduced vertical spacing

        # Use QLineEdit instead of QDoubleSpinBox to match the original payment form
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Enter amount")
        self.amount.clear()  # Explicitly clear the text field to ensure it's empty
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        from datetime import date
        self.date.setDate(QDate.fromString(date.today().isoformat(), "yyyy-MM-dd"))

        self.method = QComboBox()
        self.method.addItems(list(self.PAYMENT_METHODS.values()))

        self.company_acct = QComboBox()
        self.company_acct.setEditable(True)
        self.vendor_acct = QComboBox()
        self.vendor_acct.setEditable(True)
        self.instr_no = QLineEdit()
        self.instr_no.setPlaceholderText("Instrument / Cheque / Slip #")
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Notes (optional)")
        
        # Temporary external bank account fields
        self.temp_bank_name = QLineEdit()
        self.temp_bank_name.setPlaceholderText("Bank Name")
        self.temp_bank_number = QLineEdit()
        self.temp_bank_number.setPlaceholderText("Account Number")

        def create_required_label(text):
            """Helper function to create a label with a red asterisk for required fields"""
            label = QLabel()
            label.setText(text + "*")
            label.setStyleSheet("color: red; font-weight: bold;")
            return label

        def add_payment_field(row, col, text, widget, required=False):
            """Helper function to add payment fields with optional required indicators"""
            c = col * 2
            if required:
                label = create_required_label(text)
                payment_layout.addWidget(label, row, c)
            else:
                label = QLabel(text)
                payment_layout.addWidget(label, row, c)
            payment_layout.addWidget(widget, row, c + 1)
            return label  # Return the label for potential modification later

        self._payment_labels = {}
        
        add_payment_field(0, 0, "Amount", self.amount, required=True)
        add_payment_field(0, 1, "Payment Date", self.date, required=True)
        add_payment_field(1, 0, "Method", self.method, required=True)
        self._payment_labels['company_acct'] = add_payment_field(1, 1, "Company Bank Account", self.company_acct, required=False)
        self._payment_labels['vendor_acct'] = add_payment_field(2, 0, "Vendor Bank Account", self.vendor_acct, required=False)
        self._payment_labels['instr_no'] = add_payment_field(2, 1, "Instrument No", self.instr_no, required=False)
        
        # Add temporary bank fields to the layout (now at row 3)
        payment_layout.addWidget(QLabel("Temp Bank Name"), 3, 0)
        payment_layout.addWidget(self.temp_bank_name, 3, 1)
        payment_layout.addWidget(QLabel("Temp Bank Number"), 3, 2)
        payment_layout.addWidget(self.temp_bank_number, 3, 3)
        
        # Store temporary bank labels separately
        temp_bank_name_item = payment_layout.itemAtPosition(3, 0)
        temp_bank_number_item = payment_layout.itemAtPosition(3, 2)
        self._payment_labels['temp_bank_name'] = temp_bank_name_item.widget() if temp_bank_name_item else None
        self._payment_labels['temp_bank_number'] = temp_bank_number_item.widget() if temp_bank_number_item else None
        
        # Keep temporary bank fields visible but disabled by default
        self.temp_bank_name.setVisible(True)
        self.temp_bank_number.setVisible(True)
        self.temp_bank_name.setEnabled(False)
        self.temp_bank_number.setEnabled(False)
        # Keep the labels visible but not required initially
        # We will handle their requirement state separately
        
        # Purchase information display (only for payment mode)
        purchase_info_box = None
        remaining_info_box = None
        if self._mode == "payment" and self._purchase_id:
            purchase_info_box = QGroupBox("Purchase Information")
            purchase_info_layout = QHBoxLayout(purchase_info_box)
            self.lbl_purchase_id = QLabel(f"Purchase ID: {self._purchase_id}")
            purchase_info_layout.addWidget(self.lbl_purchase_id)
            main_layout.addWidget(purchase_info_box)

            # Add remaining amount info
            remaining_info_box = QGroupBox("Payment Summary")
            remaining_info_layout = QHBoxLayout(remaining_info_box)
            self.lbl_remaining = QLabel("Calculating...")
            remaining_info_layout.addWidget(self.lbl_remaining)
            main_layout.addWidget(remaining_info_box)
        else:
            # For advance mode, make sure we initialize the labels to avoid AttributeError
            self.lbl_purchase_id = QLabel("")
            self.lbl_remaining = QLabel("")

        # Make purchase info fields available even if not visible for payment mode
        if self._mode == "payment" and purchase_info_box and remaining_info_box:
            purchase_info_box.setVisible(True)
            remaining_info_box.setVisible(True)
        else:
            # For advance mode, hide purchase-related fields
            self.lbl_purchase_id.setParent(None)
            self.lbl_remaining.setParent(None)

        # Add payment notes
        payment_layout.addWidget(QLabel("Payment Notes"), 5, 0)
        payment_layout.addWidget(self.notes, 5, 1, 1, 3)
        payment_layout.setColumnStretch(1, 1)
        payment_layout.setColumnStretch(3, 1)

        main_layout.addWidget(payment_box, 1)

        # Button box
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.saveBtn = self.buttonBox.button(QDialogButtonBox.Save)
        self.saveBtn.setText("Record Advance")
        self.cancelBtn = self.buttonBox.button(QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self._on_save)
        self.buttonBox.rejected.connect(self.reject)

        # Add button box to layout
        main_layout.addWidget(self.buttonBox)

        scroll_area = QScrollArea()
        scroll_area.setWidget(main_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        final_layout = QVBoxLayout(self)
        final_layout.setContentsMargins(12, 12, 12, 12)
        final_layout.setSpacing(8)
        final_layout.addWidget(scroll_area, 1)
        final_layout.addWidget(self.buttonBox, 0)

        # Connect signals
        self.method.currentIndexChanged.connect(self._refresh_visibility)
        self.amount.textChanged.connect(self._toggle_fields_by_amount)
        self.vendor_acct.currentIndexChanged.connect(self._on_vendor_bank_account_changed)

        # Error Label - Add it in the dialog
        self.errorLabel = QLabel("")
        self.errorLabel.setStyleSheet("color:#b00020;")
        final_layout.insertWidget(final_layout.count()-1, self.errorLabel)  # Insert before button box

        # Clear the amount field after all initialization to ensure it starts empty
        self.amount.clear()
        
        self.resize(700, 650)
        self.setMinimumSize(600, 550)

    def _to_float_safe(self, txt: str) -> float | None:
        if txt is None or txt == "":
            return None
        try:
            cleaned = re.sub(r"[^0-9.\-]", "", txt)
            return float(cleaned) if cleaned and cleaned not in ['-', '.', '-.'] else None
        except ValueError:
            logging.warning(f"Could not convert '{txt}' to float, returning None")
            return None
        except Exception as e:
            logging.error(f"Unexpected error in _to_float_safe with input '{txt}': {e}")
            return None

    def _update_field_enablement(self, enable_company=False, enable_vendor=False, enable_instr=False, enable_temp=False):
        """Centralize the logic for enabling/disabling payment fields."""
        self.company_acct.setEnabled(enable_company)
        self.vendor_acct.setEnabled(enable_vendor)
        self.instr_no.setEnabled(enable_instr)
        self.temp_bank_name.setEnabled(enable_temp)
        self.temp_bank_number.setEnabled(enable_temp)

    def _toggle_fields_by_amount(self):
        try:
            amount_result = self._to_float_safe(self.amount.text())
            if amount_result is None:
                # If amount is empty, disable all dependent fields
                enable_fields = False
            else:
                amount = float(amount_result)
                enable_fields = amount > 0

            self.date.setEnabled(enable_fields)
            self.method.setEnabled(enable_fields)
            method = self.method.currentText()
            method_key = self._get_method_key(method)
            enable_company = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK or method_key == 'OTHER')
            enable_vendor = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK or method_key == 'OTHER')
            enable_instr = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT or method_key == 'OTHER')
            
            self._update_field_enablement(enable_company, enable_vendor, enable_instr, False)
            self.notes.setEnabled(enable_fields)

            if not enable_fields and self._get_method_key(self.method.currentText()) != 'CASH':
                self.method.setCurrentText(self.PAYMENT_METHODS['CASH'])
                
            if enable_fields:
                method_key = self._get_method_key(self.method.currentText())
                need_vendor = method_key in ('BANK_TRANSFER', 'CROSS_CHEQUE', 'CASH_DEPOSIT')
                if need_vendor and self._vendor_id:
                    self._reload_vendor_accounts()
                self._refresh_visibility()
            else:
                self._update_field_enablement(False, False, False, False)
                self.vendor_acct.clear()  
        except Exception as e:
            logging.exception("Error in _toggle_fields_by_amount")
            self.date.setEnabled(False)
            self.method.setEnabled(False)
            self._update_field_enablement(False, False, False, False)
            self.notes.setEnabled(False)

    def _reload_company_accounts(self):
        self.company_acct.clear()
        try:
            # Compliance: Check if vendors repository is available before accessing connection
            if self.vendors is None:
                # Skip loading if no vendors repository provided
                return
            
            conn = self.vendors.conn
            rows = conn.execute(
                "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
            ).fetchall()
            for r in rows:
                self.company_acct.addItem(r["label"], int(r["account_id"]))
            
            current_method = self.method.currentText()
            if current_method == self.PAYMENT_METHODS['OTHER']:
                self.company_acct.setCurrentIndex(-1)  
        except ValueError:
            logging.error("Error: Invalid company account ID")
            logging.exception("Invalid account ID in _reload_company_accounts")
        except Exception as e:
            logging.error(f"Error loading company bank accounts: {e}")
            logging.exception("Error in _reload_company_accounts")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load company bank accounts: {str(e)}")

    def _reload_vendor_accounts(self):
        current_text = self.vendor_acct.currentText()
        
        self.vendor_acct.clear()
        vid = self._vendor_id
        
        if not vid:
            self.vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
            return
        
        try:
            # Compliance: Check if vendors repository is available before accessing connection
            if self.vendors is None:
                # Skip loading if no vendors repository provided
                self.vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
                return
            
            conn = self.vendors.conn
            rows = conn.execute(
                """
                SELECT vendor_bank_account_id AS vba_id, label, is_primary
                FROM vendor_bank_accounts
                WHERE vendor_id=? AND is_active=1
                ORDER BY is_primary DESC, vba_id
                """,
                (int(vid),),
            ).fetchall()
            
            primary_account_added = False
            for r in rows:
                label = r["label"] + (" (Primary)" if str(r["is_primary"]) in ("1","True","true") else "")
                self.vendor_acct.addItem(label, int(r["vba_id"]))
                if str(r["is_primary"]) in ("1","True","true"):
                    primary_account_added = True
            
            self.vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
            
            previous_selection_restored = False
            if current_text and current_text != "":
                index = self.vendor_acct.findText(current_text)
                if index >= 0:
                    self.vendor_acct.setCurrentIndex(index)
                    previous_selection_restored = True
            
            current_method = self.method.currentText()
            current_method_key = self._get_method_key(current_method)
            needs_vendor_account = current_method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK
            
            if not previous_selection_restored and primary_account_added and needs_vendor_account:
                for i in range(self.vendor_acct.count() - 1):  
                    item_text = self.vendor_acct.itemText(i)
                    if "(Primary)" in item_text:
                        self.vendor_acct.setCurrentIndex(i)
                        break
            elif not previous_selection_restored and not needs_vendor_account:
                self.vendor_acct.setCurrentIndex(-1)  
        
        except ValueError:
            logging.error(f"Error: Invalid vendor ID: {vid}")
            logging.exception("Invalid vendor ID in _reload_vendor_accounts")
        except Exception as e:
            logging.error(f"Error loading vendor bank accounts: {e}")
            logging.exception("Error in _reload_vendor_accounts")
            
            self.vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load vendor bank accounts: {str(e)}")

    def _refresh_visibility(self):
        try:
            amount_result = self._to_float_safe(self.amount.text())
            if amount_result is None or amount_result <= 0:
                self._update_field_enablement(False, False, False, False)
                self._reset_labels()
                return
            amount = float(amount_result)
        except Exception as e:
            logging.exception("Error in _refresh_visibility")
            self._update_field_enablement(False, False, False, False)
            self._reset_labels()
            return

        method = self.method.currentText()
        method_key = self._get_method_key(method)
        need_company = method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK
        need_vendor  = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        need_instr   = method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT

        # Enable fields based on method and amount
        if amount > 0:
            if method_key == 'OTHER':
                self._update_field_enablement(True, True, True, False)
                
                if self._vendor_id:
                    self._reload_vendor_accounts()
                
                self.company_acct.setCurrentIndex(-1)
                self.vendor_acct.setCurrentIndex(-1)
            else:
                # Determine if temp bank fields should be enabled (both temp account selected and method requires vendor)
                selected_vendor_account = self.vendor_acct.currentData()
                is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY
                
                # Update temp bank visibility and enabled state
                enable_temp = is_temp_account and need_vendor
                self._update_field_enablement(need_company, need_vendor, need_instr, enable_temp)
                
                if need_vendor and self._vendor_id:
                    self._reload_vendor_accounts()  
        else:
            self._update_field_enablement(False, False, False, False)

        if hasattr(self, '_payment_labels'):
            self._update_labels(need_company, need_vendor, need_instr)

        # Update temp bank visibility based on account selection and method requirements
        # Recompute the specific variables needed for temp bank visibility
        selected_vendor_account = self.vendor_acct.currentData()
        is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY
        
        self._update_temp_bank_visibility(is_temp_account=is_temp_account, need_vendor=need_vendor)

    def _reset_labels(self):
        """Reset all payment labels to normal state (non-required)"""
        if hasattr(self, '_payment_labels'):
            for label_key, label_widget in self._payment_labels.items():
                if label_widget.styleSheet() != "":
                    plain_text = label_widget.text().rstrip('*')
                    label_widget.setText(plain_text)
                    label_widget.setStyleSheet("")

    def _update_labels(self, need_company=False, need_vendor=False, need_instr=False):
        """Update payment section labels based on required fields"""
        if not hasattr(self, '_payment_labels'):
            return
            
        self._reset_labels()
        
        if need_company and 'company_acct' in self._payment_labels:
            self._set_label_required(self._payment_labels['company_acct'])
        
        if need_vendor and 'vendor_acct' in self._payment_labels:
            self._set_label_required(self._payment_labels['vendor_acct'])
        
        if need_instr and 'instr_no' in self._payment_labels:
            self._set_label_required(self._payment_labels['instr_no'])

    def _set_label_required(self, label_widget):
        """Set a label as required (red asterisk and bold)"""
        current_text = label_widget.text()
        if not current_text.endswith("*"):
            label_widget.setText(current_text + "*")
            label_widget.setStyleSheet("color: red; font-weight: bold;")

    def _update_temp_bank_visibility(self, is_temp_account=None, need_vendor=None):
        """
        Helper method to update temporary bank field visibility and styling.
        If is_temp_account or need_vendor are not provided, they will be calculated.
        The enable/disable logic is now handled in _refresh_visibility
        """
        if is_temp_account is None:
            selected_value = self.vendor_acct.currentData()
            is_temp_account = selected_value == self.TEMP_BANK_KEY
        
        if need_vendor is None:
            method_key = self._get_method_key(self.method.currentText())
            need_vendor = method_key in ('BANK_TRANSFER', 'CROSS_CHEQUE', 'CASH_DEPOSIT')
        
        if is_temp_account and need_vendor:
            temp_name_label = self._payment_labels.get('temp_bank_name')
            if temp_name_label and not temp_name_label.text().endswith('*'):
                temp_name_label.setText(temp_name_label.text() + "*")
                temp_name_label.setStyleSheet("color: red; font-weight: bold;")
                
            temp_number_label = self._payment_labels.get('temp_bank_number')
            if temp_number_label and not temp_number_label.text().endswith('*'):
                temp_number_label.setText(temp_number_label.text() + "*")
                temp_number_label.setStyleSheet("color: red; font-weight: bold;")
                
            self.temp_bank_name.setEnabled(True)
            self.temp_bank_number.setEnabled(True)
        else:
            temp_name_label = self._payment_labels.get('temp_bank_name')
            if temp_name_label:
                temp_name_label.setText(temp_name_label.text().rstrip('*'))
                temp_name_label.setStyleSheet("")
                
            temp_number_label = self._payment_labels.get('temp_bank_number')
            if temp_number_label:
                temp_number_label.setText(temp_number_label.text().rstrip('*'))
                temp_number_label.setStyleSheet("")
                
            # Keep temp bank fields visible but disabled when not in temporary account mode
            self.temp_bank_name.setEnabled(False)
            self.temp_bank_number.setEnabled(False)

    def _on_vendor_bank_account_changed(self):
        """Show/hide temporary bank fields based on selection"""
        self._update_temp_bank_visibility()

    def _resolve_company_account_id(self) -> int | None:
        """Resolve company bank account ID from editable combobox text"""
        company_acct_text = self.company_acct.currentText().strip()
        company_id = self.company_acct.currentData()
        
        if company_id is None and company_acct_text:
            # Check if vendors repository is available before accessing connection
            if self.vendors is None:
                logging.warning("Vendors repository not available for resolving company account ID")
                return None
                
            try:
                conn = self.vendors.conn
                
                row = conn.execute(
                    "SELECT account_id FROM company_bank_accounts WHERE label = ? AND is_active=1",
                    (company_acct_text,)
                ).fetchone()
                if not row:
                    row = conn.execute(
                        "SELECT account_id FROM company_bank_accounts WHERE LOWER(label) = LOWER(?) AND is_active=1",
                        (company_acct_text,)
                    ).fetchone()
                if row:
                    company_id = int(row["account_id"])
                else:
                    # Compliance: Only logging generic info without PII details
                    logging.warning("Company bank account not found")
            except Exception as e:
                # Compliance: Only logging generic info without PII details
                logging.error(f"Error resolving company bank account ID: {e}")
                company_id = None
        
        return company_id

    def _resolve_vendor_account_id(self) -> int | None:
        """Resolve vendor bank account ID from editable combobox text"""
        vendor_acct_text = self.vendor_acct.currentText().strip()
        vendor_bank_id = self.vendor_acct.currentData()
        
        if vendor_bank_id is None and vendor_acct_text:
            # Check if vendors repository is available before accessing connection
            if self.vendors is None:
                logging.warning("Vendors repository not available for resolving vendor account ID")
                return None
                
            try:
                conn = self.vendors.conn
                
                row = conn.execute(
                    "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = ? AND vendor_id = ? AND is_active=1",
                    (vendor_acct_text, self._vendor_id)
                ).fetchone()
                if not row:
                    row = conn.execute(
                        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE LOWER(label) = LOWER(?) AND vendor_id = ? AND is_active=1",
                        (vendor_acct_text, self._vendor_id)
                    ).fetchone()
                if row:
                    vendor_bank_id = int(row["vendor_bank_account_id"])
                else:
                    # Compliance: Only logging generic info without PII details
                    logging.warning(f"Vendor bank account not found")
            except Exception as e:
                # Compliance: Only logging generic info without PII details
                logging.error(f"Error resolving vendor bank account ID: {e}")
                vendor_bank_id = None
        
        return vendor_bank_id

    def _calculate_remaining_amount(self):
        """Calculate and display the remaining amount for the purchase."""
        if not self._purchase_id or self._mode != "payment":
            if hasattr(self, 'lbl_remaining'):
                self.lbl_remaining.setText("Purchase ID not provided" if self._mode == "payment" else "N/A for advances")
            return
        
        # Early guard: Check if vendors repository is available before accessing connection
        if not self.vendors or not hasattr(self.vendors, 'conn'):
            logging.warning("Vendors repository not available for calculating remaining amount")
            if hasattr(self, 'lbl_remaining'):
                self.lbl_remaining.setText("Vendors repository not available")
            return
            
        try:
            # Fetch purchase header data to get total amount
            row = self.vendors.conn.execute(
                """
                SELECT 
                    COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
                    COALESCE(p.paid_amount, 0.0) AS paid_amount,
                    COALESCE(p.advance_payment_applied, 0.0) AS advance_applied
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                WHERE p.purchase_id = ?
                """,
                (self._purchase_id,)
            ).fetchone()
            
            if row:
                total_calc = float(row["total_calc"] or 0.0)
                paid_amount = float(row["paid_amount"] or 0.0)
                advance_applied = float(row["advance_payment_applied"] or 0.0)
                
                remaining = total_calc - paid_amount - advance_applied
                self.lbl_remaining.setText(f"Remaining: {remaining:.2f}")
            else:
                self.lbl_remaining.setText("Purchase not found")
                
        except Exception as e:
            logging.error(f"Error calculating remaining amount: {e}")
            self.lbl_remaining.setText("Error calculating remaining amount")

    def _validate_advance(self) -> tuple[bool, list[str]]:
        """Validate advance payment details and return (is_valid, errors)"""
        errors = []
        
        amount_result = self._to_float_safe(self.amount.text())
        if amount_result is None:
            errors.append("Please enter a numeric amount.")
            return len(errors) == 0, errors
        
        try:
            amount = float(amount_result)
        except (ValueError, TypeError):
            errors.append("Please enter a valid numeric amount.")
            return len(errors) == 0, errors

        if amount < 0:
            errors.append("Payment amount cannot be negative.")
        # For advances, allow all methods (Cash, Bank Transfer, Cheque, Cross Cheque,
        # Cash Deposit, Other) without enforcing bank/instrument fields. Advances are
        # stored purely as vendor credit, so banking details are optional for the user
        # but not required for persistence.

        return len(errors) == 0, errors

    def _validate_live_payment(self) -> None:
        ok, errors = self._validate_advance()
        if not ok:
            error_message = "\n".join(errors)
            self.errorLabel.setText(error_message)
            self.saveBtn.setEnabled(False)
        else:
            self.errorLabel.setText("")
            self.saveBtn.setEnabled(True)

    def _on_save(self) -> None:
        is_valid, errors = self._validate_advance()
        if not is_valid:
            error_message = "\n".join(errors)
            self._warn(error_message)
            return

        if self._mode == "payment":
            # For payment mode, we use the original validation and payload building
            payload = self._build_payload_payment()
            if payload is None:
                self._warn("Please enter a valid payment amount greater than 0.")
                return

            cb = self._submit_payment
        else:  # advance mode
            payload = self._build_payload_advance()
            if payload is None:
                self._warn("Please enter a valid payment amount greater than 0.")
                return

            cb = self._submit_advance

        # If submit callback provided, use it to persist and surface any DB constraint errors.
        if callable(cb):
            try:
                cb(payload)
            except Exception as e:
                self._handle_submit_error(e)
                self._payload = None
                return

        self._payload = payload
        self.accept()

    # ---------- Prefills ----------
    def _apply_prefills(self) -> None:
        if isinstance(self._prefill_amount, (int, float)):
            self.amount.setText(str(self._prefill_amount))

        if self._prefill_date:
            self._set_date_from_str(self.date, self._prefill_date)
        else:
            from datetime import date
            self._set_date_from_str(self.date, date.today().isoformat())

        if self._prefill_notes:
            self.notes.setText(str(self._prefill_notes))

        # Note: For the advance payment, we don't need to prefill payment method or
        # other payment-specific fields based on defaults as they are not provided as defaults

    def payload(self) -> Optional[dict]:
        return self._payload

    # ---------- Helpers ----------
    def _warn(self, msg: Optional[str]) -> None:
        """
        Show an error message in the error label.
        """
        self.errorLabel.setText(msg or "")
        QMessageBox.warning(self, _t("Cannot Save"), msg or _t("Please correct the highlighted fields."))

    def _handle_submit_error(self, exc: Exception) -> None:
        # Show a friendly message but preserve the DB-provided detail if available
        message = str(exc).strip() or _t("A database rule prevented saving.")
        self._warn(message)

    def _set_date_from_str(self, edit: QDateEdit, s: str) -> None:
        try:
            parts = s.split("-")
            if len(parts) != 3:
                logging.warning(f"Invalid date format: {s}. Expected YYYY-MM-DD.")
                return  # Invalid format (not YYYY-MM-DD)
            y, m, d = map(int, parts)
            # QDate constructor will validate the date values
            date_obj = QDate(y, m, d)
            if not date_obj.isValid():
                logging.warning(f"Invalid date values: {s}. Date not valid in QDate.")
                return  # Invalid date (e.g., Feb 30)
            edit.setDate(date_obj)
        except ValueError:
            # Raised when s.split("-") doesn't have 3 parts that can be converted to int
            logging.error(f"Error parsing date string: {s}")
            pass

    def _build_payload_advance(self) -> dict | None:
        amount, method, company_id, vendor_bank_id, instr_no, instr_date, notes, date_str, instr_type, clearing_state, is_temp_account = self._build_common_payload_parts()
        
        if amount is None:
            return None

        payload = {
            "vendor_id": self._vendor_id,  # Changed from purchase_id to vendor_id
            "amount": amount,
            "method": method,
            "bank_account_id": int(company_id) if company_id else None,
            "vendor_bank_account_id": int(vendor_bank_id) if vendor_bank_id and not is_temp_account else None,
            "instrument_type": instr_type,
            "instrument_no": instr_no,
            "instrument_date": instr_date,
            "deposited_date": None,
            "cleared_date": None,
            "clearing_state": clearing_state,
            "ref_no": None,  # ref_no field was removed from UI
            "notes": notes,
            "date": date_str,
            "temp_vendor_bank_name": self.temp_bank_name.text().strip() if is_temp_account else None,
            "temp_vendor_bank_number": self.temp_bank_number.text().strip() if is_temp_account else None,
        }

        return payload

    def _build_common_payload_parts(self) -> tuple:
        """Extract and process common payload parts used by both payment and advance payloads."""
        amount_txt = self.amount.text().strip()
        amount = self._to_float_safe(amount_txt)

        if amount is None or amount <= 0:
            return None, None, None, None, None, None, None, None, None, None, None

        method = self.method.currentText()
        
        company_id = self._resolve_company_account_id()
        vendor_bank_id = self._resolve_vendor_account_id()
        
        instr_no = self.instr_no.text().strip()
        # Since instr_date field was removed, use the main payment date
        instr_date = self.date.date().toString("yyyy-MM-dd")
        # ref_no field was removed, set to None
        ref_no = None
        notes = self.notes.text().strip()
        date_str = self.date.date().toString("yyyy-MM-dd")

        if method == self.PAYMENT_METHODS['BANK_TRANSFER']:
            instr_type = "online"
            clearing_state = "cleared"
        elif method == self.PAYMENT_METHODS['CHEQUE']:
            instr_type = "cheque"
            clearing_state = "cleared"
        elif method == self.PAYMENT_METHODS['CROSS_CHEQUE']:
            instr_type = "cross_cheque"
            clearing_state = "cleared"
        elif method == self.PAYMENT_METHODS['CASH_DEPOSIT']:
            instr_type = "cash_deposit"
            clearing_state = "cleared"
            company_id = None
        elif method == self.PAYMENT_METHODS['CASH']:
            instr_type = None
            clearing_state = "cleared"
            company_id = None
            vendor_bank_id = None
            instr_no = ""
            instr_date = date_str
        else:  # OTHER
            instr_type = "other"
            clearing_state = "cleared"
            company_id = None
            vendor_bank_id = None
            instr_no = ""
            instr_date = date_str

        selected_vendor_account = self.vendor_acct.currentData()
        is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY
        
        return amount, method, company_id, vendor_bank_id, instr_no, instr_date, notes, date_str, instr_type, clearing_state, is_temp_account

    def _build_payload_payment(self) -> dict | None:
        amount, method, company_id, vendor_bank_id, instr_no, instr_date, notes, date_str, instr_type, clearing_state, is_temp_account = self._build_common_payload_parts()
        
        if amount is None:
            return None

        payload = {
            "purchase_id": self._purchase_id,  # For payment mode, this links to purchase
            "amount": amount,
            "method": method,
            "bank_account_id": int(company_id) if company_id else None,
            "vendor_bank_account_id": int(vendor_bank_id) if vendor_bank_id and not is_temp_account else None,
            "instrument_type": instr_type,
            "instrument_no": instr_no,
            "instrument_date": instr_date,
            "deposited_date": None,
            "cleared_date": None,
            "clearing_state": clearing_state,
            "ref_no": None,  # ref_no field was removed from UI
            "notes": notes,
            "date": date_str,
            "temp_vendor_bank_name": self.temp_bank_name.text().strip() if is_temp_account else None,
            "temp_vendor_bank_number": self.temp_bank_number.text().strip() if is_temp_account else None,
        }

        return payload

