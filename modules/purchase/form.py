from PySide6.QtWidgets import (
    QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QDateEdit, QLineEdit, QPushButton, QLabel, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView
)
from PySide6.QtCore import Qt, QDate
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

        # A1) Hide vertical header numbers so “#” only appears once
        self.tbl.verticalHeader().setVisible(False)

        ib.addWidget(self.tbl, 1)
        btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add Row")
        btns.addWidget(self.btn_add_row)
        btns.addStretch(1)
        ib.addLayout(btns)

        # --- Totals & Initial Payment ---
        tot = QHBoxLayout()
        self.lab_sub = QLabel("0.00")
        self.lab_disc = QLabel("0.00")
        self.lab_total = QLabel("0.00")
        tot.addStretch(1)
        tot.addWidget(QLabel("Subtotal:")); tot.addWidget(self.lab_sub)
        tot.addWidget(QLabel("Order Discount:")); tot.addWidget(self.lab_disc)
        tot.addWidget(QLabel("Total:")); tot.addWidget(self.lab_total)

        pay = QHBoxLayout()
        self.pay_amount = QLineEdit(); self.pay_amount.setPlaceholderText("0")
        self.pay_method = QComboBox(); self.pay_method.addItems(["Cash","Bank Transfer","Card","Cheque","Other"])
        pay.addStretch(1)
        pay.addWidget(QLabel("Initial Payment:")); pay.addWidget(self.pay_amount)
        pay.addWidget(QLabel("Method:")); pay.addWidget(self.pay_method)

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
        lay.addLayout(pay)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        # state
        self._rows = []  # internal cache; each row is dict like payload item
        if initial and initial.get("items"):
            self._rows = [dict(x) for x in initial["items"]]

        # wire
        self.btn_add_row.clicked.connect(self._add_row)
        self.tbl.cellChanged.connect(self._cell_changed)
        self.txt_discount.textChanged.connect(self._refresh_totals)

        # prefill
        if initial:
            idx = self.cmb_vendor.findData(initial["vendor_id"])
            if idx >= 0: self.cmb_vendor.setCurrentIndex(idx)
            self.txt_discount.setText(str(initial.get("order_discount", 0) or 0))
            self.txt_notes.setText(initial.get("notes") or "")

        self._rebuild_table()
        self._refresh_totals()

        # size
        self.resize(980, 620)
        self.setSizeGripEnabled(True)

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
        vid = self.cmb_vendor.currentData()
        if not vid: return None
        items = []
        for r in range(self.tbl.rowCount()):
            p = self._row_payload(r)
            if p: items.append(p)
        if not items: return None
        disc = float(self.txt_discount.text()) if self.txt_discount.text().strip() else 0.0
        total = max(0.0, self._calc_subtotal() - disc)
        init_pay = float(self.pay_amount.text()) if self.pay_amount.text().strip() else 0.0
        return {
            "vendor_id": int(vid),
            "date": self.date.date().toString("yyyy-MM-dd"),
            "order_discount": disc,
            "notes": (self.txt_notes.text().strip() or None),
            "items": items,
            "total_amount": total,
            "initial_payment": init_pay,
            "initial_method": self.pay_method.currentText()
        }

    def accept(self):
        p = self.get_payload()
        if p is None: return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload
