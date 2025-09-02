from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QPushButton, QAbstractItemView, QCompleter, QWidget
)
from PySide6.QtCore import Qt, QDate
from ...database.repositories.customers_repo import CustomersRepo
    # (bank account repo is passed in, not imported here)
from ...database.repositories.products_repo import ProductsRepo
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
        bank_accounts=None,  # repo instance providing list_company_bank_accounts(); kept optional, no import here
        initial=None,
        mode: str = "sale",   # <-- NEW: 'sale' | 'quotation'
    ):
        super().__init__(parent)
        self.mode = "quotation" if str(mode).lower() == "quotation" else "sale"
        self.setWindowTitle("Quotation" if self.mode == "quotation" else "Sale")
        self.setModal(True)
        self.customers = customers; self.products = products; self.bank_accounts = bank_accounts
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

        # auto-fill contact for existing selection
        def _fill_contact_from_sel():
            idx = self.cmb_customer.currentIndex()
            if idx >= 0:
                cid = self.cmb_customer.currentData()
                c = self.customers.get(cid)
                if c:
                    self.edt_contact.setText(c.contact_info or "")
        self.cmb_customer.currentIndexChanged.connect(lambda _=None: _fill_contact_from_sel())

        # enable/disable "Add Customer" when new name + contact are provided
        def _update_add_customer_state():
            name = (self.cmb_customer.currentText() or "").strip()
            enable = bool(name) and name.lower() not in self._customers_by_name and bool((self.edt_contact.text() or "").strip())
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
        ib.addWidget(self.tbl, 1)
        add = QHBoxLayout(); self.btn_add_row = QPushButton("Add Row"); add.addWidget(self.btn_add_row); add.addStretch(1); ib.addLayout(add)

        # bottom totals (richer summary)
        tot = QHBoxLayout()
        self.lab_sub_raw   = QLabel("0.00")   # sum(qty * unit_price)
        self.lab_line_disc = QLabel("0.00")   # sum(qty * per-unit discount)
        self.lab_order_disc= QLabel("0.00")   # order discount field value
        self.lab_overall   = QLabel("0.00")   # total discount = line + order
        self.lab_total     = QLabel("0.00")   # sub_raw - overall
        tot.addStretch(1)
        for cap, w in (("Subtotal:", self.lab_sub_raw),
                       ("Line Discount:", self.lab_line_disc),
                       ("Order Discount:", self.lab_order_disc),
                       ("Total Discount:", self.lab_overall),
                       ("Total:", self.lab_total)):
            tot.addWidget(QLabel(cap)); tot.addWidget(w)

        # payment strip (wrapped in a widget so we can hide for quotations)
        self.pay_box = QWidget()
        pay = QHBoxLayout(self.pay_box)
        self.pay_amount = QLineEdit(); self.pay_amount.setPlaceholderText("0")
        self.pay_method = QComboBox(); self.pay_method.addItems(["Cash","Bank Transfer","Card","Cheque","Other"])
        pay.addStretch(1); pay.addWidget(QLabel("Initial Payment:")); pay.addWidget(self.pay_amount)
        pay.addWidget(QLabel("Method:")); pay.addWidget(self.pay_method)

        # --- Bank details strip (visible only when Method == "Bank Transfer") ---
        self.bank_box = QWidget()
        bank_layout = QHBoxLayout(self.bank_box)
        bank_layout.setContentsMargins(0, 0, 0, 0)
        self.cmb_bank_account = QComboBox()
        self.cmb_bank_account.setMinimumWidth(280)
        self.edt_instr_no = QLineEdit(); self.edt_instr_no.setPlaceholderText("Transaction/Reference No.")
        bank_layout.addStretch(1)
        bank_layout.addWidget(QLabel("Bank Account:"))
        bank_layout.addWidget(self.cmb_bank_account)
        bank_layout.addWidget(QLabel("Reference No.:"))
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

        # layout assembly
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Customer*", self.cmb_customer)
        form.addRow("Contact", self.edt_contact)
        form.addRow("", self.btn_add_customer)
        form.addRow("Date*", self.date)
        form.addRow("Order Discount", self.txt_discount)
        form.addRow("Notes", self.txt_notes)
        lay.addLayout(form); lay.addWidget(box, 1); lay.addLayout(tot)

        # Add payment/ bank strips only for 'sale' mode (hidden for quotations)
        lay.addWidget(self.pay_box)
        lay.addWidget(self.bank_box)
        if self.mode == "quotation":
            self.pay_box.setVisible(False)
            self.bank_box.setVisible(False)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject); lay.addWidget(self.buttons)
        self.resize(1200, 600); self.setSizeGripEnabled(True)

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

    # --- helpers ---
    def _toggle_bank_fields(self, text: str):
        # Only relevant in sale mode
        if self.mode != "sale":
            self.bank_box.setVisible(False)
            return
        self.bank_box.setVisible(text == "Bank Transfer")

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

        # product combo (lazy import)
        from PySide6.QtWidgets import QComboBox
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

            # Bank Transfer specifics (only when initial_payment > 0 and method == Bank Transfer)
            if init > 0 and method == "Bank Transfer":
                bank_id = self.cmb_bank_account.currentData()
                instr_no = (self.edt_instr_no.text() or "").strip()

                if bank_id is None:
                    self._warn("Bank Required", "Select a company bank account for Bank Transfer.", self.cmb_bank_account)
                    return None
                if not instr_no:
                    self._warn("Reference Required", "Enter the transaction/reference number for Bank Transfer.", self.edt_instr_no)
                    return None

                payload["initial_bank_account_id"] = int(bank_id)
                payload["initial_instrument_no"] = instr_no
                payload["initial_instrument_type"] = "online"  # fixed per rule

        return payload

    def accept(self):
        p = self.get_payload()
        if p is None:
            return
        self._payload = p; super().accept()

    def payload(self):
        return self._payload
