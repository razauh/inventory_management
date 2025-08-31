from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QPushButton, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QScrollArea, QWidget, QHeaderView, QGridLayout
)
from PySide6.QtCore import Qt, QDate
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.helpers import today_str, fmt_money

TRASH_ICON = None  # optional; you can drop a png into resources/icons and set the path


class PurchaseForm(QDialog):
    # Discount column removed
    COLS = ["#", "Product", "Qty", "Buy Price", "Sale Price", "Line Total", ""]

    def __init__(self, parent=None, vendors: VendorsRepo | None = None,
                 products: ProductsRepo | None = None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase")
        self.setModal(True)
        self.vendors = vendors
        self.products = products
        self._payload = None

        # ===== Content (inside scroll) =====
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # --- Header (two columns) ---
        self.cmb_vendor = QComboBox(); self.cmb_vendor.setEditable(True)
        for v in self.vendors.list_vendors():
            self.cmb_vendor.addItem(f"{v.name} (#{v.vendor_id})", v.vendor_id)

        self.date = QDateEdit(); self.date.setCalendarPopup(True)
        self.date.setDate(
            QDate.fromString(initial["date"], "yyyy-MM-dd")
            if initial and initial.get("date") else
            QDate.fromString(today_str(), "yyyy-MM-dd")
        )
        # Order discount removed
        self.txt_notes = QLineEdit()

        header_box = QGroupBox()
        hg = QGridLayout(header_box)
        hg.setHorizontalSpacing(12); hg.setVerticalSpacing(8)

        def add_pair(row, col, text, widget):
            c = col * 2
            hg.addWidget(QLabel(text), row, c)
            hg.addWidget(widget, row, c + 1)

        add_pair(0, 0, "Vendor*", self.cmb_vendor)
        add_pair(0, 1, "Date*", self.date)
        add_pair(1, 0, "Notes", self.txt_notes)
        hg.setColumnStretch(1, 1)
        hg.setColumnStretch(3, 1)
        main_layout.addWidget(header_box)

        # --- Items table (expand to fill space) ---
        items_box = QGroupBox("Items")
        ib = QVBoxLayout(items_box)
        ib.setSpacing(8)

        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.tbl.verticalHeader().setVisible(False)

        header = self.tbl.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Product column grows
        # compact widths for numeric cols (indices updated)
        self.tbl.setColumnWidth(0, 40)   # #
        self.tbl.setColumnWidth(2, 80)   # Qty
        self.tbl.setColumnWidth(3, 110)  # Buy
        self.tbl.setColumnWidth(4, 110)  # Sale
        self.tbl.setColumnWidth(5, 120)  # Line Total
        self.tbl.setColumnWidth(6, 48)   # Delete btn

        ib.addWidget(self.tbl, 1)

        row_btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add Row")
        row_btns.addWidget(self.btn_add_row)
        row_btns.addStretch(1)
        ib.addLayout(row_btns)

        main_layout.addWidget(items_box, 2)

        # --- Totals (compact) ---
        tot = QHBoxLayout()
        self.lab_sub = QLabel("0.00")
        self.lab_total = QLabel("0.00")
        tot.addStretch(1)
        tot.addWidget(QLabel("Subtotal:")); tot.addWidget(self.lab_sub)
        tot.addSpacing(16)
        tot.addWidget(QLabel("Total:"));    tot.addWidget(self.lab_total)
        main_layout.addLayout(tot)

        # --- Initial Payment (two columns) ---
        ip_box = QGroupBox("Initial Payment (optional)")
        ipg = QGridLayout(ip_box)
        ipg.setHorizontalSpacing(12); ipg.setVerticalSpacing(8)

        self.ip_amount = QLineEdit();    self.ip_amount.setPlaceholderText("0")
        self.ip_date = QDateEdit();      self.ip_date.setCalendarPopup(True); self.ip_date.setDate(self.date.date())

        # Include Cash (top) and Other
        self.ip_method = QComboBox()
        self.ip_method.addItems(["Cash", "Bank Transfer", "Cheque", "Cash Deposit", "Other"])

        self.ip_company_acct = QComboBox(); self.ip_company_acct.setEditable(True)
        self.ip_vendor_acct  = QComboBox(); self.ip_vendor_acct.setEditable(True)
        self.ip_instr_no   = QLineEdit(); self.ip_instr_no.setPlaceholderText("Instrument / Cheque / Slip #")
        self.ip_instr_date = QDateEdit(); self.ip_instr_date.setCalendarPopup(True); self.ip_instr_date.setDate(self.ip_date.date())
        self.ip_ref_no     = QLineEdit(); self.ip_ref_no.setPlaceholderText("Reference (optional)")
        self.ip_notes      = QLineEdit(); self.ip_notes.setPlaceholderText("Notes (optional)")

        def add_ip(row, col, text, widget):
            c = col * 2
            ipg.addWidget(QLabel(text), row, c)
            ipg.addWidget(widget, row, c + 1)

        add_ip(0, 0, "Amount", self.ip_amount)
        add_ip(0, 1, "Payment Date", self.ip_date)
        add_ip(1, 0, "Method", self.ip_method)
        add_ip(1, 1, "Company Bank Account", self.ip_company_acct)
        add_ip(2, 0, "Vendor Bank Account", self.ip_vendor_acct)
        add_ip(2, 1, "Instrument No", self.ip_instr_no)
        add_ip(3, 0, "Instrument Date", self.ip_instr_date)
        add_ip(3, 1, "Ref No", self.ip_ref_no)
        ipg.addWidget(QLabel("Payment Notes"), 4, 0)
        ipg.addWidget(self.ip_notes, 4, 1, 1, 3)
        ipg.setColumnStretch(1, 1)
        ipg.setColumnStretch(3, 1)

        self._ip_instrument_type = None
        self._ip_clearing_state = None

        main_layout.addWidget(ip_box, 0)

        # ===== Buttons OUTSIDE scroll =====
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Scroll wrapper
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

        # ===== State / wiring =====
        self._rows = []
        if initial and initial.get("items"):
            self._rows = [dict(x) for x in initial["items"]]

        self.btn_add_row.clicked.connect(self._add_row)
        self.tbl.cellChanged.connect(self._cell_changed)

        self.cmb_vendor.currentIndexChanged.connect(self._reload_vendor_accounts)
        self.ip_method.currentIndexChanged.connect(self._refresh_ip_visibility)
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

        # Sensible sizing for 1366×768 screens
        self.resize(1100, 700)
        self.setMinimumSize(860, 560)
        self.setSizeGripEnabled(True)

    # ---------------- helpers for initial payment panel ----------------
    def _reload_company_accounts(self):
        self.ip_company_acct.clear()
        try:
            conn = self.vendors.conn
            rows = conn.execute(
                "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
            ).fetchall()
            for r in rows:
                self.ip_company_acct.addItem(r["label"], int(r["account_id"]))
        except Exception:
            pass

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
                label = r["label"] + (" (Primary)" if str(r.get("is_primary", 0)) in ("1","True","true") else "")
                self.ip_vendor_acct.addItem(label, int(r["vba_id"]))
        except Exception:
            pass

    def _refresh_ip_visibility(self):
        method = self.ip_method.currentText()
        need_company = method in ("Bank Transfer", "Cheque")
        need_vendor  = method in ("Bank Transfer", "Cheque", "Cash Deposit")
        need_instr   = method in ("Bank Transfer", "Cheque", "Cash Deposit")
        need_idate   = method in ("Bank Transfer", "Cheque", "Cash Deposit")

        self.ip_company_acct.setEnabled(need_company); self.ip_company_acct.setVisible(need_company)
        self.ip_vendor_acct.setEnabled(need_vendor);   self.ip_vendor_acct.setVisible(need_vendor)
        self.ip_instr_no.setEnabled(need_instr);       self.ip_instr_no.setVisible(need_instr)
        self.ip_instr_date.setEnabled(need_idate);     self.ip_instr_date.setVisible(need_idate)

        m = method
        if m == "Bank Transfer":
            self._ip_instrument_type = "online";        self._ip_clearing_state = "posted"
        elif m == "Cheque":
            self._ip_instrument_type = "cross_cheque";  self._ip_clearing_state = "pending"
        elif m == "Cash Deposit":
            self._ip_instrument_type = "cash_deposit";  self._ip_clearing_state = "pending"
        elif m == "Cash":
            self._ip_instrument_type = "cash";          self._ip_clearing_state = "posted"
        else:  # "Other"
            self._ip_instrument_type = "other";         self._ip_clearing_state = "pending"

    # ---------------- table helpers ----------------
    def _all_products(self):
        return self.products.list_products()

    def _base_uom_id(self, product_id: int) -> int:
        base = self.products.get_base_uom(product_id)
        if base: return int(base["uom_id"])
        u = self.products.list_uoms()
        return int(u[0]["uom_id"]) if u else 1

    def _delete_row_for_button(self, btn: QPushButton):
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 6) is btn:  # column index updated
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
        for p in self._all_products():
            cmb_prod.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.tbl.setCellWidget(r, 1, cmb_prod)

        # Fill editable numeric cells (no discount column now)
        for c in (2, 3, 4):
            it = QTableWidgetItem("0")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, c, it)

        # Line total
        it_total = QTableWidgetItem("0.00")
        it_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_total.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, 5, it_total)

        # Delete button
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
        for c in (2, 3, 4, 5):  # ensure cells exist
            if self.tbl.item(row, c) is None and self.tbl.cellWidget(row, c) is None:
                return
        self._recalc_row(row)
        self._refresh_totals()

    def _recalc_row(self, r: int):
        def num(c):
            it = self.tbl.item(r, c)
            try:
                return float(it.text()) if it and it.text() else 0.0
            except Exception:
                return 0.0

        qty  = num(2)
        buy  = num(3)
        sale = num(4)

        def mark(col, bad):
            it = self.tbl.item(r, col)
            if it:
                it.setBackground(Qt.red if bad else Qt.white)

        bad_buy  = buy <= 0
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
                qty  = float(self.tbl.item(r, 2).text() or 0)
                buy  = float(self.tbl.item(r, 3).text() or 0)
            except Exception:
                continue
            s += max(0.0, qty * buy)
        return s

    def _refresh_totals(self):
        sub = self._calc_subtotal()
        tot = sub  # no order discount
        self.lab_sub.setText(fmt_money(sub))
        self.lab_total.setText(fmt_money(tot))

    # ------------- payload -------------
    def _row_payload(self, r: int) -> dict | None:
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

        qty  = num(2); buy = num(3); sale = num(4)
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
            "item_discount": 0.0,  # kept for compatibility
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
            qty_it  = self.tbl.item(r, 2)
            buy_it  = self.tbl.item(r, 3)
            sale_it = self.tbl.item(r, 4)
            try:
                qty  = float((qty_it.text()  or "0").strip())
                buy  = float((buy_it.text()  or "0").strip())
                sale = float((sale_it.text() or "0").strip())
            except Exception:
                return None
            if qty <= 0 or buy <= 0: return None
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
                "item_discount": 0.0,  # compatibility
            })

        if not rows: return None

        date_str = self.date.date().toString("yyyy-MM-dd")
        total_amount = self._calc_subtotal()  # no order discount

        payload = {
            "vendor_id": vendor_id,
            "date": date_str,
            "order_discount": 0.0,  # kept for compatibility
            "notes": (self.txt_notes.text().strip() or None),
            "items": rows,
            "total_amount": total_amount,
        }

        # ----- Initial Payment payload (unchanged except for new methods) -----
        ip_amount_txt = self.ip_amount.text().strip() if hasattr(self, "ip_amount") else ""
        ip_amount = 0.0
        if ip_amount_txt:
            try: ip_amount = float(ip_amount_txt)
            except Exception: ip_amount = -1

        if ip_amount > 0:
            method = self.ip_method.currentText() if hasattr(self, "ip_method") else ""
            company_id = self.ip_company_acct.currentData() if hasattr(self, "ip_company_acct") else None
            vendor_bank_id = self.ip_vendor_acct.currentData() if hasattr(self, "ip_vendor_acct") else None
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
                instr_type = "cash";          clearing_state = "posted"
                company_id = None;            vendor_bank_id = None
                instr_no = "";                instr_date = date_str
            else:  # "other"
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
            # legacy mirrors
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

    def accept(self):
        p = self.get_payload()
        if p is None: return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload
