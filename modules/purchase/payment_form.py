from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QPushButton, QLabel, QGroupBox, QScrollArea, QWidget,
    QGridLayout
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtCore import QEvent, QObject
from ...database.repositories.vendors_repo import VendorsRepo
from ...utils.helpers import today_str
import re
import logging


class PaymentForm(QDialog):
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
                                           'CROSS_CHEQUE', 
                                           'CASH_DEPOSIT'}
    PAYMENT_METHODS_REQUIRE_VENDOR_BANK = {'BANK_TRANSFER', 
                                          'CROSS_CHEQUE', 
                                          'CASH_DEPOSIT'}
    PAYMENT_METHODS_REQUIRE_INSTRUMENT = {'BANK_TRANSFER', 
                                         'CHEQUE', 
                                         'CROSS_CHEQUE', 
                                         'CASH_DEPOSIT'}

    def _get_method_key(self, display_value: str) -> str | None:
        """Convert a payment method display value to its corresponding key."""
        return self._method_display_to_key.get(display_value)

    def __init__(self, parent=None, vendors: VendorsRepo | None = None, purchase_id: str = None, vendor_id: int = None):
        super().__init__(parent)
        self.setWindowTitle("Record Payment")
        self.setModal(True)
        self.vendors = vendors
        self.purchase_id = purchase_id
        self.vendor_id = vendor_id
        self._payload = None
        # Create reverse mapping from display values to keys for payment methods
        self._method_display_to_key = {v: k for k, v in self.PAYMENT_METHODS.items()}

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Purchase information display
        if purchase_id:
            purchase_info_box = QGroupBox("Purchase Information")
            purchase_info_layout = QHBoxLayout(purchase_info_box)
            self.lbl_purchase_id = QLabel(f"Purchase ID: {purchase_id}")
            purchase_info_layout.addWidget(self.lbl_purchase_id)
            main_layout.addWidget(purchase_info_box)

            # Add remaining amount info
            remaining_info_box = QGroupBox("Payment Summary")
            remaining_info_layout = QHBoxLayout(remaining_info_box)
            self.lbl_remaining = QLabel("Calculating...")
            remaining_info_layout.addWidget(self.lbl_remaining)
            main_layout.addWidget(remaining_info_box)
            
            # Calculate and display remaining amount
            self._calculate_remaining_amount()

        # Payment fields group box
        payment_box = QGroupBox("Payment Details")
        payment_layout = QGridLayout(payment_box)
        payment_layout.setHorizontalSpacing(12)
        payment_layout.setVerticalSpacing(8)

        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))

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
        self._payment_labels['temp_bank_name'] = payment_layout.itemAtPosition(3, 0).widget()
        self._payment_labels['temp_bank_number'] = payment_layout.itemAtPosition(3, 2).widget()
        
        # Hide temporary bank fields by default
        self.temp_bank_name.setVisible(False)
        self.temp_bank_number.setVisible(False)
        # Keep the labels visible but not required initially
        # We will handle their requirement state separately

        # Add payment notes
        payment_layout.addWidget(QLabel("Payment Notes"), 5, 0)
        payment_layout.addWidget(self.notes, 5, 1, 1, 3)
        payment_layout.setColumnStretch(1, 1)
        payment_layout.setColumnStretch(3, 1)

        main_layout.addWidget(payment_box, 1)

        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Record Payment")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Add button box to layout
        main_layout.addWidget(button_box)

        scroll_area = QScrollArea()
        scroll_area.setWidget(main_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        final_layout = QVBoxLayout(self)
        final_layout.setContentsMargins(12, 12, 12, 12)
        final_layout.setSpacing(8)
        final_layout.addWidget(scroll_area, 1)
        final_layout.addWidget(button_box, 0)

        # Connect signals
        self.method.currentIndexChanged.connect(self._refresh_visibility)
        self.amount.textChanged.connect(self._toggle_fields_by_amount)
        self.vendor_acct.currentIndexChanged.connect(self._on_vendor_bank_account_changed)

        # Load bank accounts
        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_visibility()
        self._toggle_fields_by_amount()
        
        # Calculate and display remaining amount
        self._calculate_remaining_amount()

        self.resize(700, 650)
        self.setMinimumSize(600, 550)

    def _to_float_safe(self, txt: str) -> float:
        if txt is None:
            return 0.0
        try:
            cleaned = re.sub(r"[^0-9.\-]", "", txt)
            return float(cleaned) if cleaned and cleaned not in ['-', '.', '-.'] else 0.0
        except ValueError:
            logging.warning(f"Could not convert '{txt}' to float, returning 0.0")
            return 0.0
        except Exception as e:
            logging.error(f"Unexpected error in _to_float_safe with input '{txt}': {e}")
            return 0.0

    def _toggle_fields_by_amount(self):
        try:
            amount = float(self._to_float_safe(self.amount.text()))
            enable_fields = amount > 0

            self.date.setEnabled(enable_fields)
            self.method.setEnabled(enable_fields)
            method = self.method.currentText()
            method_key = self._get_method_key(method)
            enable_company = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK or method == self.PAYMENT_METHODS['OTHER'])
            enable_vendor = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK or method == self.PAYMENT_METHODS['OTHER'])
            enable_instr = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT or method == self.PAYMENT_METHODS['OTHER'])
            
            self.company_acct.setEnabled(enable_company)
            self.vendor_acct.setEnabled(enable_vendor)
            self.instr_no.setEnabled(enable_instr)
            self.notes.setEnabled(enable_fields)

            if not enable_fields and self.method.currentText() != self.PAYMENT_METHODS['CASH']:
                self.method.setCurrentText(self.PAYMENT_METHODS['CASH'])
                
            if enable_fields:
                method = self.method.currentText()
                need_vendor = method in (self.PAYMENT_METHODS['BANK_TRANSFER'], 
                                        self.PAYMENT_METHODS['CROSS_CHEQUE'], 
                                        self.PAYMENT_METHODS['CASH_DEPOSIT'])
                if need_vendor and self.vendor_id:
                    self._reload_vendor_accounts()
                self._refresh_visibility()
            else:
                self.company_acct.setEnabled(False)
                self.vendor_acct.setEnabled(False)
                self.vendor_acct.clear()  
                self.instr_no.setEnabled(False)
                self.instr_date.setEnabled(False)
        except Exception as e:
            logging.exception("Error in _toggle_fields_by_amount")
            self.date.setEnabled(False)
            self.method.setEnabled(False)
            self.company_acct.setEnabled(False)
            self.vendor_acct.setEnabled(False)
            self.instr_no.setEnabled(False)
            self.notes.setEnabled(False)
            # Also disable temp bank fields on error
            self.temp_bank_name.setEnabled(False)
            self.temp_bank_number.setEnabled(False)

    def _calculate_remaining_amount(self):
        """Calculate and display the remaining amount for the purchase."""
        if not self.purchase_id:
            self.lbl_remaining.setText("Purchase ID not provided")
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
                (self.purchase_id,)
            ).fetchone()
            
            if row:
                total_calc = float(row["total_calc"] or 0.0)
                paid_amount = float(row["paid_amount"] or 0.0)
                advance_applied = float(row["advance_applied"] or 0.0)
                
                remaining = total_calc - paid_amount - advance_applied
                self.lbl_remaining.setText(f"Remaining: {remaining:.2f}")
            else:
                self.lbl_remaining.setText("Purchase not found")
                
        except Exception as e:
            logging.error(f"Error calculating remaining amount: {e}")
            self.lbl_remaining.setText("Error calculating remaining amount")

    def _reload_company_accounts(self):
        self.company_acct.clear()
        try:
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
            print("Error: Invalid company account ID")
            logging.exception("Invalid account ID in _reload_company_accounts")
        except Exception as e:
            print(f"Error loading company bank accounts: {e}")
            logging.exception("Error in _reload_company_accounts")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load company bank accounts: {str(e)}")

    def _reload_vendor_accounts(self):
        current_text = self.vendor_acct.currentText()
        
        self.vendor_acct.clear()
        vid = self.vendor_id
        
        if not vid:
            self.vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
            return
        
        try:
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
            
            self.vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
            
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
            print(f"Error: Invalid vendor ID: {vid}")
            logging.exception("Invalid vendor ID in _reload_vendor_accounts")
        except Exception as e:
            print(f"Error loading vendor bank accounts: {e}")
            logging.exception("Error in _reload_vendor_accounts")
            
            self.vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load vendor bank accounts: {str(e)}")

    def _refresh_visibility(self):
        try:
            amount = float(self._to_float_safe(self.amount.text()))
            if amount <= 0:
                self.company_acct.setEnabled(False)
                self.vendor_acct.setEnabled(False)
                self.instr_no.setEnabled(False)
                self._reset_labels()
                # Also disable temporary bank fields when amount is zero
                self.temp_bank_name.setEnabled(False)
                self.temp_bank_number.setEnabled(False)
                return
        except Exception as e:
            logging.exception("Error in _refresh_visibility")
            self.company_acct.setEnabled(False)
            self.vendor_acct.setEnabled(False)
            self.instr_no.setEnabled(False)
            self._reset_labels()
            # Also disable temporary bank fields on error
            self.temp_bank_name.setEnabled(False)
            self.temp_bank_number.setEnabled(False)
            return

        method = self.method.currentText()
        method_key = self._get_method_key(method)
        need_company = method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK
        need_vendor  = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        need_instr   = method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT

        # Enable fields based on method and amount
        if amount > 0:
            if method == self.PAYMENT_METHODS['OTHER']:
                self.company_acct.setEnabled(True)
                self.vendor_acct.setEnabled(True)
                
                if self.vendor_id:
                    self._reload_vendor_accounts()
                
                self.company_acct.setCurrentIndex(-1)
                self.vendor_acct.setCurrentIndex(-1)
            else:
                self.company_acct.setEnabled(need_company)
                self.vendor_acct.setEnabled(need_vendor)
                
                if need_vendor and self.vendor_id:
                    self._reload_vendor_accounts()  
            self.instr_no.setEnabled(need_instr or method == self.PAYMENT_METHODS['OTHER'])  
        else:
            self.company_acct.setEnabled(False)
            self.vendor_acct.setEnabled(False)
            self.instr_no.setEnabled(False)

        if hasattr(self, '_payment_labels'):
            self._update_labels(need_company, need_vendor, need_instr)

        # Determine if temp bank fields should be enabled (both temp account selected and method requires vendor)
        method = self.method.currentText()
        method_key = self._get_method_key(method)
        need_vendor = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        selected_vendor_account = self.vendor_acct.currentData()
        is_temp_account = selected_vendor_account == "TEMP_BANK"
        
        # Update temp bank visibility and enabled state
        if is_temp_account and need_vendor:
            # Temp account selected and method requires vendor bank
            self.temp_bank_name.setEnabled(True)
            self.temp_bank_number.setEnabled(True)
        else:
            # Either temp account is not selected, or method doesn't require vendor bank
            self.temp_bank_name.setEnabled(False)
            self.temp_bank_number.setEnabled(False)
        
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
            is_temp_account = selected_value == "TEMP_BANK"
        
        if need_vendor is None:
            method = self.method.currentText()
            need_vendor = method in (self.PAYMENT_METHODS['BANK_TRANSFER'], 
                                   self.PAYMENT_METHODS['CROSS_CHEQUE'], 
                                   self.PAYMENT_METHODS['CASH_DEPOSIT'])
        
        if is_temp_account and need_vendor:
            temp_name_label = self._payment_labels.get('temp_bank_name')
            if temp_name_label and not temp_name_label.text().endswith('*'):
                temp_name_label.setText(temp_name_label.text() + "*")
                temp_name_label.setStyleSheet("color: red; font-weight: bold;")
                
            temp_number_label = self._payment_labels.get('temp_bank_number')
            if temp_number_label and not temp_number_label.text().endswith('*'):
                temp_number_label.setText(temp_number_label.text() + "*")
                temp_number_label.setStyleSheet("color: red; font-weight: bold;")
                
            self.temp_bank_name.setVisible(True)
            self.temp_bank_number.setVisible(True)
        else:
            temp_name_label = self._payment_labels.get('temp_bank_name')
            if temp_name_label:
                temp_name_label.setText(temp_name_label.text().rstrip('*'))
                temp_name_label.setStyleSheet("")
                
            temp_number_label = self._payment_labels.get('temp_bank_number')
            if temp_number_label:
                temp_number_label.setText(temp_number_label.text().rstrip('*'))
                temp_number_label.setStyleSheet("")
                
            # Always keep temp bank fields visible but the enabled state is controlled by _refresh_visibility
            self.temp_bank_name.setVisible(True)
            self.temp_bank_number.setVisible(True)

    def _on_vendor_bank_account_changed(self):
        """Show/hide temporary bank fields based on selection"""
        self._update_temp_bank_visibility()

    def _resolve_company_account_id(self) -> int | None:
        """Resolve company bank account ID from editable combobox text"""
        company_acct_text = self.company_acct.currentText().strip()
        company_id = self.company_acct.currentData()
        
        if company_id is None and company_acct_text:
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
                    logging.warning(f"Company bank account not found for label: {company_acct_text}")
            except Exception as e:
                logging.error(f"Error resolving company bank account ID for '{company_acct_text}': {e}")
                company_id = None
        
        return company_id

    def _resolve_vendor_account_id(self) -> int | None:
        """Resolve vendor bank account ID from editable combobox text"""
        vendor_acct_text = self.vendor_acct.currentText().strip()
        vendor_bank_id = self.vendor_acct.currentData()
        
        if vendor_bank_id is None and vendor_acct_text:
            try:
                conn = self.vendors.conn
                
                row = conn.execute(
                    "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = ? AND vendor_id = ? AND is_active=1",
                    (vendor_acct_text, self.vendor_id)
                ).fetchone()
                if not row:
                    row = conn.execute(
                        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE LOWER(label) = LOWER(?) AND vendor_id = ? AND is_active=1",
                        (vendor_acct_text, self.vendor_id)
                    ).fetchone()
                if row:
                    vendor_bank_id = int(row["vendor_bank_account_id"])
                else:
                    logging.warning(f"Vendor bank account not found for label: {vendor_acct_text} for vendor {self.vendor_id}")
            except Exception as e:
                logging.error(f"Error resolving vendor bank account ID for '{vendor_acct_text}' and vendor {self.vendor_id}: {e}")
                vendor_bank_id = None
        
        return vendor_bank_id

    def _validate_payment(self) -> tuple[bool, list[str]]:
        """Validate payment details and return (is_valid, errors)"""
        errors = []
        
        try:
            amount = float(self._to_float_safe(self.amount.text()))
        except:
            errors.append("Please enter a valid numeric amount.")
            return len(errors) == 0, errors

        if amount < 0:
            errors.append("Payment amount cannot be negative.")
        elif amount > 0:
            method = self.method.currentText()
            
            selected_vendor_account = self.vendor_acct.currentData()
            is_temp_account = selected_vendor_account == "TEMP_BANK"

            validation_rules = {
                self.PAYMENT_METHODS['BANK_TRANSFER']: {
                    'requires_company_acct': True,
                    'requires_vendor_acct': True,
                    'requires_instr_no': True,
                    'requires_temp_details': True,
                    'error_msg_company': f"For {self.PAYMENT_METHODS['BANK_TRANSFER']}, please select a company bank account.",
                    'error_msg_vendor': f"For {self.PAYMENT_METHODS['BANK_TRANSFER']}, please select a vendor bank account.",
                    'error_msg_instr': f"For {self.PAYMENT_METHODS['BANK_TRANSFER']}, please enter the instrument/cheque number.",
                    'error_msg_temp_name': f"For {self.PAYMENT_METHODS['BANK_TRANSFER']} with temporary account, please enter bank name.",
                    'error_msg_temp_number': f"For {self.PAYMENT_METHODS['BANK_TRANSFER']} with temporary account, please enter account number.",
                },
                self.PAYMENT_METHODS['CHEQUE']: {
                    'requires_company_acct': True,
                    'requires_vendor_acct': False,  
                    'requires_instr_no': True,
                    'requires_temp_details': False,
                    'error_msg_company': f"For {self.PAYMENT_METHODS['CHEQUE']}, please select a company bank account.",
                    'error_msg_instr': f"For {self.PAYMENT_METHODS['CHEQUE']}, please enter the instrument/cheque number.",
                },
                self.PAYMENT_METHODS['CROSS_CHEQUE']: {
                    'requires_company_acct': True,
                    'requires_vendor_acct': True,
                    'requires_instr_no': True,
                    'requires_temp_details': True,
                    'error_msg_company': f"For {self.PAYMENT_METHODS['CROSS_CHEQUE']}, please select a company bank account.",
                    'error_msg_vendor': f"For {self.PAYMENT_METHODS['CROSS_CHEQUE']}, please select a vendor bank account.",
                    'error_msg_instr': f"For {self.PAYMENT_METHODS['CROSS_CHEQUE']}, please enter the instrument/cheque number.",
                    'error_msg_temp_name': f"For {self.PAYMENT_METHODS['CROSS_CHEQUE']} with temporary account, please enter bank name.",
                    'error_msg_temp_number': f"For {self.PAYMENT_METHODS['CROSS_CHEQUE']} with temporary account, please enter account number.",
                },
                self.PAYMENT_METHODS['CASH_DEPOSIT']: {
                    'requires_company_acct': False,  
                    'requires_vendor_acct': True,
                    'requires_instr_no': True,
                    'requires_temp_details': True,
                    'error_msg_vendor': f"For {self.PAYMENT_METHODS['CASH_DEPOSIT']}, please select a vendor bank account.",
                    'error_msg_instr': f"For {self.PAYMENT_METHODS['CASH_DEPOSIT']}, please enter the deposit slip number.",
                    'error_msg_temp_name': f"For {self.PAYMENT_METHODS['CASH_DEPOSIT']} with temporary account, please enter bank name.",
                    'error_msg_temp_number': f"For {self.PAYMENT_METHODS['CASH_DEPOSIT']} with temporary account, please enter account number.",
                },
                self.PAYMENT_METHODS['OTHER']: {
                    # OTHER method has no specific requirements
                }
            }

            if method in validation_rules:
                rule = validation_rules[method]
                
                if rule.get('requires_company_acct', False) and self.company_acct.currentData() is None:
                    errors.append(rule['error_msg_company'])
                
                if rule.get('requires_vendor_acct', False):
                    if self.vendor_acct.currentData() is None:
                        errors.append(rule['error_msg_vendor'])
                    elif is_temp_account and rule.get('requires_temp_details', False):
                        if not self.temp_bank_name.text().strip():
                            errors.append(rule['error_msg_temp_name'])
                        if not self.temp_bank_number.text().strip():
                            errors.append(rule['error_msg_temp_number'])
                
                if rule.get('requires_instr_no', False) and not self.instr_no.text().strip():
                    errors.append(rule['error_msg_instr'])

        return len(errors) == 0, errors

    def get_payload(self) -> dict | None:
        amount_txt = self.amount.text().strip()
        amount = self._to_float_safe(amount_txt)

        if amount <= 0:
            return None

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
        is_temp_account = selected_vendor_account == "TEMP_BANK"
        
        payload = {
            "purchase_id": self.purchase_id,
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

    def validate_and_get_payload(self) -> tuple[bool, str | dict]:
        is_valid, errors = self._validate_payment()
        if not is_valid:
            error_message = "\n".join(errors)
            return False, error_message
            
        payload = self.get_payload()
        if payload is None:
            return False, "Please enter a valid payment amount greater than 0."
            
        return True, payload

    def accept(self):
        is_valid, result = self.validate_and_get_payload()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Validation Errors", str(result))
            return
        
        self._payload = result
        super().accept()

    def payload(self):
        return self._payload