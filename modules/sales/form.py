from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QPushButton, QAbstractItemView, QCompleter, QWidget, QGridLayout, QSplitter,
    QFrame, QHeaderView
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt, QDate
from ...database.repositories.customers_repo import CustomersRepo
    # (bank account repo is passed in, not imported here)
from ...database.repositories.products_repo import ProductsRepo
from ...database.repositories.sales_repo import SalesRepo
from ...utils.helpers import today_str, fmt_money
from ...utils.ui_helpers import info  # <-- added for visible validation messages


class SaleForm(QDialog):
    # Columns now include Base/Alt UoM and expanded totals logic
    COLS = ["#", "Product", "Base UoM", "Alt UoM", "Avail", "Qty", "Unit Price", "Discount", "Margin", "Line Total", ""]

    def __init__(
        self,
        parent=None,
        customers: CustomersRepo | None = None,
        products: ProductsRepo | None = None,
        sales_repo=None,  # sales repository to load payment history
        db_path=None,  # database path to create payment repo
        bank_accounts=None,  # repo instance providing list_company_bank_accounts(); kept optional, no import here
        initial=None,
        mode: str = "sale",   # <-- NEW: 'sale' | 'quotation'
    ):
        super().__init__(parent)
        self.mode = "quotation" if str(mode).lower() == "quotation" else "sale"
        self.setWindowTitle("Quotation" if self.mode == "quotation" else "Sale")

        # Match PurchaseForm pattern: start modal, then switch to non-modal
        self.setModal(True)  # Start as modal
        # Set window flags at the end of initialization like in PurchaseForm

        self.customers = customers; self.products = products; self.sales_repo = sales_repo; self.db_path = db_path; self.bank_accounts = bank_accounts
        self._payload = None

        # --- header widgets ---
        self.cmb_customer = QComboBox(); self.cmb_customer.setEditable(True)
        # better UX: placeholder & completer
        self.cmb_customer.lineEdit().setPlaceholderText("Type customer name…")
        self.edt_contact = QLineEdit(); self.edt_contact.setPlaceholderText("Contact (phone)")
        self.btn_add_customer = QPushButton("Add Customer"); self.btn_add_customer.setEnabled(False)

        # populate existing customers + completer + quick lookup by lower(name)
        self._customers_by_name = {}
        names = []
        for c in self.customers.list_customers():
            self.cmb_customer.addItem(f"{c.name} (#{c.customer_id})", c.customer_id)
            self._customers_by_name[c.name.lower()] = c
            names.append(c.name)

        # do NOT preselect a customer by default
        self.cmb_customer.setCurrentIndex(-1)
        self.cmb_customer.setEditText("")

        self._completer = QCompleter(names, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.cmb_customer.setCompleter(self._completer)

        # auto-fill contact for existing selection and update payment history
        def _fill_contact_from_sel():
            idx = self.cmb_customer.currentIndex()
            if idx >= 0:
                cid = self.cmb_customer.currentData()
                c = self.customers.get(cid)
                if c:
                    self.edt_contact.setText(c.contact_info or "")
                    # Update payment history for the selected customer
                    self._update_payment_history_for_customer(int(cid))
        self.cmb_customer.currentIndexChanged.connect(lambda _=None: _fill_contact_from_sel())

        # enable/disable "Add Customer" when new name + contact are provided
        def _update_add_customer_state():
            # Check if an existing customer is selected by checking the current data
            current_data = self.cmb_customer.currentData()
            name = (self.cmb_customer.currentText() or "").strip()

            # If currentData gives us a customer ID, this is an existing customer
            is_existing_customer = current_data is not None

            # Only enable if there's a name, it's not an existing customer, and there's contact info
            enable = bool(name) and not is_existing_customer and bool((self.edt_contact.text() or "").strip())
            self.btn_add_customer.setEnabled(enable)

        self.cmb_customer.currentTextChanged.connect(lambda _=None: _update_add_customer_state())
        self.edt_contact.textChanged.connect(lambda _=None: _update_add_customer_state())

        def _add_customer_now():
            name = (self.cmb_customer.currentText() or "").strip()
            contact = (self.edt_contact.text() or "").strip()
            if not name or not contact:
                return
            new_id = self.customers.create(name=name, contact_info=contact, address=None)
            # refresh list & completer
            self.cmb_customer.blockSignals(True)
            self.cmb_customer.clear(); self._customers_by_name.clear()
            names = []
            for c in self.customers.list_customers():
                self.cmb_customer.addItem(f"{c.name} (#{c.customer_id})", c.customer_id)
                self._customers_by_name[c.name.lower()] = c
                names.append(c.name)
            self._completer = QCompleter(names, self); self._completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.cmb_customer.setCompleter(self._completer)
            # select new customer
            idx = self.cmb_customer.findData(new_id)
            if idx >= 0: self.cmb_customer.setCurrentIndex(idx)
            self.cmb_customer.blockSignals(False)
            self.btn_add_customer.setEnabled(False)

        self.btn_add_customer.clicked.connect(_add_customer_now)

        # date / discount / notes
        self.date = QDateEdit(); self.date.setCalendarPopup(True)
        self.date.setDate(QDate.fromString(initial["date"], "yyyy-MM-dd") if initial and initial.get("date") else QDate.fromString(today_str(), "yyyy-MM-dd"))

        self.txt_discount = QLineEdit(); self.txt_discount.setPlaceholderText("0")
        self.txt_notes = QLineEdit()

        # make header fields narrower
        maxw = 360
        for w in (self.cmb_customer, self.edt_contact, self.btn_add_customer, self.date, self.txt_discount, self.txt_notes):
            w.setMaximumWidth(maxw)

        # --- items box & table ---
        box = QGroupBox("Items"); ib = QVBoxLayout(box)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)

        # Set column widths: narrow # column, wider Product column, narrower numerical columns
        header = self.tbl.horizontalHeader()

        # Column 0: "#" - make narrower
        self.tbl.setColumnWidth(0, 40)  # narrow for row numbers

        # Column 1: "Product" - make narrower (decreased by 50% from current)
        self.tbl.setColumnWidth(1, 125)  # narrowed for product selection (50% reduction)

        # Column 2: "Base UoM" - keep default/narrow
        self.tbl.setColumnWidth(2, 80)

        # Column 3: "Alt UoM" - keep default/narrow
        self.tbl.setColumnWidth(3, 80)

        # Column 4: "Avail" - make narrower (numerical column)
        self.tbl.setColumnWidth(4, 70)

        # Column 5: "Qty" - make narrower (numerical column)
        self.tbl.setColumnWidth(5, 70)

        # Column 6: "Unit Price" - make narrower (numerical column)
        self.tbl.setColumnWidth(6, 90)

        # Column 7: "Discount" - make narrower (numerical column)
        self.tbl.setColumnWidth(7, 70)

        # Column 8: "Margin" - make narrower (numerical column)
        self.tbl.setColumnWidth(8, 90)

        # Column 9: "Line Total" - make narrower (numerical column)
        self.tbl.setColumnWidth(9, 90)

        # Column 10: "" (delete button) - keep narrow
        self.tbl.setColumnWidth(10, 40)

        ib.addWidget(self.tbl, 1)
        add = QHBoxLayout(); self.btn_add_row = QPushButton("Add Row"); add.addWidget(self.btn_add_row); add.addStretch(1); ib.addLayout(add)

        # bottom totals (richer summary)
        tot = QHBoxLayout()
        self.lab_sub_raw   = QLabel("0.00")   # sum(qty * unit_price)
        self.lab_line_disc = QLabel("0.00")   # sum(qty * per-unit discount)
        self.lab_order_disc= QLabel("0.00")   # order discount field value
        self.lab_overall   = QLabel("0.00")   # total discount = line + order
        self.lab_total     = QLabel("0.00")   # sub_raw - overall

        # Increase font size and set colors for better visibility
        font = QFont()
        font.setPointSize(10)
        for label in (self.lab_sub_raw, self.lab_line_disc, self.lab_order_disc, self.lab_overall, self.lab_total):
            label.setFont(font)

        # Set different colors for key values
        self.lab_sub_raw.setStyleSheet("color: #006600; font-weight: bold;")  # Green for subtotal
        self.lab_line_disc.setStyleSheet("color: #CC0000; font-weight: bold;")  # Red for discount
        self.lab_order_disc.setStyleSheet("color: #CC0000; font-weight: bold;")  # Red for discount
        self.lab_overall.setStyleSheet("color: #990000; font-weight: bold;")  # Darker red for total discount
        self.lab_total.setStyleSheet("color: #0000AA; font-weight: bold; font-size: 12px;")  # Blue for total

        tot.addStretch(1)
        for cap, w in (("Subtotal:", self.lab_sub_raw),
                       ("Line Discount:", self.lab_line_disc),
                       ("Order Discount:", self.lab_order_disc),
                       ("Total Discount:", self.lab_overall),
                       ("Total:", self.lab_total)):
            cap_label = QLabel(cap)
            cap_label.setStyleSheet("font-weight: bold;")
            tot.addWidget(cap_label); tot.addWidget(w)

        # payment strip (wrapped in a widget so we can hide for quotations)
        self.pay_box = QWidget()
        pay = QHBoxLayout(self.pay_box)
        self.pay_amount = QLineEdit(); self.pay_amount.setPlaceholderText("0")
        self.pay_method = QComboBox(); self.pay_method.addItems(["Cash","Bank Transfer","Cheque","Cross Cheque","Other"])
        self.pay_method.setCurrentText("Bank Transfer")  # Set default to Bank Transfer
        pay.addStretch(1); pay.addWidget(self.pay_amount)
        pay.addWidget(self.pay_method)

        # --- Bank details strip (visible only when Method == "Bank Transfer") ---
        self.bank_box = QWidget()
        bank_layout = QHBoxLayout(self.bank_box)
        bank_layout.setContentsMargins(0, 0, 0, 0)
        self.cmb_bank_account = QComboBox()
        self.cmb_bank_account.setMinimumWidth(280)
        self.edt_instr_no = QLineEdit(); self.edt_instr_no.setPlaceholderText("Transaction/Instrument No.")
        bank_layout.addStretch(1)
        bank_layout.addWidget(QLabel("Bank Account:"))
        bank_layout.addWidget(self.cmb_bank_account)
        bank_layout.addWidget(QLabel("Instrument No.:"))
        bank_layout.addWidget(self.edt_instr_no)

        # Populate bank accounts if repo provided
        try:
            if self.bank_accounts and hasattr(self.bank_accounts, "list_company_bank_accounts"):
                for a in self.bank_accounts.list_company_bank_accounts():
                    # Expecting fields: bank_account_id, bank_name, account_title, account_no
                    label = f"{a['bank_name']} — {a['account_title']} ({a['account_no']})"
                    self.cmb_bank_account.addItem(label, int(a["bank_account_id"]))
        except Exception:
            # Silent: if repo call fails, leave empty; validation will handle later.
            pass

        self.bank_box.setVisible(False)  # hidden by default; toggled by method selection

        # Create main splitter to divide form and payment history panel
        main_splitter = QSplitter(Qt.Horizontal)

        # Left side: main form content
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # layout assembly for left widget
        # Shorten the input boxes for header fields
        maxw = 240  # Reduce from 360 to 240
        for w in (self.cmb_customer, self.edt_contact, self.btn_add_customer, self.date, self.txt_discount, self.txt_notes):
            w.setMaximumWidth(maxw)

        # Create horizontal layout to put payment fields right next to customer info
        customer_payment_layout = QHBoxLayout()

        # Create a form layout for customer info
        customer_info_layout = QFormLayout()
        customer_info_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        customer_info_layout.addRow("Customer*", self.cmb_customer)
        customer_info_layout.addRow("Contact", self.edt_contact)
        customer_info_layout.addRow("", self.btn_add_customer)
        customer_info_layout.addRow("Date*", self.date)
        customer_info_layout.addRow("Order Discount", self.txt_discount)
        customer_info_layout.addRow("Notes", self.txt_notes)

        # Make payment input fields shorter
        self.pay_amount.setMaximumWidth(100)
        self.cmb_bank_account.setMaximumWidth(120)
        self.edt_instr_no.setMaximumWidth(100)
        self.pay_method.setMaximumWidth(100)

        # Initially hide bank-related fields
        self.cmb_bank_account.setVisible(False)
        self.edt_instr_no.setVisible(False)

        # Create a form layout for payment section
        payment_layout = QFormLayout()
        payment_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        payment_layout.addRow("Initial Payment:", self.pay_amount)
        payment_layout.addRow("Method:", self.pay_method)
        payment_layout.addRow("Bank Account:", self.cmb_bank_account)
        payment_layout.addRow("Instrument No.:", self.edt_instr_no)

        # Add both layouts to horizontal container with minimal spacing
        customer_payment_layout.addLayout(customer_info_layout, 3)  # Give more space to customer info
        customer_payment_layout.setSpacing(5)  # Very minimal spacing between sections
        customer_payment_layout.addLayout(payment_layout, 1)  # Payment gets less space

        # For quotations, hide the payment section
        if self.mode == "quotation":
            payment_layout.parentWidget().setVisible(False)

        left_layout.addLayout(customer_payment_layout)

        # Add items box (table), totals and buttons to the left layout
        left_layout.addWidget(box, 1); left_layout.addLayout(tot)

        # Add payment/ bank strips only for 'sale' mode (hidden for quotations)
        left_layout.addWidget(self.pay_box)
        left_layout.addWidget(self.bank_box)
        if self.mode == "quotation":
            self.pay_box.setVisible(False)
            self.bank_box.setVisible(False)

        # Create right side: payment history panel
        self.payment_history_widget = self._create_payment_history_panel()

        # Add to splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(self.payment_history_widget)

        # Set initial sizes (left 75%, right 25%)
        main_splitter.setSizes([825, 275])  # Approximate 75/25 split for 1100px total width

        # Main layout
        lay = QVBoxLayout(self)
        lay.addWidget(main_splitter)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject); lay.addWidget(self.buttons)

        # Set window flags like in PurchaseForm to enable minimize, maximize, and close buttons
        # This should be done after UI construction but before setting size properties
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        # Switch to non-modal to allow proper minimize functionality, like in PurchaseForm
        self.setModal(False)
        self.resize(1100, 700); self.setMinimumSize(860, 560); self.setSizeGripEnabled(True)

        # wiring
        self.tbl.cellChanged.connect(self._cell_changed)
        self.btn_add_row.clicked.connect(self._add_row)
        self.txt_discount.textChanged.connect(self._refresh_totals)
        self.pay_method.currentTextChanged.connect(self._toggle_bank_fields)

        # seed table
        self._rows = [dict(x) for x in (initial.get("items") or [])] if initial else []
        self._rebuild_table()
        if initial:
            i = self.cmb_customer.findData(initial.get("customer_id"))
            if i >= 0: self.cmb_customer.setCurrentIndex(i)
            self.txt_discount.setText(str(initial.get("order_discount", 0) or 0))
            self.txt_notes.setText(initial.get("notes") or "")
            # If initial data includes sale_id, load payment history
            if initial and initial.get("sale_id"):
                self._sale_id = initial.get("sale_id")
                # Load payment history in a delayed way to ensure UI is ready
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._update_payment_history)  # 100ms delay
            else:
                self._sale_id = None
                # If initial data has a customer_id but no sale_id, show customer payment history
                if initial and initial.get("customer_id"):
                    # Load customer payment history in a delayed way to ensure UI is ready
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, lambda: self._update_payment_history_for_customer(int(initial.get("customer_id"))))
                else:
                    # Clear payment history since no specific sale or customer is loaded
                    self._clear_payment_history()
        else:
            self._sale_id = None
            # Clear payment history since no specific sale is loaded
            self._clear_payment_history()

    # --- helpers ---
    def _toggle_bank_fields(self, text: str):
        # Only relevant in sale mode
        if self.mode != "sale":
            self.cmb_bank_account.setVisible(False)
            self.edt_instr_no.setVisible(False)
            return
        # Show bank fields for Bank Transfer, Cheque, Cross Cheque and Other methods
        needs_bank = text in ("Bank Transfer", "Cheque", "Cross Cheque", "Other")
        self.cmb_bank_account.setVisible(needs_bank)
        self.edt_instr_no.setVisible(needs_bank)

    def _warn(self, title: str, message: str, focus_widget=None, row_to_select: int | None = None):
        """Show a friendly message, focus a widget, optionally select a row."""
        info(self, title, message)
        if focus_widget:
            focus_widget.setFocus()
        if row_to_select is not None and 0 <= row_to_select < self.tbl.rowCount():
            try:
                self.tbl.clearSelection()
                self.tbl.selectRow(row_to_select)
            except Exception:
                pass

    def _create_payment_history_panel(self):
        """Create the payment history panel on the right side."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Title
        title_label = QLabel("Payment History")
        title_label.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 5px;")
        layout.addWidget(title_label)

        # Payment summary section
        summary_group = QGroupBox("Payment Summary")
        summary_layout = QFormLayout(summary_group)

        self.payment_total_label = QLabel("0.00")
        self.payment_total_label.setStyleSheet("font-weight: bold;")
        self.payment_paid_label = QLabel("0.00")
        self.payment_paid_label.setStyleSheet("color: green; font-weight: bold;")
        self.payment_advances_label = QLabel("0.00")
        self.payment_advances_label.setStyleSheet("color: green; font-weight: bold;")
        self.payment_advances_label.setToolTip("Customer advances: Total credit deposited by customer that can be applied to future sales")
        self.payment_balance_label = QLabel("0.00")
        self.payment_balance_label.setStyleSheet("color: red; font-weight: bold;")
        self.payment_balance_label.setToolTip("Outstanding balance: Total sales amount minus total payments made by customer (excluding advances)")
        self.payment_status_label = QLabel("Unpaid")
        self.payment_status_label.setStyleSheet("font-weight: bold;")

        summary_layout.addRow("Total:", self.payment_total_label)
        summary_layout.addRow("Paid:", self.payment_paid_label)
        summary_layout.addRow("Advances:", self.payment_advances_label)
        summary_layout.addRow("Balance:", self.payment_balance_label)
        summary_layout.addRow("Status:", self.payment_status_label)

        layout.addWidget(summary_group)

        # Payments table
        payments_table_label = QLabel("Payment Transactions")
        payments_table_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(payments_table_label)

        self.payments_table = QTableWidget()
        self.payments_table.setColumnCount(4)
        self.payments_table.setHorizontalHeaderLabels(["Date", "Amount", "Method", "Status"])
        self.payments_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.payments_table.verticalHeader().setVisible(False)
        self.payments_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.payments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Make read-only

        layout.addWidget(self.payments_table, 1)  # 1 = stretch factor

        # Add refresh button
        refresh_button = QPushButton("Refresh Payments")
        refresh_button.clicked.connect(self._update_payment_history)
        layout.addWidget(refresh_button)

        return panel

    def _update_payment_history(self):
        """Update the payment history panel with current sale's payment data."""
        if not hasattr(self, '_sale_id') or not self._sale_id:
            # If no specific sale is loaded, show customer payment history if a customer is selected
            current_cid = self.cmb_customer.currentData()
            if current_cid:
                self._update_payment_history_for_customer(int(current_cid))
            else:
                self._clear_payment_history()
            return

        try:
            # Use the provided sales repo and db_path to get payment info
            if not self.sales_repo or not self.db_path:
                self._clear_payment_history()
                return

            from ...database.repositories.sale_payments_repo import SalePaymentsRepo
            from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo
            payment_repo = SalePaymentsRepo(self.db_path)
            advances_repo = CustomerAdvancesRepo(self.db_path)

            # Get sale details using the get_header method
            sale = self.sales_repo.get_header(self._sale_id)
            if not sale:
                self._clear_payment_history()
                return

            # Get customer ID to fetch advances
            customer_id = int(sale['customer_id'])
            advances = advances_repo.list_ledger(customer_id)

            # Calculate net advances (deposits minus applications)
            net_advances = sum(
                float(adv['amount']) if adv['amount'] is not None else 0.0
                for adv in advances
            )

            # Available advances (only positive net balance)
            available_advances = max(0.0, net_advances)

            # Update summary
            total_amount = float(sale['total_amount']) if sale['total_amount'] is not None else 0.0
            paid_amount = float(sale['paid_amount']) if sale['paid_amount'] is not None else 0.0
            advance_applied = float(sale['advance_payment_applied']) if sale['advance_payment_applied'] is not None else 0.0
            balance = total_amount - paid_amount - advance_applied
            payment_status = str(sale['payment_status']) if sale['payment_status'] is not None else 'Unknown'

            self.payment_total_label.setText(fmt_money(total_amount))
            self.payment_paid_label.setText(fmt_money(paid_amount))
            self.payment_advances_label.setText(fmt_money(available_advances))  # Customer advances
            self.payment_balance_label.setText(fmt_money(balance))
            self.payment_status_label.setText(payment_status)

            # Get payment transactions for this sale
            payments = payment_repo.list_by_sale(self._sale_id)

            # Also get any advances applied to this specific sale
            sale_advances = []
            for adv in advances:
                if (adv['source_type'] == 'applied_to_sale' and
                    adv['source_id'] == self._sale_id and
                    float(adv['amount']) < 0):  # Applications are negative
                    sale_advances.append(adv)

            # Combine payments and applied advances for display
            all_transactions = []

            # Add regular payments
            for payment in payments:
                all_transactions.append({
                    'date': str(payment['date']) if payment['date'] is not None else '',
                    'amount': float(payment['amount']) if payment['amount'] is not None else 0.0,
                    'method': str(payment['method']) if payment['method'] is not None else 'Payment',
                    'status': str(payment['clearing_state']) if payment['clearing_state'] is not None else 'N/A',
                    'type': 'payment'
                })

            # Add advances applied to this sale
            for advance in sale_advances:
                all_transactions.append({
                    'date': str(advance['tx_date']) if advance['tx_date'] is not None else '',
                    'amount': float(advance['amount']) if advance['amount'] is not None else 0.0,
                    'method': f"Advance Applied ({advance['source_type']})",
                    'status': 'Applied',
                    'type': 'advance_applied'
                })

            # Sort all transactions by date
            all_transactions.sort(key=lambda x: x['date'])

            # Update payments table with combined transactions
            self.payments_table.setRowCount(len(all_transactions))

            for row_idx, transaction in enumerate(all_transactions):
                # Date
                date_item = QTableWidgetItem(transaction['date'])
                date_item.setTextAlignment(Qt.AlignCenter)
                self.payments_table.setItem(row_idx, 0, date_item)

                # Amount
                amount = transaction['amount']
                amount_item = QTableWidgetItem(fmt_money(amount))
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Color code based on type and amount
                if transaction['type'] == 'advance_applied':
                    amount_item.setForeground(QColor("blue"))  # Applied advances in blue
                elif transaction['type'] == 'payment':
                    if amount < 0:
                        amount_item.setForeground(QColor("red"))  # Refunds in red
                    else:
                        amount_item.setForeground(QColor("green"))  # Payments in green
                else:
                    amount_item.setForeground(QColor("green"))  # Default to green
                self.payments_table.setItem(row_idx, 1, amount_item)

                # Method
                method_item = QTableWidgetItem(transaction['method'])
                self.payments_table.setItem(row_idx, 2, method_item)

                # Status
                status_item = QTableWidgetItem(transaction['status'])
                # Color code based on status
                if transaction['status'] == 'cleared':
                    status_item.setForeground(QColor("green"))
                elif transaction['status'] in ['Applied', 'Available', 'pending']:
                    status_item.setForeground(QColor("orange"))
                elif transaction['status'] == 'bounced':
                    status_item.setForeground(QColor("red"))
                self.payments_table.setItem(row_idx, 3, status_item)

        except Exception as e:
            # If there's an error, clear the payment history
            print(f"Error updating payment history: {e}")
            self._clear_payment_history()

    def _update_payment_history_for_customer(self, customer_id: int):
        """Update the payment history panel with customer's payment data."""
        if not self.db_path:
            self._clear_payment_history()
            return

        try:
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo
            from ...database.repositories.customers_repo import CustomersRepo
            payment_repo = SalePaymentsRepo(self.db_path)

            # Get all payments for this customer across all their sales
            payments = payment_repo.list_by_customer(customer_id)

            # Calculate summary information for the customer
            total_paid = sum(float(row['amount']) if row['amount'] is not None else 0.0 for row in payments if float(row['amount']) > 0)
            refund_amount = abs(sum(float(row['amount']) if row['amount'] is not None else 0.0 for row in payments if float(row['amount']) < 0))

            # Also get customer's total outstanding balance across all sales
            # For this, we need to get all sales for this customer
            all_sales = self.sales_repo.list_by_customer(customer_id, 'sale')

            # Calculate total outstanding amount for all sales by the customer
            # This represents the total amount still owed across all sales for this customer
            total_outstanding = 0
            for sale in all_sales:
                total_amt = float(sale['total_amount']) if sale['total_amount'] is not None else 0.0
                paid_amt = float(sale['paid_amount']) if sale['paid_amount'] is not None else 0.0
                advance_applied = float(sale['advance_payment_applied']) if sale['advance_payment_applied'] is not None else 0.0
                outstanding = total_amt - paid_amt - advance_applied
                total_outstanding += max(0, outstanding)  # Only positive outstanding amounts

            # Calculate customer's total sales amount across all their sales
            total_sales_amount = sum(float(sale['total_amount']) if sale['total_amount'] is not None else 0.0
                                   for sale in all_sales)

            # Calculate total amount paid by the customer (positive payments only)
            total_paid_by_customer = sum(float(payment['amount']) if payment['amount'] is not None else 0.0
                                       for payment in payments if float(payment['amount']) > 0)

            # Calculate total refunds given to customer (negative values)
            total_refunds = abs(sum(float(payment['amount']) if payment['amount'] is not None else 0.0
                                  for payment in payments if float(payment['amount']) < 0))

            # Calculate customer advances (separate from regular payments)
            from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo
            advances_repo = CustomerAdvancesRepo(self.db_path)
            advances = advances_repo.list_ledger(customer_id)

            # Calculate net advances (deposits minus applications)
            net_advances = sum(
                float(adv['amount']) if adv['amount'] is not None else 0.0
                for adv in advances
            )

            # Available advances (only positive net balance)
            available_advances = max(0.0, net_advances)

            # The total_outstanding was already calculated from individual sales
            # Now determine overall customer payment status based on the calculated outstanding amount
            if total_outstanding <= 0:
                overall_status = "Paid"
            elif total_outstanding < total_sales_amount * 0.5:  # If less than half is outstanding
                overall_status = "Partially Paid"
            else:
                overall_status = "Overdue"

            # Update summary
            self.payment_total_label.setText(fmt_money(total_sales_amount))
            self.payment_paid_label.setText(fmt_money(total_paid_by_customer))
            self.payment_advances_label.setText(fmt_money(available_advances))
            self.payment_balance_label.setText(fmt_money(total_outstanding))
            self.payment_status_label.setText(overall_status)

            # Combine payments and advances for display in chronological order
            all_transactions = []

            # Add regular payments
            for payment in payments:
                all_transactions.append({
                    'date': str(payment['date']) if payment['date'] is not None else '',
                    'amount': float(payment['amount']) if payment['amount'] is not None else 0.0,
                    'method': str(payment['method']) if payment['method'] is not None else 'Payment',
                    'status': str(payment['clearing_state']) if payment['clearing_state'] is not None else 'N/A',
                    'type': 'payment'
                })

            # Add advances
            for advance in advances:
                # Only show deposits/credits, not applications to sales (which have negative amounts)
                if float(advance['amount']) > 0:  # Positive amounts are deposits/credits
                    all_transactions.append({
                        'date': str(advance['tx_date']) if advance['tx_date'] is not None else '',
                        'amount': float(advance['amount']) if advance['amount'] is not None else 0.0,
                        'method': f"Advance ({advance['source_type']})",
                        'status': 'Available',  # Advances are available for application
                        'type': 'advance'
                    })

            # Sort all transactions by date
            all_transactions.sort(key=lambda x: x['date'])

            # Update payments table with combined transactions
            self.payments_table.setRowCount(len(all_transactions))

            for row_idx, transaction in enumerate(all_transactions):
                # Date
                date_item = QTableWidgetItem(transaction['date'])
                date_item.setTextAlignment(Qt.AlignCenter)
                self.payments_table.setItem(row_idx, 0, date_item)

                # Amount
                amount = transaction['amount']
                amount_item = QTableWidgetItem(fmt_money(amount))
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Color code based on type and amount
                if transaction['type'] == 'advance':
                    amount_item.setForeground(QColor("green"))  # Advances in green
                elif amount < 0:
                    amount_item.setForeground(QColor("red"))  # Refunds in red
                else:
                    amount_item.setForeground(QColor("green"))  # Payments in green
                self.payments_table.setItem(row_idx, 1, amount_item)

                # Method
                method_item = QTableWidgetItem(transaction['method'])
                self.payments_table.setItem(row_idx, 2, method_item)

                # Status
                status_item = QTableWidgetItem(transaction['status'])
                # Color code based on status
                if transaction['status'] == 'cleared':
                    status_item.setForeground(QColor("green"))
                elif transaction['status'] in ['Available', 'pending']:
                    status_item.setForeground(QColor("orange"))
                elif transaction['status'] == 'bounced':
                    status_item.setForeground(QColor("red"))
                else:
                    status_item.setForeground(QColor("gray"))
                self.payments_table.setItem(row_idx, 3, status_item)

        except Exception as e:
            # If there's an error, clear the payment history
            print(f"Error updating customer payment history: {e}")
            self._clear_payment_history()

    def _clear_payment_history(self):
        """Clear all payment history data."""
        self.payment_total_label.setText("0.00")
        self.payment_paid_label.setText("0.00")
        self.payment_advances_label.setText("0.00")  # Clear advances label
        self.payment_balance_label.setText("0.00")
        self.payment_status_label.setText("Unpaid")
        self.payments_table.setRowCount(0)

    def _all_products(self):
        return self.products.list_products()

    def _base_uom_id(self, product_id: int) -> int:
        base = self.products.get_base_uom(product_id)
        if base: return int(base["uom_id"])
        u = self.products.list_uoms()
        return int(u[0]["uom_id"]) if u else 1

    def _add_row(self, pre: dict | None = None):
        self.tbl.blockSignals(True)
        r = self.tbl.rowCount(); self.tbl.insertRow(r)

        # row number
        num = QTableWidgetItem(str(r+1))
        num.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 0, num)

        # product combo (already imported at module level)
        cmb = QComboBox()
        for p in self._all_products():
            cmb.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.tbl.setCellWidget(r, 1, cmb)

        # Base UoM (read-only label cell)
        base_cell = QTableWidgetItem("-")
        base_cell.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 2, base_cell)

        # Alt UoM (combo; disabled when no alternates)
        alt = QComboBox(); alt.setEnabled(False)
        self.tbl.setCellWidget(r, 3, alt)

        # Avail (read-only)
        avail = QTableWidgetItem("0")
        avail.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        avail.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 4, avail)

        # Qty (editable)
        qty = QTableWidgetItem("0"); qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 5, qty)

        # Unit Price (read-only; per selected UoM)
        unit = QTableWidgetItem("0.00")
        unit.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        unit.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 6, unit)

        # Discount (per-unit; editable)
        disc = QTableWidgetItem("0"); disc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 7, disc)

        # Margin (total for the line; read-only)
        marg = QTableWidgetItem("0.00")
        marg.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        marg.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 8, marg)

        # Line Total (read-only)
        ltot = QTableWidgetItem("0.00")
        ltot.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        ltot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 9, ltot)

        # delete button
        btn = QPushButton("✕")
        def kill():
            self.tbl.removeRow(r); self._reindex(); self._refresh_totals()
        btn.clicked.connect(kill); self.tbl.setCellWidget(r, 10, btn)

        # when product changes → base uom name, alt list, prices, avail
        def on_prod():
            pid = cmb.currentData()
            if not pid:
                base_cell.setText("-"); alt.clear(); alt.setEnabled(False)
                return
            # base + alternates (requires ProductsRepo.list_product_uoms)
            uoms = self.products.list_product_uoms(int(pid))
            base = next((u for u in uoms if u["is_base"]), None)
            alts = [u for u in uoms if not u["is_base"]]
            base_cell.setText(base["unit_name"] if base else "-")
            # store base uom id in row-number col UserRole; base factor in Base UoM col UserRole
            self.tbl.item(r, 0).setData(Qt.UserRole, int(base["uom_id"]) if base else None)
            self.tbl.item(r, 2).setData(Qt.UserRole, float(base["factor_to_base"]) if base else 1.0)

            # build alt combo: first item = “— base —”
            alt.blockSignals(True); alt.clear()
            alt.addItem("— base —", None)
            for u in alts:
                alt.addItem(u["unit_name"], (int(u["uom_id"]), float(u["factor_to_base"])))
            alt.setEnabled(bool(alts))
            alt.blockSignals(False)

            # prices (BASE per-unit) and stock (BASE)
            pr = self.products.latest_prices_base(int(pid))
            cost_base = float(pr["cost"]); sale_base = float(pr["sale"])
            unit.setData(Qt.UserRole, cost_base)  # store base cost for margin math
            unit.setText(fmt_money(sale_base))    # display base price by default

            # availability in BASE initially; alt handler will convert
            avail_base = self.products.on_hand_base(int(pid))
            avail.setText(f"{avail_base:g}")

            self._recalc_row(r); self._refresh_totals()

        def on_alt_changed():
            # when alt UoM changes → convert price & avail for display
            data = alt.currentData()
            pid = cmb.currentData()
            if not pid:
                return
            pr = self.products.latest_prices_base(int(pid))
            sale_base = float(pr["sale"])
            cost_base = float(unit.data(Qt.UserRole) or 0.0)
            avail_base = self.products.on_hand_base(int(pid))

            if data is None:
                # base uom
                unit.setText(fmt_money(sale_base))
                avail.setText(f"{avail_base:g}")
            else:
                _, f = data
                unit.setText(fmt_money(sale_base * f))
                # availability in selected UoM = base / f
                avail.setText(f"{(avail_base / f):g}")
            self._recalc_row(r); self._refresh_totals()

        cmb.currentIndexChanged.connect(on_prod)
        alt.currentIndexChanged.connect(on_alt_changed)
        on_prod()

        # prefill for edit
        if pre:
            i = cmb.findData(pre.get("product_id"))
            if i >= 0: cmb.setCurrentIndex(i)
            # Alt UoM selection if provided (after on_prod() built alt list)
            alt_cb = self.tbl.cellWidget(r, 3)
            if pre.get("uom_id") and self.tbl.item(r,0).data(Qt.UserRole) != pre["uom_id"] and isinstance(alt_cb, QComboBox):
                for k in range(alt_cb.count()):
                    data = alt_cb.itemData(k)
                    if isinstance(data, tuple) and data[0] == pre["uom_id"]:
                        alt_cb.setCurrentIndex(k); break
            # qty / price / discount
            self.tbl.item(r,5).setText(str(pre.get("quantity", 0)))
            self.tbl.item(r,6).setText(fmt_money(pre.get("unit_price", 0)))
            self.tbl.item(r,7).setText(str(pre.get("item_discount", 0)))

        self.tbl.blockSignals(False)
        self._recalc_row(r)

    def _reindex(self):
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r,0)
            if it: it.setText(str(r+1))

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

    def _cell_changed(self, row:int, col:int):
        # Only Qty (5) and Discount (7) are editable; respond to those changes
        if col not in (5, 7):
            return
        for c in (4,5,6,7,9):
            if self.tbl.item(row,c) is None: return
        self._recalc_row(row); self._refresh_totals()

    # qty-aware margin; per-unit margin shown in tooltip; oversell in selected UoM
    def _recalc_row(self, r:int):
        def num(c):
            it = self.tbl.item(r,c)
            try: return float(it.text().replace(",","")) if it and it.text() else 0.0
            except Exception: return 0.0

        # selected UoM factor: None = base (factor 1)
        alt = self.tbl.cellWidget(r, 3)
        data = alt.currentData() if alt else None
        factor = float(data[1]) if data else 1.0

        avail = num(4)             # already shown in selected UoM
        qty   = num(5)
        unit  = num(6)             # per selected UoM
        disc  = num(7)             # per selected UoM
        # base cost (per base unit) was stored in UserRole of Unit Price; convert to selected UoM
        cost_base = float(self.tbl.item(r,6).data(Qt.UserRole) or 0.0)
        cost_uom  = cost_base * factor

        over = qty > avail and avail >= 0
        it_qty = self.tbl.item(r,5)
        if it_qty: it_qty.setBackground(Qt.red if over else Qt.white)

        # total margin (qty-aware). Per-unit margin in tooltip.
        m_unit = (unit - disc) - cost_uom
        m_tot  = qty * m_unit
        it_m = self.tbl.item(r,8)
        if it_m:
            it_m.setText(fmt_money(m_tot))
            it_m.setToolTip(f"Per-unit margin: {fmt_money(m_unit)}")
            it_m.setBackground(Qt.red if m_tot < 0 else Qt.white)

        # line total (before order discount)
        lt = max(0.0, qty * (unit - disc))
        it_lt = self.tbl.item(r,9)
        if it_lt: it_lt.setText(fmt_money(lt))

    # ---- totals helpers (raw subtotal & line discount) ----
    def _calc_raw_subtotal(self) -> float:
        s = 0.0
        for r in range(self.tbl.rowCount()):
            try:
                qty  = float(self.tbl.item(r,5).text() or 0)
                unit = float(self.tbl.item(r,6).text().replace(",","") or 0)
                s += qty * unit
            except Exception:
                pass
        return s

    def _calc_line_discount(self) -> float:
        s = 0.0
        for r in range(self.tbl.rowCount()):
            try:
                qty  = float(self.tbl.item(r,5).text() or 0)
                disc = float(self.tbl.item(r,7).text() or 0)
                s += qty * disc
            except Exception:
                pass
        return s

    def _refresh_totals(self):
        sub_raw = self._calc_raw_subtotal()
        line_disc = self._calc_line_discount()
        try: od = float(self.txt_discount.text() or 0)
        except Exception: od = 0.0
        overall = line_disc + od
        total = max(0.0, sub_raw - overall)
        self.lab_sub_raw.setText(fmt_money(sub_raw))
        self.lab_line_disc.setText(fmt_money(line_disc))
        self.lab_order_disc.setText(fmt_money(od))
        self.lab_overall.setText(fmt_money(overall))
        self.lab_total.setText(fmt_money(total))

    # payload with visible validation and row highlighting
    def get_payload(self) -> dict | None:
        # customer must be chosen or added
        cid = self.cmb_customer.currentData()
        if not cid:
            self._warn("Missing Customer", "Please select an existing customer or add a new one.", self.cmb_customer)
            return None

        errors = []
        items = []

        # row-by-row validation with specific messages
        for r in range(self.tbl.rowCount()):
            try:
                # widgets
                from PySide6.QtWidgets import QComboBox  # lazy import retained
                cmb: QComboBox = self.tbl.cellWidget(r, 1)
                alt: QComboBox = self.tbl.cellWidget(r, 3)

                # product
                if not cmb or cmb.currentData() is None:
                    errors.append(f"Row {r+1}: Select a product.")
                    continue
                pid = int(cmb.currentData())

                # numbers in selected UoM (as displayed)
                def num(c):
                    it = self.tbl.item(r, c)
                    return float(it.text().replace(",", "")) if it and it.text() else 0.0

                avail = num(4)
                qty   = num(5)
                unit  = num(6)
                disc  = num(7)

                if qty <= 0:
                    errors.append(f"Row {r+1}: Quantity must be greater than 0.")
                    continue
                if unit <= 0:
                    errors.append(f"Row {r+1}: Unit Price must be greater than 0.")
                    continue
                if disc < 0:
                    errors.append(f"Row {r+1}: Discount cannot be negative.")
                    continue
                # oversell guard in the selected UoM
                if qty > avail:
                    errors.append(f"Row {r+1}: Quantity ({qty:g}) exceeds available ({avail:g}).")
                    continue

                # uom_id: base vs alt
                base_uom_id = int(self.tbl.item(r, 0).data(Qt.UserRole) or 0)
                uom_id = base_uom_id
                if alt and isinstance(alt.currentData(), tuple):
                    uom_id = int(alt.currentData()[0])

                items.append({
                    "product_id": pid,
                    "uom_id": int(uom_id),
                    "quantity": qty,
                    "unit_price": unit,
                    "item_discount": disc,
                })
            except Exception:
                errors.append(f"Row {r+1}: Invalid or incomplete data.")
                continue

        if errors and not items:
            # If nothing valid, show the first few issues and select the first bad row
            self._warn("Please fix these issues",
                       "\n".join(errors[:6] + (["…"] if len(errors) > 6 else [])),
                       focus_widget=self.tbl, row_to_select=0)
            return None

        if not items:
            self._warn("No Items", "Add at least one valid item to proceed.", focus_widget=self.btn_add_row)
            return None

        # order discount parsing + totals
        try:
            od = float(self.txt_discount.text() or 0)
        except Exception:
            od = 0.0

        # reuse your totals helpers
        sub_raw = self._calc_raw_subtotal()
        line_disc = self._calc_line_discount()
        total = max(0.0, sub_raw - (line_disc + od))

        payload = {
            "customer_id": int(cid),
            "date": self.date.date().toString("yyyy-MM-dd"),
            "order_discount": od,
            "notes": (self.txt_notes.text().strip() or None),
            "items": items,
            "total_amount": total,
            "line_discount_total": line_disc,
            "subtotal_raw": sub_raw,
        }

        # --- Initial payment only in SALE mode ---
        if self.mode == "sale":
            init = float(self.pay_amount.text() or 0)
            method = self.pay_method.currentText()
            payload["initial_payment"] = init
            payload["initial_method"] = method

            # Payment methods that require bank account and instrument details
            if init > 0 and method in ("Bank Transfer", "Cheque", "Cross Cheque", "Other"):
                bank_id = self.cmb_bank_account.currentData()
                instr_no = (self.edt_instr_no.text() or "").strip()

                # For Bank Transfer, Cheque and Cross Cheque, bank account and reference are required
                if method in ("Bank Transfer", "Cheque", "Cross Cheque"):
                    if bank_id is None:
                        if method == "Bank Transfer":
                            self._warn("Bank Required", "Select a company bank account for Bank Transfer.", self.cmb_bank_account)
                        elif method == "Cheque":
                            self._warn("Bank Required", "Select a company bank account for Cheque.", self.cmb_bank_account)
                        else:  # Cross Cheque
                            self._warn("Bank Required", "Select a company bank account for Cross Cheque.", self.cmb_bank_account)
                        return None
                    if not instr_no:
                        if method == "Bank Transfer":
                            self._warn("Reference Required", "Enter the transaction/instrument number for Bank Transfer.", self.edt_instr_no)
                        elif method == "Cheque":
                            self._warn("Reference Required", "Enter the cheque number for Cheque payment.", self.edt_instr_no)
                        else:  # Cross Cheque
                            self._warn("Reference Required", "Enter the cheque number for Cross Cheque payment.", self.edt_instr_no)
                        return None

                # For Other method, only store values if they exist (optional fields)
                # For Bank Transfer, Cheque and Cross Cheque, these will be required values
                if bank_id is not None:
                    payload["initial_bank_account_id"] = int(bank_id)
                if instr_no:
                    payload["initial_instrument_no"] = instr_no

                # Set appropriate instrument type based on the method
                if method == "Bank Transfer":
                    payload["initial_instrument_type"] = "online"
                elif method in ("Cheque", "Cross Cheque"):
                    payload["initial_instrument_type"] = "cross_cheque"  # Both Cheque and Cross Cheque use cross_cheque
                else:  # Other method
                    payload["initial_instrument_type"] = "other"

        return payload

    def accept(self):
        p = self.get_payload()
        if p is None:
            return
        self._payload = p

        # If this is an edit operation, update the payment history after saving
        if hasattr(self, '_sale_id') and self._sale_id:
            # Update payment history in a delayed way after successful save
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._update_payment_history)  # 100ms delay

        super().accept()

    def payload(self):
        return self._payload
