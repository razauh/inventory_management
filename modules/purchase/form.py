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

TRASH_ICON = None


class PurchaseForm(QDialog):
    COLS = ["#", "Product", "Qty", "Buy Price", "Sale Price", "Line Total", ""]

    def __init__(self, parent=None, vendors: VendorsRepo | None = None,
                 products: ProductsRepo | None = None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase")
        self.setModal(True)
        self.vendors = vendors
        self.products = products
        self._payload = None

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

        # Determine if this is an edit operation (has initial data)
        is_edit_mode = bool(initial)
        
        ip_box = QGroupBox("Initial Payment (optional)")
        
        # Disable the entire initial payment section if in edit mode
        if is_edit_mode:
            ip_box.setEnabled(False)
            ip_box.setTitle("Initial Payment (disabled during edit - use Payments section)")
        
        ipg = QGridLayout(ip_box)
        ipg.setHorizontalSpacing(12); ipg.setVerticalSpacing(8)

        self.ip_amount = QLineEdit(); self.ip_amount.setPlaceholderText("0")
        self.ip_date = QDateEdit(); self.ip_date.setCalendarPopup(True); self.ip_date.setDate(self.date.date())

        self.ip_method = QComboBox()
        self.ip_method.addItems(["Cash", "Bank Transfer", "Cheque", "Cash Deposit", "Other"])

        self.ip_company_acct = QComboBox(); self.ip_company_acct.setEditable(True)
        self.ip_vendor_acct  = QComboBox(); self.ip_vendor_acct.setEditable(True)
        self.ip_instr_no   = QLineEdit(); self.ip_instr_no.setPlaceholderText("Instrument / Cheque / Slip #")
        self.ip_instr_date = QDateEdit(); self.ip_instr_date.setCalendarPopup(True); self.ip_instr_date.setDate(self.ip_date.date())
        self.ip_ref_no     = QLineEdit(); self.ip_ref_no.setPlaceholderText("Reference (optional)")
        self.ip_notes      = QLineEdit(); self.ip_notes.setPlaceholderText("Notes (optional)")

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
            return label  # Return the label widget so it can be modified dynamically

        # Create labels for payment section and store references for dynamic updates
        self._ip_labels = {}
        
        add_ip(0, 0, "Amount", self.ip_amount, required=False)
        add_ip(0, 1, "Payment Date", self.ip_date, required=False)
        add_ip(1, 0, "Method", self.ip_method, required=False)
        self._ip_labels['company_acct'] = add_ip(1, 1, "Company Bank Account", self.ip_company_acct, required=False)
        self._ip_labels['vendor_acct'] = add_ip(2, 0, "Vendor Bank Account", self.ip_vendor_acct, required=False)
        self._ip_labels['instr_no'] = add_ip(2, 1, "Instrument No", self.ip_instr_no, required=False)
        add_ip(3, 0, "Instrument Date", self.ip_instr_date, required=False)
        add_ip(3, 1, "Ref No", self.ip_ref_no, required=False)
        ipg.addWidget(QLabel("Payment Notes"), 4, 0)
        ipg.addWidget(self.ip_notes, 4, 1, 1, 3)
        ipg.setColumnStretch(1, 1)
        ipg.setColumnStretch(3, 1)

        self._ip_instrument_type = None
        self._ip_clearing_state = None

        # Disable all initial payment controls if in edit mode
        if is_edit_mode:
            for widget in [self.ip_amount, self.ip_date, self.ip_method, 
                          self.ip_company_acct, self.ip_vendor_acct, 
                          self.ip_instr_no, self.ip_instr_date, 
                          self.ip_ref_no, self.ip_notes]:
                widget.setEnabled(False)

        main_layout.addWidget(ip_box, 0)

        # Create custom button box to have Save and Print buttons instead of default OK
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.save_button = QPushButton("Save")
        self.print_button = QPushButton("Print")
        self.pdf_export_button = QPushButton("Export to PDF")
        button_box.addButton(self.save_button, QDialogButtonBox.AcceptRole)
        button_box.addButton(self.print_button, QDialogButtonBox.ActionRole)
        button_box.addButton(self.pdf_export_button, QDialogButtonBox.ActionRole)
        
        # Connect buttons to specific methods
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

        if initial:
            idx = self.cmb_vendor.findData(initial["vendor_id"])
            if idx >= 0: self.cmb_vendor.setCurrentIndex(idx)
            self.txt_notes.setText(initial.get("notes") or "")

        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_ip_visibility()
        self._rebuild_table()
        self._refresh_totals()
        # Set initial state for payment fields based on amount
        self._toggle_ip_fields_by_amount()
        self.resize(1100, 700)
        self.setMinimumSize(860, 560)
        self.setSizeGripEnabled(True)

    def _to_float_safe(self, txt: str) -> float:
        cleaned = re.sub(r"[^0-9.\-]", "", (txt or ""))
        try:
            return float(cleaned) if cleaned else 0.0
        except Exception:
            return 0.0

    def _toggle_ip_fields_by_amount(self):
        try:
            amount = float(self._to_float_safe(self.ip_amount.text()))
            enable_fields = amount > 0

            # Set enable state for all initial payment fields except amount
            self.ip_date.setEnabled(enable_fields)
            self.ip_method.setEnabled(enable_fields)
            self.ip_company_acct.setEnabled(enable_fields and self.ip_method.currentText() in ("Bank Transfer", "Cheque", "Cash Deposit"))
            self.ip_vendor_acct.setEnabled(enable_fields and self.ip_method.currentText() in ("Bank Transfer", "Cheque", "Cash Deposit"))
            self.ip_instr_no.setEnabled(enable_fields and self.ip_method.currentText() in ("Bank Transfer", "Cheque", "Cash Deposit"))
            self.ip_instr_date.setEnabled(enable_fields and self.ip_method.currentText() in ("Bank Transfer", "Cheque", "Cash Deposit"))
            self.ip_ref_no.setEnabled(enable_fields)
            self.ip_notes.setEnabled(enable_fields)

            # If amount is 0, reset method to Cash to avoid confusion
            if not enable_fields and self.ip_method.currentText() != "Cash":
                self.ip_method.setCurrentText("Cash")
                
            # Update method-specific visibility when amount changes
            if enable_fields:
                # Also reload vendor accounts if current payment method requires them
                method = self.ip_method.currentText()
                need_vendor = method in ("Bank Transfer", "Cheque", "Cash Deposit")
                if need_vendor and self.cmb_vendor.currentData():
                    self._reload_vendor_accounts()
                self._refresh_ip_visibility()
            else:
                # For disabled fields, ensure method-specific fields are also disabled
                self.ip_company_acct.setEnabled(False)
                self.ip_vendor_acct.setEnabled(False)
                self.ip_vendor_acct.clear()  # Clear dropdown when disabling
                self.ip_instr_no.setEnabled(False)
                self.ip_instr_date.setEnabled(False)
        except Exception as e:
            # Show specific error message instead of silently failing
            import logging
            logging.exception("Error in _toggle_ip_fields_by_amount")
            # If parsing fails, disable fields except amount
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
        except ValueError:
            # Handle issues with converting account_id to int
            print("Error: Invalid company account ID")
            import logging
            logging.exception("Invalid account ID in _reload_company_accounts")
        except Exception as e:
            # Show specific error message instead of silently failing
            print(f"Error loading company bank accounts: {e}")
            import logging
            logging.exception("Error in _reload_company_accounts")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load company bank accounts: {str(e)}")

    def _reload_vendor_accounts(self):
        self.ip_vendor_acct.clear()
        vid = self.cmb_vendor.currentData()
        if not vid:
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
            for r in rows:
                label = r["label"] + (" (Primary)" if str(r["is_primary"]) in ("1","True","true") else "")
                self.ip_vendor_acct.addItem(label, int(r["vba_id"]))
        except ValueError:
            # Handle issues with converting vid to int
            print(f"Error: Invalid vendor ID: {vid}")
            import logging
            logging.exception("Invalid vendor ID in _reload_vendor_accounts")
        except Exception as e:
            # Show specific error message instead of silently failing
            print(f"Error loading vendor bank accounts: {e}")
            import logging
            logging.exception("Error in _reload_vendor_accounts")
            # Optionally show an error to the user if there's a GUI error reporting mechanism
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not load vendor bank accounts: {str(e)}")

    def _refresh_ip_visibility(self):
        # Only apply method-specific field activation if amount > 0
        try:
            amount = float(self._to_float_safe(self.ip_amount.text()))
            if amount <= 0:
                # If amount is 0 or less, disable method-specific fields
                self.ip_company_acct.setEnabled(False)
                self.ip_vendor_acct.setEnabled(False)
                self.ip_instr_no.setEnabled(False)
                self.ip_instr_date.setEnabled(False)
                return
        except Exception as e:
            # Show specific error message instead of silently failing
            import logging
            logging.exception("Error in _refresh_ip_visibility")
            # If parsing fails, disable method-specific fields
            self.ip_company_acct.setEnabled(False)
            self.ip_vendor_acct.setEnabled(False)
            self.ip_instr_no.setEnabled(False)
            self.ip_instr_date.setEnabled(False)
            return

        method = self.ip_method.currentText()
        need_company = method in ("Bank Transfer", "Cheque", "Cash Deposit")
        need_vendor  = method in ("Bank Transfer", "Cheque", "Cash Deposit")
        need_instr   = method in ("Bank Transfer", "Cheque", "Cash Deposit")
        need_idate   = method in ("Bank Transfer", "Cheque", "Cash Deposit")

        # Only update if amount > 0 (fields should be enabled)
        if amount > 0:
            self.ip_company_acct.setEnabled(need_company)
            self.ip_vendor_acct.setEnabled(need_vendor)
            # When vendor bank account is enabled for certain payment methods,
            # make sure to reload the vendor accounts for the currently selected vendor
            if need_vendor:
                self._reload_vendor_accounts()  # This will populate the dropdown with accounts for the selected vendor
            self.ip_instr_no.setEnabled(need_instr)
            self.ip_instr_date.setEnabled(need_idate)
        else:
            # Double-check: if amount <= 0, disable these fields
            self.ip_company_acct.setEnabled(False)
            self.ip_vendor_acct.setEnabled(False)
            self.ip_instr_no.setEnabled(False)
            self.ip_instr_date.setEnabled(False)

        # Update the payment section labels dynamically based on required fields
        if hasattr(self, '_ip_labels'):
            # Reset all labels to normal first
            for label_key, label_widget in self._ip_labels.items():
                # Remove any existing required styling
                if label_widget.styleSheet() != "":
                    # Reset to normal label
                    plain_text = label_widget.text().rstrip('*')
                    label_widget.setText(plain_text)
                    label_widget.setStyleSheet("")
            
            # Now apply required styling to the appropriate labels based on method
            if need_company and 'company_acct' in self._ip_labels:
                company_label = self._ip_labels['company_acct']
                current_text = company_label.text()
                if not current_text.endswith("*"):
                    company_label.setText(current_text + "*")
                    company_label.setStyleSheet("color: red; font-weight: bold;")
            
            if need_vendor and 'vendor_acct' in self._ip_labels:
                vendor_label = self._ip_labels['vendor_acct']
                current_text = vendor_label.text()
                if not current_text.endswith("*"):
                    vendor_label.setText(current_text + "*")
                    vendor_label.setStyleSheet("color: red; font-weight: bold;")
            
            if need_instr and 'instr_no' in self._ip_labels:
                instr_label = self._ip_labels['instr_no']
                current_text = instr_label.text()
                if not current_text.endswith("*"):
                    instr_label.setText(current_text + "*")
                    instr_label.setStyleSheet("color: red; font-weight: bold;")

        m = method
        if m == "Bank Transfer":
            self._ip_instrument_type = "online";        self._ip_clearing_state = "posted"
        elif m == "Cheque":
            self._ip_instrument_type = "cross_cheque";  self._ip_clearing_state = "pending"
        elif m == "Cash Deposit":
            self._ip_instrument_type = "cash_deposit";  self._ip_clearing_state = "pending"
        elif m == "Cash":
            self._ip_instrument_type = "cash";          self._ip_clearing_state = "cleared"
        else:
            self._ip_instrument_type = "other";         self._ip_clearing_state = "pending"

    def _all_products(self):
        return self.products.list_products()

    def _base_uom_id(self, product_id: int) -> int:
        base = self.products.get_base_uom(product_id)
        if base: return int(base["uom_id"])
        u = self.products.list_uoms()
        return int(u[0]["uom_id"]) if u else 1

    def _delete_row_for_button(self, btn: QPushButton):
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 6) is btn:
                self.tbl.removeRow(r)
                self._reindex_rows()
                self._refresh_totals()
                return

    def _add_row(self, pre: dict | None = None):
        self.tbl.blockSignals(True)
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
        
        # Add items to combo
        for p in self._all_products():
            cmb_prod.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.tbl.setCellWidget(r, 1, cmb_prod)

        for c in (2, 3, 4):
            it = QTableWidgetItem("0")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, c, it)

        it_total = QTableWidgetItem("0.00")
        it_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_total.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 5, it_total)

        btn_del = QPushButton("✕")
        btn_del.clicked.connect(lambda _=False, b=btn_del: self._delete_row_for_button(b))
        self.tbl.setCellWidget(r, 6, btn_del)

        def on_prod_changed():
            pid = cmb_prod.currentData()
            self.tbl.item(r, 0).setData(Qt.UserRole, self._base_uom_id(int(pid)) if pid else None)
            self._recalc_row(r); self._refresh_totals()
        cmb_prod.currentIndexChanged.connect(on_prod_changed)

        if pre:
            i = cmb_prod.findData(pre.get("product_id"))
            if i >= 0: cmb_prod.setCurrentIndex(i)
            self.tbl.item(r, 2).setText(str(pre.get("quantity", 0)))
            self.tbl.item(r, 3).setText(str(pre.get("purchase_price", 0)))
            self.tbl.item(r, 4).setText(str(pre.get("sale_price", 0)))
            if "uom_id" in pre:
                self.tbl.item(r, 0).setData(Qt.UserRole, int(pre["uom_id"]))
            on_prod_changed()
        else:
            on_prod_changed()

        self.tbl.blockSignals(False)
        self._recalc_row(r)

    def _reindex_rows(self):
        for r in range(self.tbl.rowCount()):
            if self.tbl.item(r, 0):
                self.tbl.item(r, 0).setText(str(r + 1))

    def _rebuild_table(self):
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        if not self._rows:
            self._add_row({})
        else:
            for row in self._rows:
                self._add_row(row)
        self.tbl.blockSignals(False)
        self._refresh_totals()

    def _cell_changed(self, row: int, col: int):
        if row < 0 or row >= self.tbl.rowCount():
            return
        for c in (2, 3, 4, 5):
            if self.tbl.item(row, c) is None and self.tbl.cellWidget(row, c) is None:
                return
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
        bad_sale = not (sale >= buy > 0)
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
        return {
            "product_id": int(pid),
            "uom_id": int(uom_id),
            "quantity": qty,
            "purchase_price": buy,
            "sale_price": sale,
            "item_discount": 0.0,
        }

    def get_payload(self) -> dict | None:
        try:
            vendor_id = int(self.cmb_vendor.currentData())
        except Exception:
            return None

        rows = []
        for r in range(self.tbl.rowCount()):
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod: continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""): continue
            qty_it = self.tbl.item(r, 2)
            buy_it = self.tbl.item(r, 3)
            sale_it = self.tbl.item(r, 4)
            try:
                qty = self._to_float_safe((qty_it.text() or "0").strip())
                buy = self._to_float_safe((buy_it.text() or "0").strip())
                sale = self._to_float_safe((sale_it.text() or "0").strip())
            except Exception:
                return None
            if qty <= 0 or buy <= 0 or not (sale >= buy):
                return None
            uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
            if uom_id is None:
                try:
                    uom_id = int(self.products.get_base_uom(product_id)["uom_id"])
                except Exception:
                    uom_id = self._base_uom_id(product_id)
            if uom_id is None: return None
            rows.append({
                "product_id": int(product_id),
                "uom_id": int(uom_id),
                "quantity": qty,
                "purchase_price": buy,
                "sale_price": sale,
                "item_discount": 0.0,
            })

        if not rows: return None

        date_str = self.date.date().toString("yyyy-MM-dd")
        total_amount = self._calc_subtotal()

        payload = {
            "vendor_id": vendor_id,
            "date": date_str,
            "order_discount": 0.0,
            "notes": (self.txt_notes.text().strip() or None),
            "items": rows,
            "total_amount": total_amount,
        }

        ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
        ip_amount = self._to_float_safe(ip_amount_txt)

        if ip_amount_txt and ip_amount < 0.0:
            return None

        if ip_amount > 0:
            method = self.ip_method.currentText() if hasattr(self, "ip_method") else ""
            
            # Handle editable comboboxes: if currentData() is None, try to find the ID by looking up the text
            # First ensure vendor_id is available as it's needed for vendor bank account lookup
            try:
                resolved_vendor_id = int(self.cmb_vendor.currentData())
            except Exception:
                return None  # vendor selection is required
            
            company_acct_text = self.ip_company_acct.currentText().strip() if hasattr(self, "ip_company_acct") and self.ip_company_acct.currentText() else ""
            company_id = self.ip_company_acct.currentData() if hasattr(self, "ip_company_acct") else None
            if company_id is None and company_acct_text:
                # Look up company account ID by label/text (with case-insensitive matching)
                try:
                    conn = self.vendors.conn
                    # First try exact match
                    row = conn.execute(
                        "SELECT account_id FROM company_bank_accounts WHERE label = ? AND is_active=1",
                        (company_acct_text,)
                    ).fetchone()
                    if not row:
                        # Try case-insensitive match
                        row = conn.execute(
                            "SELECT account_id FROM company_bank_accounts WHERE LOWER(label) = LOWER(?) AND is_active=1",
                            (company_acct_text,)
                        ).fetchone()
                    if row:
                        company_id = int(row["account_id"])
                except Exception:
                    company_id = None
            
            vendor_acct_text = self.ip_vendor_acct.currentText().strip() if hasattr(self, "ip_vendor_acct") and self.ip_vendor_acct.currentText() else ""
            vendor_bank_id = self.ip_vendor_acct.currentData() if hasattr(self, "ip_vendor_acct") else None
            if vendor_bank_id is None and vendor_acct_text:
                # Look up vendor account ID by label/text (with case-insensitive matching)
                try:
                    conn = self.vendors.conn
                    # First try exact match
                    row = conn.execute(
                        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = ? AND vendor_id = ? AND is_active=1",
                        (vendor_acct_text, resolved_vendor_id)
                    ).fetchone()
                    if not row:
                        # Try case-insensitive match
                        row = conn.execute(
                            "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE LOWER(label) = LOWER(?) AND vendor_id = ? AND is_active=1",
                            (vendor_acct_text, resolved_vendor_id)
                        ).fetchone()
                    if row:
                        vendor_bank_id = int(row["vendor_bank_account_id"])
                except Exception:
                    vendor_bank_id = None
            
            instr_no = self.ip_instr_no.text().strip() if hasattr(self, "ip_instr_no") else ""
            instr_date = self.ip_instr_date.date().toString("yyyy-MM-dd") if hasattr(self, "ip_instr_date") else date_str
            ref_no = self.ip_ref_no.text().strip() if hasattr(self, "ip_ref_no") else None
            notes = self.ip_notes.text().strip() if hasattr(self, "ip_notes") else None

            m = (method or "").strip().lower()
            if m == "bank transfer":
                if not company_id or not vendor_bank_id or not instr_no: return None
                instr_type = "online";        clearing_state = "posted"
            elif m == "cheque":
                if not company_id or not vendor_bank_id or not instr_no: return None
                instr_type = "cross_cheque";  clearing_state = "pending"
            elif m == "cash deposit":
                if not vendor_bank_id or not instr_no: return None
                instr_type = "cash_deposit";  clearing_state = "pending"; company_id = None
            elif m == "cash":
                instr_type = None
                clearing_state = None  # controller will default cash → 'cleared'
                company_id = None;     vendor_bank_id = None
                instr_no = "";         instr_date = date_str
            else:
                instr_type = "other";         clearing_state = "pending"
                company_id = None;            vendor_bank_id = None
                instr_no = "";                instr_date = date_str

            payload["initial_payment"] = {
                "amount": ip_amount,
                "method": method,
                "bank_account_id": int(company_id) if company_id else None,
                "vendor_bank_account_id": int(vendor_bank_id) if vendor_bank_id else None,
                "instrument_type": instr_type,
                "instrument_no": instr_no,
                "instrument_date": instr_date,
                "deposited_date": None,
                "cleared_date": None,
                "clearing_state": clearing_state,
                "ref_no": ref_no,
                "notes": notes,
                "date": date_str,
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

    def validate_form(self) -> tuple[bool, list[str]]:  # (is_valid, list_of_error_messages)
        """Validate form and return detailed error messages"""
        errors = []
        
        # Validate vendor
        vendor_id = self.cmb_vendor.currentData()
        if vendor_id is None or vendor_id == "":
            errors.append("Please select a vendor from the dropdown list.")

        # Validate date
        try:
            date_str = self.date.date().toString("yyyy-MM-dd")
            import datetime
            datetime.datetime.strptime(date_str, "%Y-%m-%d")  # Basic date validation
        except:
            errors.append("Please select a valid date.")

        # Validate items
        valid_rows = []
        for r in range(self.tbl.rowCount()):
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod:
                continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""):
                errors.append(f"Row {r+1}: Please select a product.")
                continue

            # Validate quantity
            qty_it = self.tbl.item(r, 2)
            try:
                qty = self._to_float_safe((qty_it.text() or "0").strip())
                if qty <= 0:
                    errors.append(f"Row {r+1}: Quantity must be greater than 0.")
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric quantity.")

            # Validate purchase price
            buy_it = self.tbl.item(r, 3)
            try:
                buy = self._to_float_safe((buy_it.text() or "0").strip())
                if buy <= 0:
                    errors.append(f"Row {r+1}: Purchase price must be greater than 0.")
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric purchase price.")

            # Validate sale price
            sale_it = self.tbl.item(r, 4)
            try:
                sale = self._to_float_safe((sale_it.text() or "0").strip())
                if sale < buy:
                    errors.append(f"Row {r+1}: Sale price must be greater than or equal to purchase price ({buy}).")
            except:
                errors.append(f"Row {r+1}: Please enter a valid numeric sale price.")

        # If no valid rows were found
        if not any(cmb_prod.currentData() for r in range(self.tbl.rowCount()) if (cmb_prod := self.tbl.cellWidget(r, 1))):
            errors.append("Please add at least one valid purchase item.")

        # Validate initial payment if amount is specified
        try:
            ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
            ip_amount = self._to_float_safe(ip_amount_txt)

            if ip_amount < 0:
                errors.append("Initial payment amount cannot be negative.")
            elif ip_amount > 0:
                method = self.ip_method.currentText() if hasattr(self, "ip_method") else ""
                m = (method or "").strip().lower()

                if m in ["bank transfer", "cheque"]:
                    if self.ip_company_acct.currentData() is None:
                        errors.append(f"For {method}, please select a company bank account.")
                    if self.ip_vendor_acct.currentData() is None:
                        errors.append(f"For {method}, please select a vendor bank account.")
                    if not self.ip_instr_no.text().strip():
                        errors.append(f"For {method}, please enter the instrument/cheque number.")
                elif m == "cash deposit":
                    if self.ip_vendor_acct.currentData() is None:
                        errors.append(f"For {method}, please select a vendor bank account.")
                    if not self.ip_instr_no.text().strip():
                        errors.append(f"For {method}, please enter the deposit slip number.")

        except Exception as e:
            errors.append("Error validating initial payment: " + str(e))

        return len(errors) == 0, errors

    def accept(self):
        is_valid, errors = self.validate_form()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            error_message = "Please correct the following errors:\n\n" + "\n".join([f"• {err}" for err in errors])
            QMessageBox.warning(self, "Validation Errors", error_message)
            return
        p = self.get_payload()
        if p is None:
            # Fallback for any remaining validation issues
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing/Invalid Fields",
                                "Please enter valid purchase details (all required fields must be filled).")
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload

    def _save_clicked(self):
        """Handle save button click"""
        if not self.validate_form()[0]:
            return
        # Set flag to indicate this is a regular save (not print)
        self._should_print = False
        self._should_export_pdf = False
        self.accept()

    def _print_clicked(self):
        """Handle print button click"""
        if not self.validate_form()[0]:
            return
        # Set flag to indicate this is a print request
        self._should_print = True
        self._should_export_pdf = False
        self.accept()

    def _pdf_export_clicked(self):
        """Handle PDF export button click"""
        if not self.validate_form()[0]:
            return
        # Set flag to indicate this is a PDF export request
        self._should_print = False
        self._should_export_pdf = True
        self.accept()

    def get_payload(self) -> dict | None:
        try:
            vendor_id = int(self.cmb_vendor.currentData())
        except Exception:
            return None

        rows = []
        for r in range(self.tbl.rowCount()):
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod: continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""): continue
            qty_it = self.tbl.item(r, 2)
            buy_it = self.tbl.item(r, 3)
            sale_it = self.tbl.item(r, 4)
            try:
                qty = self._to_float_safe((qty_it.text() or "0").strip())
                buy = self._to_float_safe((buy_it.text() or "0").strip())
                sale = self._to_float_safe((sale_it.text() or "0").strip())
            except Exception:
                return None
            if qty <= 0 or buy <= 0 or not (sale >= buy):
                return None
            uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
            if uom_id is None:
                try:
                    uom_id = int(self.products.get_base_uom(product_id)["uom_id"])
                except Exception:
                    uom_id = self._base_uom_id(product_id)
            if uom_id is None: return None
            rows.append({
                "product_id": int(product_id),
                "uom_id": int(uom_id),
                "quantity": qty,
                "purchase_price": buy,
                "sale_price": sale,
                "item_discount": 0.0,
            })

        if not rows: return None

        date_str = self.date.date().toString("yyyy-MM-dd")
        total_amount = self._calc_subtotal()

        payload = {
            "vendor_id": vendor_id,
            "date": date_str,
            "order_discount": 0.0,
            "notes": (self.txt_notes.text().strip() or None),
            "items": rows,
            "total_amount": total_amount,
        }

        ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
        ip_amount = self._to_float_safe(ip_amount_txt)

        if ip_amount_txt and ip_amount < 0.0:
            return None

        if ip_amount > 0:
            method = self.ip_method.currentText() if hasattr(self, "ip_method") else ""
            
            # Handle editable comboboxes: if currentData() is None, try to find the ID by looking up the text
            # First ensure vendor_id is available as it's needed for vendor bank account lookup
            try:
                resolved_vendor_id = int(self.cmb_vendor.currentData())
            except Exception:
                return None  # vendor selection is required
            
            company_acct_text = self.ip_company_acct.currentText().strip() if hasattr(self, "ip_company_acct") and self.ip_company_acct.currentText() else ""
            company_id = self.ip_company_acct.currentData() if hasattr(self, "ip_company_acct") else None
            if company_id is None and company_acct_text:
                # Look up company account ID by label/text (with case-insensitive matching)
                try:
                    conn = self.vendors.conn
                    # First try exact match
                    row = conn.execute(
                        "SELECT account_id FROM company_bank_accounts WHERE label = ? AND is_active=1",
                        (company_acct_text,)
                    ).fetchone()
                    if not row:
                        # Try case-insensitive match
                        row = conn.execute(
                            "SELECT account_id FROM company_bank_accounts WHERE LOWER(label) = LOWER(?) AND is_active=1",
                            (company_acct_text,)
                        ).fetchone()
                    if row:
                        company_id = int(row["account_id"])
                except Exception:
                    company_id = None
            
            vendor_acct_text = self.ip_vendor_acct.currentText().strip() if hasattr(self, "ip_vendor_acct") and self.ip_vendor_acct.currentText() else ""
            vendor_bank_id = self.ip_vendor_acct.currentData() if hasattr(self, "ip_vendor_acct") else None
            if vendor_bank_id is None and vendor_acct_text:
                # Look up vendor account ID by label/text (with case-insensitive matching)
                try:
                    conn = self.vendors.conn
                    # First try exact match
                    row = conn.execute(
                        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = ? AND vendor_id = ? AND is_active=1",
                        (vendor_acct_text, resolved_vendor_id)
                    ).fetchone()
                    if not row:
                        # Try case-insensitive match
                        row = conn.execute(
                            "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE LOWER(label) = LOWER(?) AND vendor_id = ? AND is_active=1",
                            (vendor_acct_text, resolved_vendor_id)
                        ).fetchone()
                    if row:
                        vendor_bank_id = int(row["vendor_bank_account_id"])
                except Exception:
                    vendor_bank_id = None
            
            instr_no = self.ip_instr_no.text().strip() if hasattr(self, "ip_instr_no") else ""
            instr_date = self.ip_instr_date.date().toString("yyyy-MM-dd") if hasattr(self, "ip_instr_date") else date_str
            ref_no = self.ip_ref_no.text().strip() if hasattr(self, "ip_ref_no") else None
            notes = self.ip_notes.text().strip() if hasattr(self, "ip_notes") else None

            m = (method or "").strip().lower()
            if m == "bank transfer":
                if not company_id or not vendor_bank_id or not instr_no: return None
                instr_type = "online";        clearing_state = "posted"
            elif m == "cheque":
                if not company_id or not vendor_bank_id or not instr_no: return None
                instr_type = "cross_cheque";  clearing_state = "pending"
            elif m == "cash deposit":
                if not vendor_bank_id or not instr_no: return None
                instr_type = "cash_deposit";  clearing_state = "pending"; company_id = None
            elif m == "cash":
                instr_type = None
                clearing_state = None  # controller will default cash → 'cleared'
                company_id = None;     vendor_bank_id = None
                instr_no = "";         instr_date = date_str
            else:
                instr_type = "other";         clearing_state = "pending"
                company_id = None;            vendor_bank_id = None
                instr_no = "";                instr_date = date_str

            payload["initial_payment"] = {
                "amount": ip_amount,
                "method": method,
                "bank_account_id": int(company_id) if company_id else None,
                "vendor_bank_account_id": int(vendor_bank_id) if vendor_bank_id else None,
                "instrument_type": instr_type,
                "instrument_no": instr_no,
                "instrument_date": instr_date,
                "deposited_date": None,
                "cleared_date": None,
                "clearing_state": clearing_state,
                "ref_no": ref_no,
                "notes": notes,
                "date": date_str,
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

        # Add the print and PDF export flags to the payload
        if hasattr(self, '_should_print'):
            payload['_should_print'] = self._should_print
        if hasattr(self, '_should_export_pdf'):
            payload['_should_export_pdf'] = self._should_export_pdf

        return payload
