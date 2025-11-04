from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QPushButton, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QScrollArea, QWidget, QHeaderView, QGridLayout
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QCompleter
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.helpers import today_str, fmt_money
import re
import datetime
import logging


class PurchaseForm(QDialog):
    COLS = ["#", "Product", "Qty", "Buy Price", "Sale Price", "Line Total", ""]
    
    
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

    def __init__(self, parent=None, vendors: VendorsRepo | None = None,
                 products: ProductsRepo | None = None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase")
        self.setModal(True)
        self.vendors = vendors
        self.products = products
        self._payload = None
        # Create reverse mapping from display values to keys for payment methods
        self._method_display_to_key = {v: k for k, v in self.PAYMENT_METHODS.items()}

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        self.cmb_vendor = QComboBox(); self.cmb_vendor.setEditable(True)
        for v in self.vendors.list_vendors():
            self.cmb_vendor.addItem(f"{v.name} (#{v.vendor_id})", v.vendor_id)

        self.date = QDateEdit(); self.date.setCalendarPopup(True)
        self.date.setDate(
            QDate.fromString(initial["date"], "yyyy-MM-dd")
            if initial and initial.get("date") else
            QDate.fromString(today_str(), "yyyy-MM-dd")
        )
        self.txt_notes = QLineEdit()

        def create_required_label(text):
            """Helper function to create a label with a red asterisk for required fields"""
            label = QLabel()
            label.setText(text + "*")
            label.setStyleSheet("color: red; font-weight: bold;")
            return label

        header_box = QGroupBox()
        hg = QGridLayout(header_box)
        hg.setHorizontalSpacing(12); hg.setVerticalSpacing(8)

        def add_pair(row, col, text, widget, required=False):
            """Modified function to optionally add red asterisks to required fields"""
            c = col * 2
            if required:
                hg.addWidget(create_required_label(text), row, c)
            else:
                hg.addWidget(QLabel(text), row, c)
            hg.addWidget(widget, row, c + 1)

        add_pair(0, 0, "Vendor", self.cmb_vendor, required=True)
        add_pair(0, 1, "Date", self.date, required=True)
        add_pair(1, 0, "Notes", self.txt_notes, required=False)
        hg.setColumnStretch(1, 1)
        hg.setColumnStretch(3, 1)
        main_layout.addWidget(header_box)

        items_box = QGroupBox("Items")
        ib = QVBoxLayout(items_box)
        ib.setSpacing(8)

        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.tbl.verticalHeader().setVisible(False)

        header = self.tbl.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 40)
        self.tbl.setColumnWidth(2, 80)
        self.tbl.setColumnWidth(3, 110)
        self.tbl.setColumnWidth(4, 110)
        self.tbl.setColumnWidth(5, 120)
        self.tbl.setColumnWidth(6, 48)

        ib.addWidget(self.tbl, 1)

        row_btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add Row")
        row_btns.addWidget(self.btn_add_row)
        row_btns.addStretch(1)
        ib.addLayout(row_btns)

        main_layout.addWidget(items_box, 2)

        tot = QHBoxLayout()
        self.lab_sub = QLabel("0.00")
        self.lab_total = QLabel("0.00")
        tot.addStretch(1)
        tot.addWidget(QLabel("Subtotal:")); tot.addWidget(self.lab_sub)
        tot.addSpacing(16)
        tot.addWidget(QLabel("Total:"));    tot.addWidget(self.lab_total)
        main_layout.addLayout(tot)

        
        is_edit_mode = bool(initial)
        
        ip_box = QGroupBox("Initial Payment (optional)")
        
        
        if is_edit_mode:
            ip_box.setEnabled(False)
            ip_box.setTitle("Initial Payment (disabled during edit - use Payments section)")
        
        ipg = QGridLayout(ip_box)
        ipg.setHorizontalSpacing(12); ipg.setVerticalSpacing(8)

        self.ip_amount = QLineEdit(); self.ip_amount.setPlaceholderText("0")
        self.ip_date = QDateEdit(); self.ip_date.setCalendarPopup(True); self.ip_date.setDate(self.date.date())

        self.ip_method = QComboBox()
        self.ip_method.addItems(list(self.PAYMENT_METHODS.values()))

        self.ip_company_acct = QComboBox(); self.ip_company_acct.setEditable(True)
        self.ip_vendor_acct  = QComboBox(); self.ip_vendor_acct.setEditable(True)
        self.ip_instr_no   = QLineEdit(); self.ip_instr_no.setPlaceholderText("Instrument / Cheque / Slip #")
        self.ip_instr_date = QDateEdit(); self.ip_instr_date.setCalendarPopup(True); self.ip_instr_date.setDate(self.ip_date.date())
        self.ip_ref_no     = QLineEdit(); self.ip_ref_no.setPlaceholderText("Reference (optional)")
        self.ip_notes      = QLineEdit(); self.ip_notes.setPlaceholderText("Notes (optional)")
        
        
        self.temp_bank_name = QLineEdit(); self.temp_bank_name.setPlaceholderText("Bank Name")
        self.temp_bank_number = QLineEdit(); self.temp_bank_number.setPlaceholderText("Account Number")

        def add_ip(row, col, text, widget, required=False):
            """Modified function for payment section with optional required field indicators"""
            c = col * 2
            if required:
                label = create_required_label(text)
                ipg.addWidget(label, row, c)
            else:
                label = QLabel(text)
                ipg.addWidget(label, row, c)
            ipg.addWidget(widget, row, c + 1)
            return label  

        
        self._ip_labels = {}
        
        add_ip(0, 0, "Amount", self.ip_amount, required=False)
        add_ip(0, 1, "Payment Date", self.ip_date, required=False)
        add_ip(1, 0, "Method", self.ip_method, required=False)
        self._ip_labels['company_acct'] = add_ip(1, 1, "Company Bank Account", self.ip_company_acct, required=False)
        self._ip_labels['vendor_acct'] = add_ip(2, 0, "Vendor Bank Account", self.ip_vendor_acct, required=False)
        self._ip_labels['instr_no'] = add_ip(2, 1, "Instrument No", self.ip_instr_no, required=False)
        add_ip(3, 0, "Instrument Date", self.ip_instr_date, required=False)
        add_ip(3, 1, "Ref No", self.ip_ref_no, required=False)
        
        
        self._ip_labels['temp_bank_name'] = add_ip(4, 0, "Temp Bank Name", self.temp_bank_name, required=False)
        self._ip_labels['temp_bank_number'] = add_ip(4, 1, "Temp Bank Number", self.temp_bank_number, required=False)
        
        
        self.temp_bank_name.setVisible(False)
        self.temp_bank_number.setVisible(False)
        
        ipg.addWidget(QLabel("Payment Notes"), 5, 0)
        ipg.addWidget(self.ip_notes, 5, 1, 1, 3)
        ipg.setColumnStretch(1, 1)
        ipg.setColumnStretch(3, 1)

        
        if is_edit_mode:
            for widget in [self.ip_amount, self.ip_date, self.ip_method, 
                          self.ip_company_acct, self.ip_vendor_acct, 
                          self.ip_instr_no, self.ip_instr_date, 
                          self.ip_ref_no, self.ip_notes]:
                widget.setEnabled(False)

        main_layout.addWidget(ip_box, 0)

        
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.save_button = QPushButton("Save")
        self.print_button = QPushButton("Print")
        self.pdf_export_button = QPushButton("Export to PDF")
        button_box.addButton(self.save_button, QDialogButtonBox.AcceptRole)
        button_box.addButton(self.print_button, QDialogButtonBox.ActionRole)
        button_box.addButton(self.pdf_export_button, QDialogButtonBox.ActionRole)
        
        
        self.save_button.clicked.connect(self._save_clicked)
        self.print_button.clicked.connect(self._print_clicked)
        self.pdf_export_button.clicked.connect(self._pdf_export_clicked)
        button_box.rejected.connect(self.reject)

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

        self._rows = []
        if initial and initial.get("items"):
            self._rows = [dict(x) for x in initial["items"]]

        self.btn_add_row.clicked.connect(self._add_row)
        self.tbl.cellChanged.connect(self._cell_changed)

        self.cmb_vendor.currentIndexChanged.connect(self._reload_vendor_accounts)
        self.ip_method.currentIndexChanged.connect(self._refresh_ip_visibility)
        self.ip_amount.textChanged.connect(self._toggle_ip_fields_by_amount)
        self.ip_date.dateChanged.connect(lambda _d: self.ip_instr_date.setDate(self.ip_date.date()))
        self.date.dateChanged.connect(
            lambda _d: (self.ip_date.setDate(self.date.date())
                        if (self.ip_amount.text().strip() in ("", "0", "0.0")) else None)
        )
        
        self.ip_vendor_acct.currentIndexChanged.connect(self._on_vendor_bank_account_changed)

        if initial:
            idx = self.cmb_vendor.findData(initial["vendor_id"])
            if idx >= 0: self.cmb_vendor.setCurrentIndex(idx)
            self.txt_notes.setText(initial.get("notes") or "")

        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_ip_visibility()
        self._rebuild_table()
        self._refresh_totals()
        
        self._toggle_ip_fields_by_amount()
        self.resize(1100, 700)
        self.setMinimumSize(860, 560)
        self.setSizeGripEnabled(True)

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

    def _toggle_ip_fields_by_amount(self):
        try:
            amount = float(self._to_float_safe(self.ip_amount.text()))
            enable_fields = amount > 0

            
            self.ip_date.setEnabled(enable_fields)
            self.ip_method.setEnabled(enable_fields)
            method = self.ip_method.currentText()
            method_key = self._get_method_key(method)
            enable_company = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK or method == self.PAYMENT_METHODS['OTHER'])
            enable_vendor = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK or method == self.PAYMENT_METHODS['OTHER'])
            enable_instr = enable_fields and (method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT or method == self.PAYMENT_METHODS['OTHER'])
            
            self.ip_company_acct.setEnabled(enable_company)
            self.ip_vendor_acct.setEnabled(enable_vendor)
            self.ip_instr_no.setEnabled(enable_instr)
            self.ip_instr_date.setEnabled(enable_instr)
            self.ip_ref_no.setEnabled(enable_fields)
            self.ip_notes.setEnabled(enable_fields)

            
            if not enable_fields and self.ip_method.currentText() != self.PAYMENT_METHODS['CASH']:
                self.ip_method.setCurrentText(self.PAYMENT_METHODS['CASH'])
                
            
            if enable_fields:
                
                method = self.ip_method.currentText()
                need_vendor = method in (self.PAYMENT_METHODS['BANK_TRANSFER'], 
                                        self.PAYMENT_METHODS['CROSS_CHEQUE'], 
                                        self.PAYMENT_METHODS['CASH_DEPOSIT'])
                if need_vendor and self.cmb_vendor.currentData():
                    self._reload_vendor_accounts()
                self._refresh_ip_visibility()
            else:
                
                self.ip_company_acct.setEnabled(False)
                self.ip_vendor_acct.setEnabled(False)
                self.ip_vendor_acct.clear()  
                self.ip_instr_no.setEnabled(False)
                self.ip_instr_date.setEnabled(False)
        except Exception as e:
            logging.exception("Error in _toggle_ip_fields_by_amount")
            self.ip_date.setEnabled(False)
            self.ip_method.setEnabled(False)
            self.ip_company_acct.setEnabled(False)
            self.ip_vendor_acct.setEnabled(False)
            self.ip_instr_no.setEnabled(False)
            self.ip_instr_date.setEnabled(False)
            self.ip_ref_no.setEnabled(False)
            self.ip_notes.setEnabled(False)

    def _reload_company_accounts(self):
        self.ip_company_acct.clear()
        try:
            conn = self.vendors.conn
            rows = conn.execute(
                "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
            ).fetchall()
            for r in rows:
                self.ip_company_acct.addItem(r["label"], int(r["account_id"]))
            
            
            current_method = self.ip_method.currentText()
            if current_method == self.PAYMENT_METHODS['OTHER']:
                self.ip_company_acct.setCurrentIndex(-1)  
        except ValueError:
            print("Error: Invalid company account ID")
            logging.exception("Invalid account ID in _reload_company_accounts")
        except Exception as e:
            print(f"Error loading company bank accounts: {e}")
            logging.exception("Error in _reload_company_accounts")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load company bank accounts: {str(e)}")

    def _reload_vendor_accounts(self):
        
        current_text = self.ip_vendor_acct.currentText()
        
        self.ip_vendor_acct.clear()
        vid = self.cmb_vendor.currentData()
        
        if not vid:
            
            self.ip_vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
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
                self.ip_vendor_acct.addItem(label, int(r["vba_id"]))
                if str(r["is_primary"]) in ("1","True","true"):
                    primary_account_added = True
            
            
            self.ip_vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
            
            
            previous_selection_restored = False
            if current_text and current_text != "":
                index = self.ip_vendor_acct.findText(current_text)
                if index >= 0:
                    self.ip_vendor_acct.setCurrentIndex(index)
                    previous_selection_restored = True
            
            
            
            current_method = self.ip_method.currentText()
            current_method_key = self._get_method_key(current_method)
            needs_vendor_account = current_method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK
            
            if not previous_selection_restored and primary_account_added and needs_vendor_account:
                
                for i in range(self.ip_vendor_acct.count() - 1):  
                    item_text = self.ip_vendor_acct.itemText(i)
                    if "(Primary)" in item_text:
                        self.ip_vendor_acct.setCurrentIndex(i)
                        break
            elif not previous_selection_restored and not needs_vendor_account:
                
                self.ip_vendor_acct.setCurrentIndex(-1)  
        
        except ValueError:
            print(f"Error: Invalid vendor ID: {vid}")
            logging.exception("Invalid vendor ID in _reload_vendor_accounts")
        except Exception as e:
            print(f"Error loading vendor bank accounts: {e}")
            logging.exception("Error in _reload_vendor_accounts")
            
            self.ip_vendor_acct.addItem("Temporary/External Bank Account", "TEMP_BANK")
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load vendor bank accounts: {str(e)}")

    def _refresh_ip_visibility(self):
        
        try:
            amount = float(self._to_float_safe(self.ip_amount.text()))
            if amount <= 0:
                
                self.ip_company_acct.setEnabled(False)
                self.ip_vendor_acct.setEnabled(False)
                self.ip_instr_no.setEnabled(False)
                self.ip_instr_date.setEnabled(False)
                
                self._reset_ip_labels()
                return
        except Exception as e:
            logging.exception("Error in _refresh_ip_visibility")
            self.ip_company_acct.setEnabled(False)
            self.ip_vendor_acct.setEnabled(False)
            self.ip_instr_no.setEnabled(False)
            self.ip_instr_date.setEnabled(False)
            
            self._reset_ip_labels()
            return

        method = self.ip_method.currentText()
        method_key = self._get_method_key(method)
        need_company = method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK
        need_vendor  = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        need_instr   = method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT
        need_idate   = method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT

        
        if amount > 0:
            
            if method == self.PAYMENT_METHODS['OTHER']:
                self.ip_company_acct.setEnabled(True)
                self.ip_vendor_acct.setEnabled(True)
                
                current_vendor_id = self.cmb_vendor.currentData()
                if current_vendor_id:
                    self._reload_vendor_accounts()
                
                self.ip_company_acct.setCurrentIndex(-1)
                self.ip_vendor_acct.setCurrentIndex(-1)
            else:
                self.ip_company_acct.setEnabled(need_company)
                self.ip_vendor_acct.setEnabled(need_vendor)
                
                
                
                if need_vendor:
                    current_vendor_id = self.cmb_vendor.currentData()
                    if current_vendor_id:
                        self._reload_vendor_accounts()  
            self.ip_instr_no.setEnabled(need_instr or method == self.PAYMENT_METHODS['OTHER'])  
            self.ip_instr_date.setEnabled(need_idate or method == self.PAYMENT_METHODS['OTHER'])  
        else:
            
            self.ip_company_acct.setEnabled(False)
            self.ip_vendor_acct.setEnabled(False)
            self.ip_instr_no.setEnabled(False)
            self.ip_instr_date.setEnabled(False)

        
        if hasattr(self, '_ip_labels'):
            self._update_ip_labels(need_company, need_vendor, need_instr)

        
        method = self.ip_method.currentText()
        method_key = self._get_method_key(method)
        need_vendor = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        selected_vendor_account = self.ip_vendor_acct.currentData()
        is_temp_account = selected_vendor_account == "TEMP_BANK"
        
        self._update_temp_bank_visibility(is_temp_account=is_temp_account, need_vendor=need_vendor)
        
    def _reset_ip_labels(self):
        """Reset all initial payment labels to normal state (non-required)"""
        if hasattr(self, '_ip_labels'):
            for label_key, label_widget in self._ip_labels.items():
                
                if label_widget.styleSheet() != "":
                    
                    plain_text = label_widget.text().rstrip('*')
                    label_widget.setText(plain_text)
                    label_widget.setStyleSheet("")
    
    def _update_ip_labels(self, need_company=False, need_vendor=False, need_instr=False):
        """Update initial payment section labels based on required fields"""
        if not hasattr(self, '_ip_labels'):
            return
            
        
        self._reset_ip_labels()
        
        
        if need_company and 'company_acct' in self._ip_labels:
            self._set_label_required(self._ip_labels['company_acct'])
        
        if need_vendor and 'vendor_acct' in self._ip_labels:
            self._set_label_required(self._ip_labels['vendor_acct'])
        
        if need_instr and 'instr_no' in self._ip_labels:
            self._set_label_required(self._ip_labels['instr_no'])

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
        """
        if is_temp_account is None:
            selected_value = self.ip_vendor_acct.currentData()
            is_temp_account = selected_value == "TEMP_BANK"
        
        if need_vendor is None:
            method = self.ip_method.currentText()
            need_vendor = method in (self.PAYMENT_METHODS['BANK_TRANSFER'], 
                                   self.PAYMENT_METHODS['CROSS_CHEQUE'], 
                                   self.PAYMENT_METHODS['CASH_DEPOSIT'])
        
        
        if is_temp_account and need_vendor:
            
            temp_name_label = self._ip_labels.get('temp_bank_name')
            if temp_name_label and not temp_name_label.text().endswith('*'):
                temp_name_label.setText(temp_name_label.text() + "*")
                temp_name_label.setStyleSheet("color: red; font-weight: bold;")
                
            temp_number_label = self._ip_labels.get('temp_bank_number')
            if temp_number_label and not temp_number_label.text().endswith('*'):
                temp_number_label.setText(temp_number_label.text() + "*")
                temp_number_label.setStyleSheet("color: red; font-weight: bold;")
                
            
            self.temp_bank_name.setVisible(True)
            self.temp_bank_number.setVisible(True)
            if 'temp_bank_name' in self._ip_labels:
                self._ip_labels['temp_bank_name'].setVisible(True)
            if 'temp_bank_number' in self._ip_labels:
                self._ip_labels['temp_bank_number'].setVisible(True)
        else:
            
            temp_name_label = self._ip_labels.get('temp_bank_name')
            if temp_name_label:
                temp_name_label.setText(temp_name_label.text().rstrip('*'))
                temp_name_label.setStyleSheet("")
                
            temp_number_label = self._ip_labels.get('temp_bank_number')
            if temp_number_label:
                temp_number_label.setText(temp_number_label.text().rstrip('*'))
                temp_number_label.setStyleSheet("")
                
            
            show_temp_fields = is_temp_account  
            self.temp_bank_name.setVisible(show_temp_fields)
            self.temp_bank_number.setVisible(show_temp_fields)
            if 'temp_bank_name' in self._ip_labels:
                self._ip_labels['temp_bank_name'].setVisible(show_temp_fields)
            if 'temp_bank_number' in self._ip_labels:
                self._ip_labels['temp_bank_number'].setVisible(show_temp_fields)

    def _on_vendor_bank_account_changed(self):
        """Show/hide temporary bank fields based on selection"""
        
        self._update_temp_bank_visibility()




    def _all_products(self):
        return self.products.list_products()

    def _base_uom_id(self, product_id: int) -> int | None:
        base = self.products.get_base_uom(product_id)
        if base: return int(base["uom_id"])
        u = self.products.list_uoms()
        if u:
            return int(u[0]["uom_id"])
        else:
            
            logging.error("No UOMs found in the system. Please configure at least one UOM.")
            return None

    def _delete_row_for_button(self, btn: QPushButton):
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 6) is btn:
                self.tbl.removeRow(r)
                self._reindex_rows()
                self._refresh_totals()
                return

    def _with_signal_blocking(self, widget, callback):
        """Helper to execute a callback with signal blocking."""
        widget.blockSignals(True)
        try:
            return callback()
        finally:
            widget.blockSignals(False)

    def _add_row(self, pre: dict | None = None):
        def on_prod_changed():
            pid = cmb_prod.currentData()
            if pid:
                uom_id = self._base_uom_id(int(pid))
                if uom_id is not None:
                    self.tbl.item(r, 0).setData(Qt.UserRole, uom_id)
            self._recalc_row(r); self._refresh_totals()

        r = self.tbl.rowCount()
        self.tbl.insertRow(r)

        num = QTableWidgetItem(str(r + 1))
        num.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 0, num)

        cmb_prod = QComboBox()
        cmb_prod.setEditable(True)
        product_names = [p.name for p in self._all_products()]
        completer = QCompleter(product_names, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        cmb_prod.setCompleter(completer)
        
        
        for p in self._all_products():
            cmb_prod.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.tbl.setCellWidget(r, 1, cmb_prod)

        for c in (2, 3, 4):
            it = QTableWidgetItem("0")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
            self.tbl.setItem(r, c, it)

        it_total = QTableWidgetItem("0.00")
        it_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_total.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 5, it_total)

        btn_del = QPushButton("✕")
        btn_del.clicked.connect(lambda _=False, b=btn_del: self._delete_row_for_button(b))
        self.tbl.setCellWidget(r, 6, btn_del)

        
        cmb_prod.currentIndexChanged.connect(on_prod_changed)

        
        if pre:
            def init_pre_populated_data():
                
                product_id = pre.get("product_id")
                i = cmb_prod.findData(product_id)
                if i >= 0:
                    cmb_prod.setCurrentIndex(i)
                
                
                self.tbl.item(r, 2).setText(str(pre.get("quantity", 0)))
                self.tbl.item(r, 3).setText(str(pre.get("purchase_price", 0)))
                self.tbl.item(r, 4).setText(str(pre.get("sale_price", 0)))
                
                
                if "uom_id" in pre:
                    self.tbl.item(r, 0).setData(Qt.UserRole, int(pre["uom_id"]))
                
                
                if product_id:
                    uom_id = self._base_uom_id(int(product_id))
                    if uom_id is not None:
                        self.tbl.item(r, 0).setData(Qt.UserRole, uom_id)
                
                
                self._recalc_row(r)
            
            
            cmb_prod.blockSignals(True)
            self._with_signal_blocking(self.tbl, init_pre_populated_data)
            cmb_prod.blockSignals(False)
        else:
            
            on_prod_changed()
            
            
            
            self._recalc_row(r)

        
        

    def _reindex_rows(self):
        for r in range(self.tbl.rowCount()):
            if self.tbl.item(r, 0):
                self.tbl.item(r, 0).setText(str(r + 1))

    def _rebuild_table(self):
        def rebuild_table_content():
            self.tbl.setRowCount(0)
            if not self._rows:
                self._add_row({})
            else:
                for row in self._rows:
                    self._add_row(row)
            self._refresh_totals()
            
            # Recalculate all visible rows to ensure all line totals are updated
            # This is necessary because programmatic value changes may not trigger _cell_changed
            for r in range(self.tbl.rowCount()):
                self._recalc_row(r)  # Calculate line total for each row once
            
            
            self._refresh_totals()
        
        self._with_signal_blocking(self.tbl, rebuild_table_content)

    def _cell_changed(self, row: int, col: int):
        if row < 0 or row >= self.tbl.rowCount():
            return
        
        if col in [2, 3, 4]:
            
            if self.tbl.item(row, col) is not None:
                self._recalc_row(row)
                self._refresh_totals()

    def _recalc_row(self, r: int):
        def num(c):
            it = self.tbl.item(r, c)
            return self._to_float_safe(it.text()) if it and it.text() else 0.0

        qty = num(2)
        buy = num(3)
        sale = num(4)

        def mark(col, bad):
            it = self.tbl.item(r, col)
            if it:
                it.setBackground(Qt.red if bad else Qt.white)

        bad_buy = buy <= 0
        bad_sale = (sale < buy) or (sale <= 0)  
        mark(3, bad_buy)
        mark(4, bad_sale or bad_buy)

        line_total = max(0.0, qty * buy)
        lt_item = self.tbl.item(r, 5)
        if lt_item:
            lt_item.setText(fmt_money(line_total))

    def _calc_subtotal(self) -> float:
        s = 0.0
        for r in range(self.tbl.rowCount()):
            try:
                qty = self._to_float_safe(self.tbl.item(r, 2).text() or "0")
                buy = self._to_float_safe(self.tbl.item(r, 3).text() or "0")
            except Exception:
                continue
            s += max(0.0, qty * buy)
        return s

    def _refresh_totals(self):
        sub = self._calc_subtotal()
        tot = sub
        self.lab_sub.setText(fmt_money(sub))
        self.lab_total.setText(fmt_money(tot))

    def _row_payload(self, r: int) -> dict | None:
        cmb_prod: QComboBox = self.tbl.cellWidget(r, 1)
        if not cmb_prod: return None
        pid = cmb_prod.currentData()
        if not pid: return None

        def num(c):
            it = self.tbl.item(r, c)
            return self._to_float_safe(it.text()) if it and it.text() else 0.0

        qty = num(2); buy = num(3); sale = num(4)
        if qty <= 0 or buy <= 0 or not (sale >= buy):
            return None
        uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
        if not uom_id:
            uom_id = self._base_uom_id(int(pid))
        if uom_id is None:
            return None  
        return {
            "product_id": int(pid),
            "uom_id": int(uom_id),
            "quantity": qty,
            "purchase_price": buy,
            "sale_price": sale,
            "item_discount": 0.0,
        }

    def _validate_vendor_selection(self) -> tuple[bool, str]:
        """Validate vendor selection and return (is_valid, error_message)"""
        vendor_id = self.cmb_vendor.currentData()
        if vendor_id is None or vendor_id == "":
            return False, "Please select a vendor from the dropdown list."
        return True, ""

    def _validate_date(self) -> tuple[bool, str]:
        """Validate date selection and return (is_valid, error_message)"""
        try:
            date_str = self.date.date().toString("yyyy-MM-dd")
            datetime.datetime.strptime(date_str, "%Y-%m-%d")  
            return True, ""
        except Exception:
            return False, "Please select a valid date."

    def _validate_items(self) -> tuple[bool, list[str], list[dict]]:
        """Validate purchase items and return (is_valid, error_messages, valid_rows)"""
        errors = []
        valid_rows = []
        
        for r in range(self.tbl.rowCount()):
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod:
                continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""):
                errors.append(f"Row {r+1}: Please select a product.")
                continue

            
            qty_it = self.tbl.item(r, 2)
            try:
                qty = self._to_float_safe((qty_it.text() or "0").strip())
                if qty <= 0:
                    errors.append(f"Row {r+1}: Quantity must be greater than 0.")
                    continue
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric quantity.")
                continue

            
            buy_it = self.tbl.item(r, 3)
            try:
                buy = self._to_float_safe((buy_it.text() or "0").strip())
                if buy <= 0:
                    errors.append(f"Row {r+1}: Purchase price must be greater than 0.")
                    continue
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric purchase price.")
                continue

            
            sale_it = self.tbl.item(r, 4)
            try:
                sale = self._to_float_safe((sale_it.text() or "0").strip())
                if sale < buy:
                    errors.append(f"Row {r+1}: Sale price must be greater than or equal to purchase price ({buy}).")
                    continue
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric sale price.")
                continue

            
            uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
            if uom_id is None:
                try:
                    uom_id = int(self.products.get_base_uom(product_id)["uom_id"])
                except Exception:
                    uom_id = self._base_uom_id(product_id)
            
            if uom_id is not None:
                valid_rows.append({
                    "product_id": int(product_id),
                    "uom_id": int(uom_id),
                    "quantity": qty,
                    "purchase_price": buy,
                    "sale_price": sale,
                    "item_discount": 0.0,
                })
            else:
                errors.append(f"Row {r+1}: Unable to determine UOM for product. Please configure UOM settings.")

        
        if not valid_rows:
            errors.append("Please add at least one valid purchase item.")

        return len(errors) == 0, errors, valid_rows

    def _resolve_company_account_id(self) -> int | None:
        """Resolve company bank account ID from editable combobox text"""
        company_acct_text = self.ip_company_acct.currentText().strip()
        company_id = self.ip_company_acct.currentData()
        
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
        
        try:
            resolved_vendor_id = int(self.cmb_vendor.currentData())
        except (ValueError, TypeError):
            logging.error("Vendor selection is required to resolve vendor bank account ID")
            return None  
        
        vendor_acct_text = self.ip_vendor_acct.currentText().strip()
        vendor_bank_id = self.ip_vendor_acct.currentData()
        
        if vendor_bank_id is None and vendor_acct_text:
            
            try:
                conn = self.vendors.conn
                
                row = conn.execute(
                    "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = ? AND vendor_id = ? AND is_active=1",
                    (vendor_acct_text, resolved_vendor_id)
                ).fetchone()
                if not row:
                    
                    row = conn.execute(
                        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE LOWER(label) = LOWER(?) AND vendor_id = ? AND is_active=1",
                        (vendor_acct_text, resolved_vendor_id)
                    ).fetchone()
                if row:
                    vendor_bank_id = int(row["vendor_bank_account_id"])
                else:
                    logging.warning(f"Vendor bank account not found for label: {vendor_acct_text} for vendor {resolved_vendor_id}")
            except Exception as e:
                logging.error(f"Error resolving vendor bank account ID for '{vendor_acct_text}' and vendor {resolved_vendor_id}: {e}")
                vendor_bank_id = None
        
        return vendor_bank_id

    def _validate_initial_payment(self, ip_amount: float) -> tuple[bool, list[str]]:
        """Validate initial payment details and return (is_valid, errors)"""
        errors = []
        
        if ip_amount < 0:
            errors.append("Initial payment amount cannot be negative.")
        elif ip_amount > 0:
            method = self.ip_method.currentText()
            
            selected_vendor_account = self.ip_vendor_acct.currentData()
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
                    
                    
                }
            }

            
            if method in validation_rules:
                rule = validation_rules[method]
                
                
                if rule.get('requires_company_acct', False) and self.ip_company_acct.currentData() is None:
                    errors.append(rule['error_msg_company'])
                
                
                if rule.get('requires_vendor_acct', False):
                    if self.ip_vendor_acct.currentData() is None:
                        errors.append(rule['error_msg_vendor'])
                    elif is_temp_account and rule.get('requires_temp_details', False):
                        
                        if not self.temp_bank_name.text().strip():
                            errors.append(rule['error_msg_temp_name'])
                        if not self.temp_bank_number.text().strip():
                            errors.append(rule['error_msg_temp_number'])
                
                
                if rule.get('requires_instr_no', False) and not self.ip_instr_no.text().strip():
                    errors.append(rule['error_msg_instr'])
            

        return len(errors) == 0, errors

    def get_payload(self) -> dict | None:
        
        
        
        vendor_id = int(self.cmb_vendor.currentData())
        date_str = self.date.date().toString("yyyy-MM-dd")
        total_amount = self._calc_subtotal()

        
        rows = []
        for r in range(self.tbl.rowCount()):
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod: continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""): continue
            
            def num(c):
                it = self.tbl.item(r, c)
                return self._to_float_safe(it.text()) if it and it.text() else 0.0

            qty = num(2); buy = num(3); sale = num(4)
            uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
            if uom_id is None:
                try:
                    uom_id = int(self.products.get_base_uom(product_id)["uom_id"])
                except Exception:
                    uom_id = self._base_uom_id(product_id)
            
            rows.append({
                "product_id": int(product_id),
                "uom_id": int(uom_id),
                "quantity": qty,
                "purchase_price": buy,
                "sale_price": sale,
                "item_discount": 0.0,
            })

        payload = {
            "vendor_id": vendor_id,
            "date": date_str,
            "order_discount": 0.0,
            "notes": (self.txt_notes.text().strip() or None),
            "items": rows,
            "total_amount": total_amount,
        }

        ip_amount_txt = self.ip_amount.text().strip()
        ip_amount = self._to_float_safe(ip_amount_txt)

        if ip_amount > 0:
            method = self.ip_method.currentText()
            
            
            company_id = self._resolve_company_account_id()
            vendor_bank_id = self._resolve_vendor_account_id()
            
            instr_no = self.ip_instr_no.text().strip()
            instr_date = self.ip_instr_date.date().toString("yyyy-MM-dd")
            ref_no = self.ip_ref_no.text().strip()
            notes = self.ip_notes.text().strip()

            if method == self.PAYMENT_METHODS['BANK_TRANSFER']:
                instr_type = "online";        clearing_state = "cleared"
            elif method == self.PAYMENT_METHODS['CHEQUE']:
                instr_type = "cheque";  clearing_state = "cleared"
            elif method == self.PAYMENT_METHODS['CROSS_CHEQUE']:
                instr_type = "cross_cheque";  clearing_state = "cleared"
            elif method == self.PAYMENT_METHODS['CASH_DEPOSIT']:
                instr_type = "cash_deposit";  clearing_state = "cleared"; company_id = None
            elif method == self.PAYMENT_METHODS['CASH']:
                instr_type = None
                clearing_state = "cleared"
                company_id = None;     vendor_bank_id = None
                instr_no = "";         instr_date = date_str
            else:  
                instr_type = "other";         clearing_state = "cleared"
                company_id = None;            vendor_bank_id = None
                instr_no = "";                instr_date = date_str

            
            selected_vendor_account = self.ip_vendor_acct.currentData()
            is_temp_account = selected_vendor_account == "TEMP_BANK"
            
            payload["initial_payment"] = {
                "amount": ip_amount,
                "method": method,
                "bank_account_id": int(company_id) if company_id else None,
                "vendor_bank_account_id": int(vendor_bank_id) if vendor_bank_id and not is_temp_account else None,
                "instrument_type": instr_type,
                "instrument_no": instr_no,
                "instrument_date": instr_date,
                "deposited_date": None,
                "cleared_date": None,
                "clearing_state": clearing_state,
                "ref_no": ref_no,
                "notes": notes,
                "date": date_str,
                
                "temp_vendor_bank_name": self.temp_bank_name.text().strip() if is_temp_account else None,
                "temp_vendor_bank_number": self.temp_bank_number.text().strip() if is_temp_account else None,
            }
            payload["initial_bank_account_id"] = payload["initial_payment"]["bank_account_id"]
            payload["initial_vendor_bank_account_id"] = payload["initial_payment"]["vendor_bank_account_id"]
            payload["initial_instrument_type"] = payload["initial_payment"]["instrument_type"]
            payload["initial_instrument_no"] = payload["initial_payment"]["instrument_no"]
            payload["initial_instrument_date"] = payload["initial_payment"]["instrument_date"]
            payload["initial_deposited_date"] = payload["initial_payment"]["deposited_date"]
            payload["initial_cleared_date"] = payload["initial_payment"]["cleared_date"]
            payload["initial_clearing_state"] = payload["initial_payment"]["clearing_state"]
            payload["initial_ref_no"] = payload["initial_payment"]["ref_no"]
            payload["initial_payment_notes"] = payload["initial_payment"]["notes"]
            payload["initial_method"] = payload["initial_payment"]["method"]

        return payload

    def validate_form(self) -> tuple[bool, list[str]]:  
        """Validate form and return detailed error messages"""
        errors = []
        
        
        
        is_valid, error_msg = self._validate_vendor_selection()
        if not is_valid:
            errors.append(error_msg)

        
        is_valid, error_msg = self._validate_date()
        if not is_valid:
            errors.append(error_msg)

        
        is_valid, item_errors, _ = self._validate_items()
        errors.extend(item_errors)

        
        try:
            ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
            ip_amount = self._to_float_safe(ip_amount_txt)

            if ip_amount < 0:
                errors.append("Initial payment amount cannot be negative.")
            elif ip_amount > 0:
                
                is_valid, payment_errors = self._validate_initial_payment(ip_amount)
                errors.extend(payment_errors)

        except Exception as e:
            errors.append("Error validating initial payment: " + str(e))

        return len(errors) == 0, errors

    def accept(self):
        is_valid, errors = self.validate_form()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            error_message = self._format_validation_errors(errors)
            QMessageBox.warning(self, "Validation Errors", error_message)
            return
        p = self.get_payload()
        if p is None:
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing/Invalid Fields",
                                "Please enter valid purchase details (all required fields must be filled).")
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload

    def _format_validation_errors(self, errors: list[str]) -> str:
        """Format validation errors into a user-friendly message."""
        if not errors:
            return ""
        return "Please correct the following errors:\n\n" + "\n".join([f"• {err}" for err in errors])

    def _validate_and_perform_action(self, action_func):
        """Validate form and perform the given action if valid"""
        is_valid, errors = self.validate_form()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            error_message = self._format_validation_errors(errors)
            QMessageBox.warning(self, "Validation Errors", error_message)
            return False
        
        
        return action_func()

    def _save_clicked(self):
        """Handle save button click"""
        def save_action():
            
            self.accept()
            return True
        
        self._validate_and_perform_action(save_action)

    def _print_clicked(self):
        """Handle print button click"""
        def print_action():
            
            self.accept()  
            
            
            return True
            
        self._validate_and_perform_action(print_action)

    def _pdf_export_clicked(self):
        """Handle PDF export button click"""
        def pdf_export_action():
            
            self.accept()
            
            return True
            
        self._validate_and_perform_action(pdf_export_action)


