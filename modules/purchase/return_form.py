from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QDialogButtonBox, QLineEdit, QFormLayout, QLabel, QComboBox, QDateEdit,
    QGridLayout, QRadioButton
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QBrush, QColor
from ...utils.helpers import today_str, fmt_money

# Constants
EPSILON = 1e-9
CLEARING_STATE_POSTED = "posted"


def _first_key(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class PurchaseReturnForm(QDialog):
    # Column indices
    COL_ITEM_ID = 0
    COL_PRODUCT = 1
    COL_UOM = 2
    COL_QTY_RETURN = 3
    COL_QTY_PURCHASED = 4
    COL_RETURNED_SO_FAR = 5
    COL_MAX_RETURNABLE = 6
    COL_LINE_VALUE = 7
    COL_NOTES = 8

    # Reordered headers: put Qty Return before any other 'qty/return' headers
    COLS = [
        "ItemID", "Product", "UoM",
        "Qty Return",
        "Qty Purchased",
        "Returned so far",
        "Max returnable",
        "Line Value",
        "Notes",
    ]

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
    TEMP_BANK_KEY = "TEMP_BANK"

    def __init__(
        self,
        parent=None,
        items: list[dict] | None = None,
        *,
        vendor_id: int | None = None,
        vendors=None,  # Changed: now using vendors object that contains connection
        vendor_bank_accounts_repo=None,
        company_bank_accounts_repo=None,
        purchases_repo=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Purchase Return")
        self.setModal(True)

        self.vendor_id = int(vendor_id) if vendor_id is not None else None
        self.vendors = vendors  # Changed: using vendors object for connection
        self.vba_repo = vendor_bank_accounts_repo
        self.cba_repo = company_bank_accounts_repo
        self.purchases_repo = purchases_repo
        
        # Create reverse mapping from display values to keys for payment methods
        self._method_display_to_key = {v: k for k, v in self.PAYMENT_METHODS.items()}

        # Header
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))
        self.notes = QLineEdit()
        f = QFormLayout()
        f.addRow("Date", self.date)
        f.addRow("Notes", self.notes)
        
        # Add purchase summary info
        self.purchase_id = None  # Initialize here but will be set by controller
        self.lbl_remaining = QLabel("Calculating remaining...")
        self.lbl_return_value = QLabel("Return value: 0.00")
        summary_layout = QHBoxLayout()
        summary_layout.addWidget(self.lbl_remaining)
        summary_layout.addWidget(self.lbl_return_value)
        f.addRow("Purchase Summary:", summary_layout)
        
        # Timer for debouncing expensive operations like _update_remaining_amount
        self._remaining_amount_timer = QTimer(self)
        self._remaining_amount_timer.setSingleShot(True)
        self._remaining_amount_timer.timeout.connect(self._update_remaining_amount)

        # Table
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setColumnWidth(self.COL_ITEM_ID, 70)
        self.tbl.setColumnWidth(self.COL_PRODUCT, 220)
        self.tbl.setColumnWidth(self.COL_UOM, 80)
        self.tbl.setColumnWidth(self.COL_QTY_RETURN, 110)
        self.tbl.setColumnWidth(self.COL_QTY_PURCHASED, 110)
        self.tbl.setColumnWidth(self.COL_RETURNED_SO_FAR, 120)
        self.tbl.setColumnWidth(self.COL_MAX_RETURNABLE, 120)
        self.tbl.setColumnWidth(self.COL_LINE_VALUE, 120)
        self.tbl.setColumnWidth(self.COL_NOTES, 160)

        # Totals + return mode
        tot_bar = QHBoxLayout()

        # Return scope selector
        self.rb_return_selected = QRadioButton("Return selected quantities")
        self.rb_return_whole = QRadioButton("Return whole order")
        self.rb_return_selected.setChecked(True)

        tot_bar.addWidget(QLabel("Return:"))
        tot_bar.addWidget(self.rb_return_selected)
        tot_bar.addWidget(self.rb_return_whole)

        tot_bar.addStretch(1)
        self.lab_qty_total = QLabel("0")
        self.lab_val_total = QLabel("Total Return Value: 0.00")
        tot_bar.addWidget(QLabel("Total Qty:"))
        tot_bar.addWidget(self.lab_qty_total)
        tot_bar.addSpacing(20)
        tot_bar.addWidget(self.lab_val_total)

        # Settlement
        settle_box = QGroupBox("Settlement")
        settle_layout = QVBoxLayout(settle_box)

        # Settlement mode selector
        mode_row = QHBoxLayout()
        self.rb_credit_note = QRadioButton("Credit Note")
        self.rb_refund_now = QRadioButton("Refund Now")
        self.rb_credit_note.setChecked(True)  # Default to Credit Note
        mode_row.addWidget(QLabel("Settlement Mode:"))
        mode_row.addWidget(self.rb_credit_note)
        mode_row.addWidget(self.rb_refund_now)
        mode_row.addStretch(1)
        settle_layout.addLayout(mode_row)

        # Refund details panel - similar to payment form structure
        self.ref_panel = QGroupBox("Refund Details")
        ref_layout = QGridLayout(self.ref_panel)
        ref_layout.setHorizontalSpacing(12)
        ref_layout.setVerticalSpacing(8)

        # Refund method dropdown
        self.cmb_method = QComboBox()
        self.cmb_method.addItems(list(self.PAYMENT_METHODS.values()))

        # Bank account fields
        self.cmb_company_acct = QComboBox()
        self.cmb_company_acct.setEditable(True)
        self.cmb_vendor_acct = QComboBox()
        self.cmb_vendor_acct.setEditable(True)

        # Instrument fields
        self.txt_instr_no = QLineEdit()
        self.txt_instr_no.setPlaceholderText("Instrument / Cheque / Slip No")
        self.date_instr = QDateEdit()
        self.date_instr.setCalendarPopup(True)
        self.date_instr.setDate(self.date.date())

        # Temporary external bank account fields
        self.temp_bank_name = QLineEdit()
        self.temp_bank_name.setPlaceholderText("Bank Name")
        self.temp_bank_number = QLineEdit()
        self.temp_bank_number.setPlaceholderText("Account Number")

        self._clearing_state_fixed = CLEARING_STATE_POSTED

        # Helper functions
        def create_required_label(text):
            """Helper function to create a label with a red asterisk for required fields"""
            label = QLabel()
            label.setText(text + "*")
            label.setStyleSheet("color: red; font-weight: bold;")
            return label

        def add_refund_field(row, col, text, widget, required=False):
            """Helper function to add refund fields with optional required indicators"""
            c = col * 2
            if required:
                label = create_required_label(text)
                ref_layout.addWidget(label, row, c)
            else:
                label = QLabel(text)
                ref_layout.addWidget(label, row, c)
            ref_layout.addWidget(widget, row, c + 1)
            return label  # Return the label for potential modification later

        self._refund_labels = {}
        
        # Add refund fields in a grid layout
        add_refund_field(0, 0, "Method", self.cmb_method, required=True)
        self._refund_labels['company_acct'] = add_refund_field(0, 1, "Company Account", self.cmb_company_acct, required=False)
        self._refund_labels['vendor_acct'] = add_refund_field(1, 0, "Vendor Account", self.cmb_vendor_acct, required=False)
        self._refund_labels['instr_no'] = add_refund_field(1, 1, "Instrument No", self.txt_instr_no, required=False)
        
        # Add temporary bank fields to the layout (now at row 3)
        ref_layout.addWidget(QLabel("Temp Bank Name"), 3, 0)
        ref_layout.addWidget(self.temp_bank_name, 3, 1)
        ref_layout.addWidget(QLabel("Temp Bank Number"), 3, 2)
        ref_layout.addWidget(self.temp_bank_number, 3, 3)
        
        # Store temporary bank labels separately
        self._refund_labels['temp_bank_name'] = ref_layout.itemAtPosition(3, 0).widget()
        self._refund_labels['temp_bank_number'] = ref_layout.itemAtPosition(3, 2).widget()
        
        # Keep temporary bank fields visible but disabled by default
        self.temp_bank_name.setVisible(True)
        self.temp_bank_number.setVisible(True)
        self.temp_bank_name.setEnabled(False)
        self.temp_bank_number.setEnabled(False)

        # Add the refund panel to the main layout
        settle_layout.addWidget(self.ref_panel)
        self.ref_panel.setVisible(False)

        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        # Layout
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(self.tbl, 1)
        lay.addLayout(tot_bar)
        lay.addWidget(settle_box)
        lay.addWidget(self.buttons)

        self._payload = None
        self._qty_snapshot = []  # for polling
        if items:
            self.set_items(items)

        # signals (user editing)
        self.tbl.cellChanged.connect(self._cell_changed)
        self.tbl.itemChanged.connect(self._item_changed)
        self.rb_return_whole.toggled.connect(self._toggle_return_scope)
        self.rb_credit_note.toggled.connect(self._toggle_mode)
        self.cmb_method.currentIndexChanged.connect(self._refresh_refund_visibility)
        self.date.dateChanged.connect(self._default_instrument_date)
        self.txt_instr_no.textChanged.connect(self._validate)
        self.cmb_company_acct.currentIndexChanged.connect(self._validate)
        self.cmb_vendor_acct.currentIndexChanged.connect(self._on_vendor_bank_account_changed)
        self.date_instr.dateChanged.connect(self._validate)
        
        # Load bank accounts
        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_refund_visibility()

        # polling (programmatic setItem on Qty cell)
        self._poll = QTimer(self)
        self._poll.setInterval(15)
        self._poll.timeout.connect(self._poll_scan_qty)
        self._poll.start()

        self._validate()
        # Set up return value tracking
        self._refresh_return_value()
        
        self.resize(1200, 680)
        self.setSizeGripEnabled(True)

    # ---------- account loaders ----------
    def _load_company_accounts_from_db(self):
        """Shared method to load company bank accounts from database"""
        self.cmb_company_acct.clear()
        try:
            # Try to get the database connection
            conn = getattr(self.vendors, 'conn', None) if self.vendors else None
            
            if conn:
                rows = conn.execute(
                    "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
                ).fetchall()
                for r in rows:
                    self.cmb_company_acct.addItem(r["label"], int(r["account_id"]))
            else:
                # Fallback to repo if connection not available
                rows = []
                repo = self.cba_repo
                try_methods = ("list_active", "list_all", "list", "list_bank_accounts")
                if repo:
                    for m in try_methods:
                        if hasattr(repo, m):
                            rows = getattr(repo, m)()
                            break
                if not rows:
                    rows = [
                        {"label": "Meezan — Current", "account_id": 1},
                        {"label": "HBL — Current", "account_id": 2},
                    ]
                for r in rows or []:
                    label = _first_key(r, "label", "bank_name", default="Account")
                    aid = _first_key(r, "account_id", "bank_account_id")
                    self.cmb_company_acct.addItem(str(label), aid)
        except Exception as e:
            import logging
            logging.error(f"Error loading company bank accounts: {e}")
            # Fallback to default accounts if there's an error
            self.cmb_company_acct.addItem("Meezan — Current", 1)
            self.cmb_company_acct.addItem("HBL — Current", 2)

    def _load_company_accounts(self):
        """Load company bank accounts"""
        self._load_company_accounts_from_db()

    def _reload_company_accounts(self):
        """Reload company bank accounts"""
        self._load_company_accounts_from_db()

    def _load_vendor_accounts(self):
        self.cmb_vendor_acct.clear()
        rows = []
        repo = self.vba_repo
        if repo and self.vendor_id:
            try_methods = ("list_active_for_vendor", "list_for_vendor", "list_by_vendor")
            for m in try_methods:
                if hasattr(repo, m):
                    rows = getattr(repo, m)(self.vendor_id)
                    break
        primary_index = 0
        for i, r in enumerate(rows or []):
            label = _first_key(r, "label", default="Vendor Account")
            vid = _first_key(r, "vendor_bank_account_id", "id")
            self.cmb_vendor_acct.addItem(str(label), vid)
            if _first_key(r, "is_primary", default=0) == 1 and primary_index == 0:
                primary_index = i
        if self.cmb_vendor_acct.count() > 0:
            self.cmb_vendor_acct.setCurrentIndex(primary_index)

    # ---------- items ----------
    def set_items(self, items: list[dict]):
        """
        Accepts flexible keys:
          item_id; product_name/name/product; unit_name/uom_name/uom;
          quantity/qty/qty_purchased; returned_so_far/returned/qty_returned; returnable;
          purchase_price/buy/buy_price/unit_price/unit_cost/cost_price; item_discount/discount/disc
        """
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(items))
        for r, it in enumerate(items):
            item_id = int(_first_key(it, "item_id", default=-1))
            product = str(_first_key(it, "product_name", "name", "product", default=f"#{item_id}"))
            uom = str(_first_key(it, "unit_name", "uom_name", "uom", default=""))
            qty_purchased = float(_first_key(it, "quantity", "qty", "qty_purchased", default=0.0))

            if "returnable" in it and it["returnable"] is not None:
                try:
                    max_returnable = float(it["returnable"])
                    returned_so_far = max(0.0, qty_purchased - max_returnable)
                except Exception:
                    max_returnable = 0.0
                    returned_so_far = 0.0
            else:
                returned_so_far = float(_first_key(it, "returned_so_far", "returned", "qty_returned", default=0.0))
                max_returnable = max(0.0, qty_purchased - returned_so_far)

            buy = float(_first_key(
                it, "purchase_price", "buy_price", "buy",
                "unit_purchase_price", "unit_price", "price",
                "unit_cost", "cost_price", default=0.0
            ))
            disc = float(_first_key(it, "item_discount", "discount", "disc", "unit_discount", default=0.0))
            net_unit = max(0.0, buy - disc)

            def ro(text):
                x = QTableWidgetItem(text)
                x.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                return x

            id_item = ro(str(item_id))
            id_item.setData(Qt.UserRole, {
                "purchase_price": buy,
                "item_discount": disc,
                "net_unit": net_unit,
                "max_returnable": max_returnable,
            })
            self.tbl.setItem(r, self.COL_ITEM_ID, id_item)
            self.tbl.setItem(r, self.COL_PRODUCT, ro(product))
            self.tbl.setItem(r, self.COL_UOM, ro(uom))
            self.tbl.setItem(r, self.COL_QTY_PURCHASED, ro(f"{qty_purchased:g}"))
            self.tbl.setItem(r, self.COL_RETURNED_SO_FAR, ro(f"{returned_so_far:g}"))
            self.tbl.setItem(r, self.COL_MAX_RETURNABLE, ro(f"{max_returnable:g}"))

            q_item = QTableWidgetItem("0")
            q_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, self.COL_QTY_RETURN, q_item)

            v_item = ro("0.00")
            v_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, self.COL_LINE_VALUE, v_item)

            self.tbl.setItem(r, self.COL_NOTES, QTableWidgetItem(""))

        self.tbl.blockSignals(False)
        self._qty_snapshot = self._snapshot_qtys()
        self._recalc_all()

    # ---------- reactive / polling ----------
    def _snapshot_qtys(self):
        return [
            (self.tbl.item(r, self.COL_QTY_RETURN).text() if self.tbl.item(r, self.COL_QTY_RETURN) else "")
            for r in range(self.tbl.rowCount())
        ]

    def _poll_scan_qty(self):
        # Detect programmatic replacements/changes of Qty cells
        curr = self._snapshot_qtys()
        if curr != self._qty_snapshot:
            self._qty_snapshot = curr
            self._recalc_all()

    def _cell_changed(self, row: int, col: int):
        if row >= 0 and col == self.COL_QTY_RETURN:
            self._recalc_row(row)
            self._refresh_totals()
            self._validate()

    def _item_changed(self, item: QTableWidgetItem):
        if item and item.column() == self.COL_QTY_RETURN:
            self._recalc_row(item.row())
            self._refresh_totals()
            self._validate()

    def _meta_for_row(self, r: int):
        id_cell = self.tbl.item(r, self.COL_ITEM_ID)
        meta = (id_cell.data(Qt.UserRole) if id_cell else None) or {}
        if "max_returnable" not in meta or meta["max_returnable"] is None:
            try:
                meta["max_returnable"] = float(self.tbl.item(r, self.COL_MAX_RETURNABLE).text() or "0")
            except Exception:
                meta["max_returnable"] = 0.0
        return meta

    def _recalc_row(self, r: int):
        q_item = self.tbl.item(r, self.COL_QTY_RETURN)
        try:
            qty_ret = float(q_item.text() or "0")
        except Exception:
            qty_ret = 0.0
        meta = self._meta_for_row(r)
        max_ret = float(meta.get("max_returnable") or 0.0)
        net_unit = float(meta.get("net_unit") or 0.0)

        bad = qty_ret < 0 or qty_ret > max_ret + EPSILON
        try:
            if bad:
                q_item.setBackground(QBrush(QColor(255, 200, 200)))  # Light red
                q_item.setToolTip(f"Invalid: must be between 0 and {max_ret:.2f}")  # Add tooltip
            else:
                q_item.setBackground(QBrush(Qt.white))
                q_item.setToolTip("")  # Clear tooltip
        except Exception:
            q_item.setBackground(Qt.red if bad else Qt.white)
            q_item.setToolTip(f"Invalid: must be between 0 and {max_ret:.2f}" if bad else "")

        it_val = self.tbl.item(r, self.COL_LINE_VALUE)
        it_val.setText(fmt_money(max(0.0, qty_ret * net_unit)))
        
        # Update return value and remaining amount - debounce the expensive operation
        self._refresh_return_value()
        if hasattr(self, 'purchase_id') and self.purchase_id:
            # Stop any existing timer and start a new one to debounce the call
            self._remaining_amount_timer.stop()
            self._remaining_amount_timer.start(300)  # 300ms delay

    def _recalc_all(self):
        for r in range(self.tbl.rowCount()):
            self._recalc_row(r)
        self._refresh_totals()
        self._validate()

    def _toggle_return_scope(self, whole_checked: bool):
        """
        When 'Return whole order' is selected, pre-fill each line's
        return quantity with its max_returnable amount.
        """
        if not whole_checked:
            return

        self.tbl.blockSignals(True)
        try:
            for r in range(self.tbl.rowCount()):
                meta = self._meta_for_row(r)
                max_ret = float(meta.get("max_returnable") or 0.0)
                q_item = self.tbl.item(r, self.COL_QTY_RETURN)
                if not q_item:
                    q_item = QTableWidgetItem("0")
                    q_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.tbl.setItem(r, self.COL_QTY_RETURN, q_item)
                q_item.setText(f"{max_ret:g}")
        finally:
            self.tbl.blockSignals(False)

        # Snapshot and recompute totals/validation
        self._qty_snapshot = self._snapshot_qtys()
        self._recalc_all()

    def _refresh_totals(self):
        qty_total = 0.0
        val_total = 0.0
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, self.COL_QTY_RETURN)
            try:
                q = float(it.text() or "0")
            except Exception:
                q = 0.0
            meta = self._meta_for_row(r)
            qty_total += q
            val_total += max(0.0, q * float(meta.get("net_unit") or 0.0))
        self.lab_qty_total.setText(f"{qty_total:g}")
        self.lab_val_total.setText(f"Total Return Value: {fmt_money(val_total)}")
        
        # Update return value display and remaining amount
        self._refresh_return_value()
        if hasattr(self, 'purchase_id') and self.purchase_id:
            self._update_remaining_amount()

    # ---------- settlement ----------
    def _toggle_mode(self):
        is_refund = self.rb_refund_now.isChecked()
        self.ref_panel.setVisible(is_refund)
        if is_refund:
            self.date_instr.setDate(self.date.date())
            # Update visibility of temp bank fields when refund panel becomes visible
            self._update_temp_bank_refund_visibility()
        self._validate()

    def _default_instrument_date(self):
        if self.rb_refund_now.isChecked():
            self.date_instr.setDate(self.date.date())

    def _current_settlement_mode(self) -> str:
        if self.rb_refund_now.isChecked():
            return "refund_now"
        else:
            return "credit_note"

    # ---------- payload ----------
    def get_payload(self) -> dict | None:
        # Ensure any pending edits have been processed and totals are up to date
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass
        # Recalculate to keep totals/validation in sync even if edits were programmatic
        self._recalc_all()

        if not hasattr(self, "tbl"):
            return None

        items = []
        for r in range(self.tbl.rowCount()):
            id_cell = self.tbl.item(r, self.COL_ITEM_ID)
            try:
                item_id = int(id_cell.text())
            except Exception:
                item_id = id_cell.data(Qt.UserRole) if id_cell else -1
            if item_id is None:
                item_id = -1

            qty_it = self.tbl.item(r, self.COL_QTY_RETURN)
            try:
                return_qty = float((qty_it.text() or "0").strip()) if qty_it else 0.0
            except Exception:
                return_qty = 0.0

            if return_qty < 0:
                return None
            if return_qty == 0:
                continue

            meta = self._meta_for_row(r)
            max_ret = float(meta.get("max_returnable") or 0.0)
            if return_qty > max_ret + EPSILON:
                return None

            purchase_price = float(meta.get("purchase_price") or 0.0)
            item_discount = float(meta.get("item_discount") or 0.0)
            if purchase_price < 0 or item_discount < 0:
                return None
            if (purchase_price - item_discount) < -EPSILON:
                return None

            items.append({
                "item_id": int(item_id),
                "return_qty": return_qty,
                "purchase_price": purchase_price,
                "item_discount": item_discount,
            })

        if not items:
            return None

        date_str = self.date.date().toString("yyyy-MM-dd")
        mode = self._current_settlement_mode()

        if mode == "credit_note":
            settlement = {"mode": "credit_note"}
        else:
            method_txt = (self.cmb_method.currentText() or "Bank Transfer").strip()
            bank_id = self._resolve_company_account_id()
            vendor_bank_id = self._resolve_vendor_account_id()
            instr_no = (self.txt_instr_no.text() or "AUTO-REF").strip()
            instr_date = self.date_instr.date().toString("yyyy-MM-dd")

            method_key = self._get_method_key(method_txt)
            
            # Determine instrument type and clearing state based on method
            if method_key == 'BANK_TRANSFER':
                instr_type = "online"
                clearing_state = "cleared"
            elif method_key == 'CHEQUE':
                instr_type = "cheque"
                clearing_state = "cleared"
            elif method_key == 'CROSS_CHEQUE':
                instr_type = "cross_cheque"
                clearing_state = "cleared"
            elif method_key == 'CASH_DEPOSIT':
                instr_type = "cash_deposit"
                clearing_state = "cleared"
                bank_id = None  # Cash deposit doesn't require a company bank account
            elif method_key == 'CASH':
                instr_type = None
                clearing_state = "cleared"
                bank_id = None
                vendor_bank_id = None
                instr_no = ""
                instr_date = date_str
            else:  # OTHER
                instr_type = "other"
                clearing_state = "cleared"
                bank_id = None
                vendor_bank_id = None
                instr_no = ""
                instr_date = date_str

            selected_vendor_account = self.cmb_vendor_acct.currentData()
            is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY

            settlement = {
                "mode": "refund_now",
                "method": method_txt,
                "bank_account_id": bank_id,
                "vendor_bank_account_id": vendor_bank_id if not is_temp_account else None,
                "instrument_type": instr_type,
                "instrument_no": instr_no,
                "instrument_date": instr_date,
                "clearing_state": clearing_state,
                "date": date_str,
                "temp_vendor_bank_name": self.temp_bank_name.text().strip() if is_temp_account else None,
                "temp_vendor_bank_number": self.temp_bank_number.text().strip() if is_temp_account else None,
            }

        # Controller expects `lines`; keep `items` for backward compatibility in case other callers rely on it
        payload = {
            "date": date_str,
            "lines": [
                {
                    "item_id": i["item_id"],
                    "qty_return": i["return_qty"],
                    "purchase_price": i["purchase_price"],
                    "item_discount": i["item_discount"],
                }
                for i in items
            ],
            "items": items,
            "settlement": settlement,
            "notes": (self.notes.text().strip() or None),
        }
        return payload

    def accept(self):
        is_valid, result = self.validate_and_get_payload()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Validation Errors", str(result))
            return
        
        self._payload = result
        super().accept()

    def validate_and_get_payload(self) -> tuple[bool, str | dict]:
        # First run the basic validation checks using the common method
        ok, errors = self._perform_common_validation()
        
        if not ok:
            error_message = "\n".join(errors)
            return False, error_message

        # If validation passes, get the payload
        p = self.get_payload()
        if p is None:
            return False, "Could not generate return payload. Please check all values."
            
        return True, p

    def payload(self):
        return self._payload

    # ---------- remaining calculation ----------
    def set_purchase_id(self, purchase_id: str):
        """Set the purchase ID for this return form, allowing remaining calculation."""
        self.purchase_id = purchase_id
        self._update_remaining_amount()

    def _calculate_return_value(self) -> float:
        """Calculate the total return value based on quantities entered."""
        total_val = 0.0
        for r in range(self.tbl.rowCount()):
            it_qty = self.tbl.item(r, self.COL_QTY_RETURN)
            if not it_qty:
                continue
            try:
                q = float(it_qty.text() or 0.0)
            except Exception:
                q = 0.0
            meta = self._meta_for_row(r)
            total_val += max(0.0, q * float(meta.get("net_unit") or 0.0))
        return total_val

    def _update_remaining_amount(self):
        """Update the remaining amount label for the purchase."""
        if not self.purchase_id:
            self.lbl_remaining.setText("Purchase ID not set")
            return
            
        try:
            # Use the repository pattern to get purchase financials
            if self.purchases_repo:
                financials = self.purchases_repo.fetch_purchase_financials(self.purchase_id)
                
                if financials:
                    total_calc = float(financials.get("calculated_total_amount", 0.0))
                    paid_amount = float(financials.get("paid_amount", 0.0))
                    advance_applied = float(financials.get("advance_payment_applied", 0.0))
                    
                    # Calculate current return value to adjust the remaining
                    current_return_value = self._calculate_return_value()
                    # When a return is processed, it reduces the amount owed on the purchase,
                    # which decreases the "remaining" amount
                    original_remaining = total_calc - paid_amount - advance_applied
                    new_remaining = original_remaining - current_return_value
                    self.lbl_remaining.setText(f"Adjusted Remaining: {new_remaining:.2f} (Original: {original_remaining:.2f})")
                else:
                    self.lbl_remaining.setText("Purchase financials not found")
            else:
                self.lbl_remaining.setText("Purchases repository not available")
                
        except Exception as e:
            import logging
            logging.error(f"Error calculating remaining amount using repository: {e}")
            self.lbl_remaining.setText("Error calculating remaining amount")

    def _refresh_return_value(self):
        """Refresh the return value display."""
        return_value = self._calculate_return_value()
        self.lbl_return_value.setText(f"Return Value: {fmt_money(return_value)}")

    # ---------- validation / OK gating ----------
    def _perform_common_validation(self) -> tuple[bool, list[str]]:
        """Perform common validation checks. Returns (is_valid, list_of_errors)."""
        errors = []
        ok = True
        any_line = False
        
        for r in range(self.tbl.rowCount()):
            it_qty = self.tbl.item(r, self.COL_QTY_RETURN)
            if not it_qty:
                continue
            try:
                q = float(it_qty.text() or 0.0)
            except ValueError:
                errors.append(f"Row {r+1}: Please enter a valid numeric quantity in 'Qty Return' column.")
                ok = False
                continue
                
            meta = self._meta_for_row(r)
            max_ret = float(meta.get("max_returnable") or 0.0)
            if q > 0:
                any_line = True
            if q < 0:
                errors.append(f"Row {r+1}: Return quantity cannot be negative.")
                ok = False
            elif q > max_ret + EPSILON:
                errors.append(f"Row {r+1}: Return quantity ({q}) exceeds max returnable ({max_ret}).")
                ok = False

        if not any_line:
            errors.append("Please enter at least one return line with quantity > 0.")
            ok = False

        if ok and self.rb_refund_now.isChecked():
            total_val = 0.0
            for r in range(self.tbl.rowCount()):
                it_qty = self.tbl.item(r, self.COL_QTY_RETURN)
                if not it_qty:
                    continue
                try:
                    q = float(it_qty.text() or 0.0)
                except ValueError:
                    continue  # This error is already caught above
                meta = self._meta_for_row(r)
                total_val += max(0.0, q * float(meta.get("net_unit") or 0.0))
            if total_val <= 0.0:
                errors.append("Refund amount must be greater than zero.")
                ok = False
            if self.cmb_company_acct.currentIndex() < 0:
                errors.append("Please select a company bank account for refund.")
                ok = False

        return ok, errors

    def _get_method_key(self, display_value: str) -> str | None:
        """Convert a payment method display value to its corresponding key."""
        return self._method_display_to_key.get(display_value)

    def _to_float_safe(self, txt: str) -> float:
        import re
        import logging
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

    def _update_field_enablement(self, enable_company=False, enable_vendor=False, enable_instr=False, enable_temp=False):
        """Centralize the logic for enabling/disabling refund fields."""
        self.cmb_company_acct.setEnabled(enable_company)
        self.cmb_vendor_acct.setEnabled(enable_vendor)
        self.txt_instr_no.setEnabled(enable_instr)
        self.temp_bank_name.setEnabled(enable_temp)
        self.temp_bank_number.setEnabled(enable_temp)

    def _refresh_refund_visibility(self):
        try:
            if not self.rb_refund_now.isChecked():
                self._update_field_enablement(False, False, False, False)
                self._reset_refund_labels()
                return
        except Exception as e:
            import logging
            logging.exception("Error in _refresh_refund_visibility")
            self._update_field_enablement(False, False, False, False)
            self._reset_refund_labels()
            return

        method = self.cmb_method.currentText()
        method_key = self._get_method_key(method)
        need_company = method_key in self.PAYMENT_METHODS_REQUIRE_COMPANY_BANK
        need_vendor  = method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK  
        need_instr   = method_key in self.PAYMENT_METHODS_REQUIRE_INSTRUMENT

        # Determine if temp bank fields should be enabled (both temp account selected and method requires vendor)
        selected_vendor_account = self.cmb_vendor_acct.currentData()
        is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY
        
        # Update temp bank visibility and enabled state
        enable_temp = is_temp_account and need_vendor
        self._update_field_enablement(need_company, need_vendor, need_instr, enable_temp)
        
        if need_vendor and self.vendor_id:
            self._reload_vendor_accounts()  
        
        if hasattr(self, '_refund_labels'):
            self._update_refund_labels(need_company, need_vendor, need_instr)

        self._update_temp_bank_refund_visibility(is_temp_account=is_temp_account, need_vendor=need_vendor)

    def _reset_refund_labels(self):
        """Reset all refund labels to normal state (non-required)"""
        if hasattr(self, '_refund_labels'):
            for label_key, label_widget in self._refund_labels.items():
                if label_widget.styleSheet() != "":
                    plain_text = label_widget.text().rstrip('*')
                    label_widget.setText(plain_text)
                    label_widget.setStyleSheet("")

    def _update_refund_labels(self, need_company=False, need_vendor=False, need_instr=False):
        """Update refund section labels based on required fields"""
        if not hasattr(self, '_refund_labels'):
            return
            
        self._reset_refund_labels()
        
        if need_company and 'company_acct' in self._refund_labels:
            self._set_refund_label_required(self._refund_labels['company_acct'])
        
        if need_vendor and 'vendor_acct' in self._refund_labels:
            self._set_refund_label_required(self._refund_labels['vendor_acct'])
        
        if need_instr and 'instr_no' in self._refund_labels:
            self._set_refund_label_required(self._refund_labels['instr_no'])

    def _set_refund_label_required(self, label_widget):
        """Set a label as required (red asterisk and bold)"""
        current_text = label_widget.text()
        if not current_text.endswith("*"):
            label_widget.setText(current_text + "*")
            label_widget.setStyleSheet("color: red; font-weight: bold;")

    def _update_temp_bank_refund_visibility(self, is_temp_account=None, need_vendor=None):
        """
        Helper method to update temporary bank field visibility and styling.
        If is_temp_account or need_vendor are not provided, they will be calculated.
        The enable/disable logic is now handled in _refresh_refund_visibility
        """
        if is_temp_account is None:
            selected_value = self.cmb_vendor_acct.currentData()
            is_temp_account = selected_value == self.TEMP_BANK_KEY
        
        if need_vendor is None:
            method = self.cmb_method.currentText()
            need_vendor = method in (self.PAYMENT_METHODS['BANK_TRANSFER'], 
                                   self.PAYMENT_METHODS['CROSS_CHEQUE'], 
                                   self.PAYMENT_METHODS['CASH_DEPOSIT'])
        
        if is_temp_account and need_vendor:
            temp_name_label = self._refund_labels.get('temp_bank_name')
            if temp_name_label and not temp_name_label.text().endswith('*'):
                temp_name_label.setText(temp_name_label.text() + "*")
                temp_name_label.setStyleSheet("color: red; font-weight: bold;")
                
            temp_number_label = self._refund_labels.get('temp_bank_number')
            if temp_number_label and not temp_number_label.text().endswith('*'):
                temp_number_label.setText(temp_number_label.text() + "*")
                temp_number_label.setStyleSheet("color: red; font-weight: bold;")
                
            self.temp_bank_name.setVisible(True)
            self.temp_bank_number.setVisible(True)
            self.temp_bank_name.setEnabled(True)
            self.temp_bank_number.setEnabled(True)
        else:
            temp_name_label = self._refund_labels.get('temp_bank_name')
            if temp_name_label:
                temp_name_label.setText(temp_name_label.text().rstrip('*'))
                temp_name_label.setStyleSheet("")
                
            temp_number_label = self._refund_labels.get('temp_bank_number')
            if temp_number_label:
                temp_number_label.setText(temp_number_label.text().rstrip('*'))
                temp_number_label.setStyleSheet("")
                
            self.temp_bank_name.setVisible(True)  # Keep visible but disable
            self.temp_bank_number.setVisible(True)  # Keep visible but disable
            self.temp_bank_name.setEnabled(False)
            self.temp_bank_number.setEnabled(False)

    def _on_vendor_bank_account_changed(self):
        """Show/hide temporary bank fields based on selection"""
        self._update_temp_bank_refund_visibility()

    def _reload_company_accounts(self):
        """Reload company bank accounts"""
        self._load_company_accounts_from_db()

    def _reload_vendor_accounts(self):
        current_text = self.cmb_vendor_acct.currentText()
        
        self.cmb_vendor_acct.clear()
        vid = self.vendor_id
        
        if not vid:
            self.cmb_vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
            return
        
        rows = []
        repo = self.vba_repo
        if repo and self.vendor_id:
            try_methods = ("list_active_for_vendor", "list_for_vendor", "list_by_vendor")
            for m in try_methods:
                if hasattr(repo, m):
                    rows = getattr(repo, m)(self.vendor_id)
                    break
        
        primary_index = 0
        for i, r in enumerate(rows or []):
            label = _first_key(r, "label", default="Vendor Account")
            bank_account_id = _first_key(r, "vendor_bank_account_id", "id")
            self.cmb_vendor_acct.addItem(str(label), bank_account_id)
            if _first_key(r, "is_primary", default=0) == 1 and primary_index == 0:
                primary_index = i
        
        self.cmb_vendor_acct.addItem("Temporary/External Bank Account", self.TEMP_BANK_KEY)
        
        import logging
        try:
            previous_selection_restored = False
            if current_text and current_text != "":
                index = self.cmb_vendor_acct.findText(current_text)
                if index >= 0:
                    self.cmb_vendor_acct.setCurrentIndex(index)
                    previous_selection_restored = True
            
            current_method = self.cmb_method.currentText()
            current_method_key = self._get_method_key(current_method)
            needs_vendor_account = current_method_key in self.PAYMENT_METHODS_REQUIRE_VENDOR_BANK
            
            if not previous_selection_restored and primary_index and needs_vendor_account:
                for i in range(self.cmb_vendor_acct.count() - 1):  # Exclude temp bank option  
                    item_text = self.cmb_vendor_acct.itemText(i)
                    if "(Primary)" in item_text:
                        self.cmb_vendor_acct.setCurrentIndex(i)
                        break
            elif not previous_selection_restored and not needs_vendor_account:
                self.cmb_vendor_acct.setCurrentIndex(-1)  
        
        except ValueError:
            logging.error(f"Error: Invalid vendor ID: {vid}")
            logging.exception("Invalid vendor ID in _reload_vendor_accounts")

    def _resolve_company_account_id(self) -> int | None:
        """Resolve company bank account ID from editable combobox text"""
        company_acct_text = self.cmb_company_acct.currentText().strip()
        company_id = self.cmb_company_acct.currentData()
        
        if company_id is None and company_acct_text:
            try:
                # Try to find account using the database connection
                conn = getattr(self.vendors, 'conn', None) if self.vendors else None
                
                if conn:
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
                        import logging
                        logging.warning(f"Company bank account not found for label: {company_acct_text}")
                else:
                    # Fallback to repo if connection not available
                    if self.cba_repo and hasattr(self.cba_repo, 'find_by_label'):
                        account = self.cba_repo.find_by_label(company_acct_text)
                        if account:
                            company_id = account.get('account_id') or account.get('id')
                    elif self.cba_repo and hasattr(self.cba_repo, 'list_active'):
                        # Fallback: search through active accounts
                        all_accounts = self.cba_repo.list_active()
                        for acc in all_accounts:
                            if acc.get('label', '').lower() == company_acct_text.lower():
                                company_id = acc.get('account_id') or acc.get('id')
                                break
            except Exception as e:
                import logging
                logging.error(f"Error resolving company bank account ID for '{company_acct_text}': {e}")
                company_id = None
        
        return company_id

    def _resolve_vendor_account_id(self) -> int | None:
        """Resolve vendor bank account ID from editable combobox text"""
        vendor_acct_text = self.cmb_vendor_acct.currentText().strip()
        vendor_bank_id = self.cmb_vendor_acct.currentData()
        
        # Check if it's a temporary account immediately after retrieving the value
        if vendor_bank_id == self.TEMP_BANK_KEY:
            return None  # Temp account has no ID
        
        if vendor_bank_id is None and vendor_acct_text:
            try:
                # Try to find account in repo
                if self.vba_repo and hasattr(self.vba_repo, 'find_by_label'):
                    account = self.vba_repo.find_by_label(vendor_acct_text, self.vendor_id)
                    if account:
                        vendor_bank_id = account.get('vendor_bank_account_id') or account.get('id')
                elif self.vba_repo and hasattr(self.vba_repo, 'list_active_for_vendor'):
                    # Fallback: search through active vendor accounts
                    all_accounts = self.vba_repo.list_active_for_vendor(self.vendor_id)
                    for acc in all_accounts:
                        if acc.get('label', '').lower() == vendor_acct_text.lower():
                            vendor_bank_id = acc.get('vendor_bank_account_id') or acc.get('id')
                            break
            except Exception as e:
                import logging
                logging.error(f"Error resolving vendor bank account ID for '{vendor_acct_text}' and vendor {self.vendor_id}: {e}")
                vendor_bank_id = None
        
        return vendor_bank_id

    def _validate(self):
        # Keep the OK button always enabled to allow users to attempt submission
        btn_ok = self.buttons.button(QDialogButtonBox.Ok)
        if btn_ok:
            btn_ok.setEnabled(True)

    def _validate_refund_details(self) -> tuple[bool, list[str]]:
        """Validate refund details and return (is_valid, errors)"""
        errors = []
        total_val = self._calculate_return_value()
        
        if total_val <= 0:
            errors.append("Refund amount must be greater than zero.")
            return len(errors) == 0, errors

        method = self.cmb_method.currentText()
        
        selected_vendor_account = self.cmb_vendor_acct.currentData()
        is_temp_account = selected_vendor_account == self.TEMP_BANK_KEY

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
            
            if rule.get('requires_company_acct', False) and self.cmb_company_acct.currentData() is None:
                errors.append(rule['error_msg_company'])
            
            if rule.get('requires_vendor_acct', False):
                if self.cmb_vendor_acct.currentData() is None:
                    errors.append(rule['error_msg_vendor'])
                elif is_temp_account and rule.get('requires_temp_details', False):
                    if not self.temp_bank_name.text().strip():
                        errors.append(rule['error_msg_temp_name'])
                    if not self.temp_bank_number.text().strip():
                        errors.append(rule['error_msg_temp_number'])
            
            if rule.get('requires_instr_no', False) and not self.txt_instr_no.text().strip():
                errors.append(rule['error_msg_instr'])

        return len(errors) == 0, errors
