from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QPushButton, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QSpinBox
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QIcon
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.validators import is_positive_number
from ...utils.helpers import today_str, fmt_money
from pathlib import Path
TRASH_ICON = None  # optional; you can drop a png into resources/icons and set the path

class PurchaseForm(QDialog):
    COLS = ["#", "Product", "Qty", "Buy Price", "Sale Price", "Discount", "Line Total", ""]
    def __init__(self, parent=None, vendors: VendorsRepo | None = None, products: ProductsRepo | None = None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase")
        self.setModal(True)
        self.vendors = vendors
        self.products = products
        self._payload = None
        # --- Header fields ---
        self.cmb_vendor = QComboBox(); self.cmb_vendor.setEditable(True)
        for v in self.vendors.list_vendors():
            self.cmb_vendor.addItem(f"{v.name} (#{v.vendor_id})", v.vendor_id)
        self.date = QDateEdit(); self.date.setCalendarPopup(True)
        self.date.setDate(QDate.fromString(initial["date"], "yyyy-MM-dd") if initial and initial.get("date") else QDate.fromString(today_str(), "yyyy-MM-dd"))
        self.txt_discount = QLineEdit(); self.txt_discount.setPlaceholderText("0")
        self.txt_notes = QLineEdit()
        # --- Items table (editable) ---
        items_box = QGroupBox("Items")
        ib = QVBoxLayout(items_box)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.tbl.horizontalHeader().setStretchLastSection(False)
        self.tbl.setColumnWidth(0, 40)    # #
        self.tbl.setColumnWidth(1, 260)   # Product
        self.tbl.setColumnWidth(2, 100)   # Qty
        self.tbl.setColumnWidth(3, 120)   # Buy
        self.tbl.setColumnWidth(4, 120)   # Sale
        self.tbl.setColumnWidth(5, 120)   # Discount
        self.tbl.setColumnWidth(6, 130)   # Line Total
        self.tbl.setColumnWidth(7, 48)    # delete
        # A1) Hide vertical header numbers so "#" only appears once
        self.tbl.verticalHeader().setVisible(False)
        ib.addWidget(self.tbl, 1)
        btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add Row")
        btns.addWidget(self.btn_add_row)
        btns.addStretch(1)
        ib.addLayout(btns)
        # --- Totals ---
        tot = QHBoxLayout()
        self.lab_sub = QLabel("0.00")
        self.lab_disc = QLabel("0.00")
        self.lab_total = QLabel("0.00")
        tot.addStretch(1)
        tot.addWidget(QLabel("Subtotal:")); tot.addWidget(self.lab_sub)
        tot.addWidget(QLabel("Order Discount:")); tot.addWidget(self.lab_disc)
        tot.addWidget(QLabel("Total:")); tot.addWidget(self.lab_total)
        # --- Initial Payment panel (method-specific fields) ---
        ip_box = QGroupBox("Initial Payment (optional)")
        ip = QFormLayout(ip_box)
        # Amount & date
        self.ip_amount = QLineEdit(); self.ip_amount.setPlaceholderText("0")   # >0 means "create payment row"
        self.ip_date = QDateEdit(); self.ip_date.setCalendarPopup(True)
        # default payment date = header date
        self.ip_date.setDate(self.date.date())
        # Method selector (restricted)
        self.ip_method = QComboBox()
        self.ip_method.addItems(["Bank Transfer", "Cheque", "Cash Deposit"])  # match DB triggers
        # Shared/conditional fields
        self.ip_company_acct = QComboBox(); self.ip_company_acct.setEditable(True)
        self.ip_vendor_acct  = QComboBox(); self.ip_vendor_acct.setEditable(True)
        self.ip_instr_no     = QLineEdit(); self.ip_instr_no.setPlaceholderText("Instrument / Cheque / Slip #")
        self.ip_instr_date   = QDateEdit(); self.ip_instr_date.setCalendarPopup(True)
        self.ip_instr_date.setDate(self.ip_date.date())  # default to payment date
        self.ip_ref_no       = QLineEdit(); self.ip_ref_no.setPlaceholderText("Reference (optional)")
        self.ip_notes        = QLineEdit(); self.ip_notes.setPlaceholderText("Notes (optional)")
        # We'll store method-derived fixed values here when building payload
        self._ip_instrument_type = None
        self._ip_clearing_state  = None
        # Lay out fields (some will be hidden per method)
        ip.addRow("Amount", self.ip_amount)
        ip.addRow("Payment Date", self.ip_date)
        ip.addRow("Method", self.ip_method)
        ip.addRow("Company Bank Account", self.ip_company_acct)
        ip.addRow("Vendor Bank Account", self.ip_vendor_acct)
        ip.addRow("Instrument No", self.ip_instr_no)
        ip.addRow("Instrument Date", self.ip_instr_date)
        ip.addRow("Ref No", self.ip_ref_no)
        ip.addRow("Payment Notes", self.ip_notes)
        # --- Main layout ---
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Vendor*", self.cmb_vendor)
        form.addRow("Date*", self.date)
        form.addRow("Order Discount", self.txt_discount)
        form.addRow("Notes", self.txt_notes)
        lay.addLayout(form)
        lay.addWidget(items_box, 1)
        lay.addLayout(tot)
        lay.addWidget(ip_box)
        # state
        self._rows = []  # internal cache; each row is dict like payload item
        if initial and initial.get("items"):
            self._rows = [dict(x) for x in initial["items"]]
        # wire
        self.btn_add_row.clicked.connect(self._add_row)
        self.tbl.cellChanged.connect(self._cell_changed)
        self.txt_discount.textChanged.connect(self._refresh_totals)
        # NEW: wire vendor/method/date for the IP panel
        self.cmb_vendor.currentIndexChanged.connect(self._reload_vendor_accounts)
        self.ip_method.currentIndexChanged.connect(self._refresh_ip_visibility)
        self.ip_date.dateChanged.connect(lambda _d: self.ip_instr_date.setDate(self.ip_date.date()))
        # Keep payment date aligned with header date until user enters amount
        self.date.dateChanged.connect(
            lambda _d: (self.ip_date.setDate(self.date.date())
                        if (self.ip_amount.text().strip() in ("", "0", "0.0")) else None)
        )
        # prefill
        if initial:
            idx = self.cmb_vendor.findData(initial["vendor_id"])
            if idx >= 0: self.cmb_vendor.setCurrentIndex(idx)
            self.txt_discount.setText(str(initial.get("order_discount", 0) or 0))
            self.txt_notes.setText(initial.get("notes") or "")
        # initialize IP panel lists/visibility
        self._reload_company_accounts()
        self._reload_vendor_accounts()
        self._refresh_ip_visibility()
        self._rebuild_table()
        self._refresh_totals()
        # size
        self.resize(980, 720)  # taller for the IP panel
        self.setSizeGripEnabled(True)
    # ---------------- helpers for initial payment panel ----------------
    def _reload_company_accounts(self):
        """Populate company bank accounts (active only)."""
        self.ip_company_acct.clear()
        try:
            conn = self.vendors.conn  # reuse existing repo connection
            rows = conn.execute(
                "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
            ).fetchall()
            for r in rows:
                self.ip_company_acct.addItem(r["label"], int(r["account_id"]))
        except Exception:
            # leave empty; validation will catch missing accounts when required
            pass
    def _reload_vendor_accounts(self):
        """Populate vendor bank accounts for the selected vendor (active only; primary first)."""
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
                (int(vid),)
            ).fetchall()
            for r in rows:
                label = r["label"] + (" (Primary)" if str(r.get("is_primary", 0)) in ("1", "True", "true") else "")
                self.ip_vendor_acct.addItem(label, int(r["vba_id"]))
        except Exception:
            pass
    def _refresh_ip_visibility(self):
        """
        Show/hide fields and set fixed instrument_type & default clearing_state per method.
        DB rules recap:
          - Bank Transfer: requires company acct, vendor acct, instrument_no; instrument_type='online'; clearing_state='posted'
          - Cheque: requires company acct, vendor acct, instrument_no; instrument_type='cross_cheque'; clearing_state='pending'
          - Cash Deposit: requires vendor acct, instrument_no; instrument_type='cash_deposit'; clearing_state='pending'
        """
        method = self.ip_method.currentText()
        # default visibility needs
        need_company = (method in ("Bank Transfer", "Cheque"))
        need_vendor  = (method in ("Bank Transfer", "Cheque", "Cash Deposit"))
        need_instr   = True
        need_idate   = True
        # Make sure the rows exist (FormLayout rows contain the widgets directly)
        self.ip_company_acct.setEnabled(need_company)
        self.ip_company_acct.setVisible(need_company)
        self.ip_vendor_acct.setEnabled(need_vendor)
        self.ip_vendor_acct.setVisible(need_vendor)
        self.ip_instr_no.setEnabled(need_instr)
        self.ip_instr_no.setVisible(need_instr)
        self.ip_instr_date.setEnabled(need_idate)
        self.ip_instr_date.setVisible(need_idate)
        # instrument type & clearing default by method
        if method == "Bank Transfer":
            self._ip_instrument_type = "online"
            self._ip_clearing_state  = "posted"
        elif method == "Cheque":
            self._ip_instrument_type = "cross_cheque"
            self._ip_clearing_state  = "pending"
        elif method == "Cash Deposit":
            self._ip_instrument_type = "cash_deposit"
            self._ip_clearing_state  = "pending"
        else:
            self._ip_instrument_type = None
            self._ip_clearing_state  = None
    # ---------------- table helpers ----------------
    def _all_products(self):
        return self.products.list_products()
    def _base_uom_id(self, product_id: int) -> int:
        base = self.products.get_base_uom(product_id)  # returns {"uom_id","unit_name"} or None
        if base: return int(base["uom_id"])
        # very defensive fallback: first global UoM
        u = self.products.list_uoms()
        return int(u[0]["uom_id"]) if u else 1
    # A2) Block cellChanged while building rows; recalc after unblocked
    def _add_row(self, pre: dict | None = None):
        self.tbl.blockSignals(True)  # block during row construction
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        # #: row number cell also carries hidden uom_id in UserRole
        num = QTableWidgetItem(str(r+1))
        num.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 0, num)
        # Product combo
        from PySide6.QtWidgets import QComboBox
        cmb_prod = QComboBox()
        for p in self._all_products():
            cmb_prod.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.tbl.setCellWidget(r, 1, cmb_prod)
        # Qty / Buy / Sale / Discount (editable numbers)
        for c in (2, 3, 4, 5):
            it = QTableWidgetItem("0")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, c, it)
        # Line total (read-only)
        it_total = QTableWidgetItem("0.00")
        it_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_total.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 6, it_total)
        # Delete button
        btn_del = QPushButton("✕")
        def kill():
            self.tbl.removeRow(r)
            self._reindex_rows()
            self._refresh_totals()
        btn_del.clicked.connect(kill)
        self.tbl.setCellWidget(r, 7, btn_del)
        # When product changes, store its Base UoM id (hidden)
        def on_prod_changed():
            pid = cmb_prod.currentData()
            self.tbl.item(r, 0).setData(Qt.UserRole, self._base_uom_id(int(pid)) if pid else None)
            self._recalc_row(r); self._refresh_totals()
        cmb_prod.currentIndexChanged.connect(on_prod_changed)
        # Prefill for edit
        if pre:
            i = cmb_prod.findData(pre.get("product_id"))
            if i >= 0: cmb_prod.setCurrentIndex(i)
            self.tbl.item(r, 2).setText(str(pre.get("quantity", 0)))
            self.tbl.item(r, 3).setText(str(pre.get("purchase_price", 0)))
            self.tbl.item(r, 4).setText(str(pre.get("sale_price", 0)))
            self.tbl.item(r, 5).setText(str(pre.get("item_discount", 0)))
            # Keep the original uom_id if provided; otherwise base will be set above
            if "uom_id" in pre:
                self.tbl.item(r, 0).setData(Qt.UserRole, int(pre["uom_id"]))
        # initialize uom for empty rows and compute once fully ready
        if not pre:
            on_prod_changed()
        self.tbl.blockSignals(False)  # unblock when done
        self._recalc_row(r)           # safe: row is fully built now
    def _reindex_rows(self):
        for r in range(self.tbl.rowCount()):
            if self.tbl.item(r, 0):
                self.tbl.item(r, 0).setText(str(r+1))
    # A2) Rebuild table with signals blocked
    def _rebuild_table(self):
        self.tbl.blockSignals(True)  # avoid interim signals
        self.tbl.setRowCount(0)
        if not self._rows:
            self._add_row({})
        else:
            for row in self._rows:
                self._add_row(row)
        self.tbl.blockSignals(False)
        self._refresh_totals()
    # A3) Guard against half-built rows
    def _cell_changed(self, row: int, col: int):
        if row < 0 or row >= self.tbl.rowCount():
            return
        # bail if any required cell is missing (row still initializing)
        for c in (2, 3, 4, 5, 6):
            if self.tbl.item(row, c) is None:
                return
        self._recalc_row(row)
        self._refresh_totals()
    # A4) Correct pricing rules and line total formula with validation highlights
    def _recalc_row(self, r: int):
        # read numbers safely
        def num(c):
            it = self.tbl.item(r, c)
            try:
                return float(it.text()) if it and it.text() else 0.0
            except Exception:
                return 0.0
        qty  = num(2)
        buy  = num(3)
        sale = num(4)
        disc = num(5)  # per-unit discount
        # enforce: sale ≥ buy and 0 ≤ discount < buy
        def mark(col, bad):
            it = self.tbl.item(r, col)
            if it:
                it.setBackground(Qt.red if bad else Qt.white)
        bad_buy  = buy <= 0
        bad_sale = not (sale >= buy > 0)
        bad_disc = not (0 <= disc < buy if buy > 0 else disc == 0)
        mark(3, bad_buy)
        mark(4, bad_sale or bad_buy)
        mark(5, bad_disc or bad_buy)
        # Line Total = (qty × buy) − (qty × discount_per_unit)
        line_total = max(0.0, qty * (buy - disc))
        lt_item = self.tbl.item(r, 6)
        if lt_item:
            lt_item.setText(fmt_money(line_total))
    # A5) Subtotal must include per-unit discount
    def _calc_subtotal(self) -> float:
        s = 0.0
        for r in range(self.tbl.rowCount()):
            try:
                qty  = float(self.tbl.item(r, 2).text() or 0)
                buy  = float(self.tbl.item(r, 3).text() or 0)
                disc = float(self.tbl.item(r, 5).text() or 0)
            except Exception:
                continue
            s += max(0.0, qty * (buy - disc))
        return s
    def _refresh_totals(self):
        sub = self._calc_subtotal()
        try:
            disc = float(self.txt_discount.text()) if self.txt_discount.text().strip() else 0.0
        except Exception:
            disc = 0.0
        tot = max(0.0, sub - disc)
        self.lab_sub.setText(fmt_money(sub))
        self.lab_disc.setText(fmt_money(disc))
        self.lab_total.setText(fmt_money(tot))
    # ------------- payload -------------
    def _row_payload(self, r: int) -> dict | None:
        from PySide6.QtWidgets import QComboBox
        cmb_prod: QComboBox = self.tbl.cellWidget(r, 1)
        if not cmb_prod: return None
        pid = cmb_prod.currentData()
        if not pid: return None
        def num(c):
            it = self.tbl.item(r, c)
            try:
                return float(it.text()) if it and it.text() else 0.0
            except Exception:
                return 0.0
        qty  = num(2)
        buy  = num(3)
        sale = num(4)
        disc = num(5)
        # integrity
        if qty <= 0 or buy <= 0 or not (sale >= buy) or not (0 <= disc < buy):
            return None
        # base uom from hidden data (fallback to lookup)
        uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
        if not uom_id:
            uom_id = self._base_uom_id(int(pid))
        return {
            "product_id": int(pid),
            "uom_id": int(uom_id),
            "quantity": qty,
            "purchase_price": buy,
            "sale_price": sale,
            "item_discount": disc
        }
    def get_payload(self) -> dict | None:
        """
        Build a payload that the controller/repos consume.
        Rules:
          - Items must be valid (qty > 0, buy > 0, 0 <= item_discount < buy).
          - Base-UoM only (your rows already lock UoM to base).
          - Initial payment is OPTIONAL: only validate & include it when amount > 0.
        """
        try:
            vendor_id = int(self.cmb_vendor.currentData())
        except Exception:
            return None
        
        # --- collect rows ---
        rows = []
        for r in range(self.tbl.rowCount()):
            # product combobox in column 1; numeric cells in 2..5 (qty, buy, sale, disc)
            cmb_prod = self.tbl.cellWidget(r, 1)
            if not cmb_prod:
                continue
            product_id = cmb_prod.currentData()
            if product_id in (None, ""):
                continue
            qty_it  = self.tbl.item(r, 2)
            buy_it  = self.tbl.item(r, 3)
            sale_it = self.tbl.item(r, 4)
            disc_it = self.tbl.item(r, 5)
            try:
                qty  = float((qty_it.text() or "0").strip())
                buy  = float((buy_it.text() or "0").strip())
                sale = float((sale_it.text() or "0").strip())
                disc = float((disc_it.text() or "0").strip())
            except Exception:
                return None
            # pricing rules (match the tests)
            if qty <= 0 or buy <= 0:
                return None
            if disc < 0 or disc >= buy:
                return None
            # sale can be anything (even < buy) by design
            # Base UoM only – your grid already locks it; if you stash base uom_id, use it.
            # Many projects store base uom_id on the row; fall back to a lookup label if you have it.
            uom_id = self.tbl.item(r, 0).data(Qt.UserRole)
            if uom_id is None:
                try:
                    uom_id = int(self.products.get_base_uom(product_id)["uom_id"])
                except Exception:
                    uom_id = self._base_uom_id(product_id)
            if uom_id is None:
                return None
            rows.append({
                "product_id": int(product_id),
                "uom_id": int(uom_id),
                "quantity": qty,
                "purchase_price": buy,
                "sale_price": sale,
                "item_discount": disc,
            })
        
        if not rows:
            return None
        
        # totals from labels/fields you already update
        date_str = self.date.date().toString("yyyy-MM-dd")
        order_disc = 0.0
        try:
            order_disc = float((self.txt_discount.text() or "0").strip())
        except Exception:
            order_disc = 0.0
        
        # Let the repo recalc anyway; still send UI total for UX parity
        total_amount = self._calc_subtotal() - order_disc
        
        payload = {
            "vendor_id": vendor_id,
            "date": date_str,
            "order_discount": order_disc,
            "notes": (self.txt_notes.text().strip() or None),
            "items": rows,
            "total_amount": total_amount,
        }
        
        # --- Initial Payment (optional) ---
        # Only include & validate if amount > 0
        ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
        ip_amount = 0.0
        if ip_amount_txt:
            try:
                ip_amount = float(ip_amount_txt)
            except Exception:
                ip_amount = -1  # invalid -> block
        
        if ip_amount > 0:
            method = self.ip_method.currentText() if hasattr(self, "ip_method") else ""
            company_id = self.ip_company_acct.currentData() if hasattr(self, "ip_company_acct") else None
            vendor_bank_id = self.ip_vendor_acct.currentData() if hasattr(self, "ip_vendor_acct") else None
            instr_no = self.ip_instr_no.text().strip() if hasattr(self, "ip_instr_no") else ""
            instr_date = self.ip_instr_date.date().toString("yyyy-MM-dd") if hasattr(self, "ip_instr_date") else date_str
            ref_no = self.ip_ref_no.text().strip() if hasattr(self, "ip_ref_no") else None
            notes = self.ip_notes.text().strip() if hasattr(self, "ip_notes") else None
            
            # method guards (parity with DB triggers)
            m = (method or "").strip().lower()
            if m == "bank transfer":
                if not company_id or not vendor_bank_id or not instr_no:
                    return None
                instr_type = "online"
                clearing_state = "posted"
            elif m == "cheque":
                if not company_id or not vendor_bank_id or not instr_no:
                    return None
                instr_type = "cross_cheque"
                clearing_state = "pending"
            elif m == "cash deposit":
                if not vendor_bank_id or not instr_no:
                    return None
                instr_type = "cash_deposit"
                clearing_state = "pending"
                company_id = None
            else:
                # unrecognized method → block
                return None
            
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
            
            # also expose legacy flat aliases for any older consumers
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
            # legacy numeric/method fields (some code paths still read these)
            payload["initial_method"] = payload["initial_payment"]["method"]
        
        return payload

    def accept(self):
        p = self.get_payload()
        if p is None: return
        self._payload = p
        super().accept()
    def payload(self):
        return self._payload