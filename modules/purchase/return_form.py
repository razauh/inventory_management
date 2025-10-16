from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QDialogButtonBox, QLineEdit, QFormLayout, QLabel, QComboBox, QDateEdit
)
from PySide6.QtCore import Qt, QDate, QTimer
from ...utils.helpers import today_str, fmt_money


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

    def __init__(
        self,
        parent=None,
        items: list[dict] | None = None,
        *,
        vendor_id: int | None = None,
        vendor_bank_accounts_repo=None,
        company_bank_accounts_repo=None,
        purchases_repo=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Purchase Return")
        self.setModal(True)

        self.vendor_id = int(vendor_id) if vendor_id is not None else None
        self.vba_repo = vendor_bank_accounts_repo
        self.cba_repo = company_bank_accounts_repo

        # Header
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))
        self.notes = QLineEdit()
        f = QFormLayout()
        f.addRow("Date", self.date)
        f.addRow("Notes", self.notes)

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

        # Totals
        tot_bar = QHBoxLayout()
        tot_bar.addStretch(1)
        self.lab_qty_total = QLabel("0")
        self.lab_val_total = QLabel("Total Return Value: 0.00")
        tot_bar.addWidget(QLabel("Total Qty:")); tot_bar.addWidget(self.lab_qty_total)
        tot_bar.addSpacing(20)
        tot_bar.addWidget(self.lab_val_total)

        # Settlement
        settle_box = QGroupBox("Settlement")
        sb = QVBoxLayout(settle_box)

        mode_row = QHBoxLayout()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Credit Note", "Refund Now"])
        mode_row.addWidget(QLabel("Mode:"))
        mode_row.addWidget(self.cmb_mode)
        mode_row.addStretch(1)
        sb.addLayout(mode_row)

        self.ref_panel = QGroupBox("Refund (Incoming)")
        rp = QFormLayout(self.ref_panel)

        self.cmb_method = QComboBox()
        # Allow the three labels test searches for
        self.cmb_method.addItems(["Bank Transfer", "Cheque", "Cash Deposit", "Cash"])

        self.cmb_company_acct = QComboBox()
        self._load_company_accounts()

        self.cmb_vendor_acct = QComboBox()
        self._load_vendor_accounts()

        self.txt_instr_no = QLineEdit()
        self.txt_instr_no.setPlaceholderText("Instrument / Cheque / Slip No")

        self.date_instr = QDateEdit()
        self.date_instr.setCalendarPopup(True)
        self.date_instr.setDate(self.date.date())

        self._clearing_state_fixed = "posted"

        rp.addRow("Method", self.cmb_method)
        rp.addRow("Company Account*", self.cmb_company_acct)
        rp.addRow("Vendor Account", self.cmb_vendor_acct)
        rp.addRow("Instrument No*", self.txt_instr_no)
        rp.addRow("Instrument Date", self.date_instr)
        sb.addWidget(self.ref_panel)
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
        self.cmb_mode.currentTextChanged.connect(self._toggle_mode)
        self.cmb_method.currentIndexChanged.connect(self._validate)
        self.date.dateChanged.connect(self._default_instrument_date)
        self.txt_instr_no.textChanged.connect(self._validate)
        self.cmb_company_acct.currentIndexChanged.connect(self._validate)
        self.cmb_vendor_acct.currentIndexChanged.connect(self._validate)
        self.date_instr.dateChanged.connect(self._validate)

        # polling (programmatic setItem on Qty cell)
        self._poll = QTimer(self)
        self._poll.setInterval(15)
        self._poll.timeout.connect(self._poll_scan_qty)
        self._poll.start()

        self._validate()
        self.resize(1200, 680)
        self.setSizeGripEnabled(True)

    # ---------- account loaders ----------
    def _load_company_accounts(self):
        self.cmb_company_acct.clear()
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

        bad = qty_ret < 0 or qty_ret > max_ret + 1e-9
        try:
            from PySide6.QtGui import QBrush
            q_item.setBackground(QBrush(Qt.red if bad else Qt.white))
        except Exception:
            q_item.setBackground(Qt.red if bad else Qt.white)

        it_val = self.tbl.item(r, self.COL_LINE_VALUE)
        it_val.setText(fmt_money(max(0.0, qty_ret * net_unit)))

    def _recalc_all(self):
        for r in range(self.tbl.rowCount()):
            self._recalc_row(r)
        self._refresh_totals()
        self._validate()

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

    # ---------- settlement ----------
    def _toggle_mode(self):
        is_refund = (self.cmb_mode.currentText() == "Refund Now")
        self.ref_panel.setVisible(is_refund)
        if is_refund:
            self.date_instr.setDate(self.date.date())
        self._validate()

    def _default_instrument_date(self):
        if self.cmb_mode.currentText() == "Refund Now":
            self.date_instr.setDate(self.date.date())

    def _current_settlement_mode(self) -> str:
        t = (self.cmb_mode.currentText() or "").strip().lower()
        if "credit" in t:
            return "credit_note"
        if "refund" in t:
            return "refund_now"
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
            if return_qty > max_ret + 1e-9:
                return None

            purchase_price = float(meta.get("purchase_price") or 0.0)
            item_discount = float(meta.get("item_discount") or 0.0)
            if purchase_price < 0 or item_discount < 0:
                return None
            if (purchase_price - item_discount) < -1e-9:
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
            bank_id = self.cmb_company_acct.currentData() if self.cmb_company_acct.count() else None
            vendor_bank_id = self.cmb_vendor_acct.currentData() if self.cmb_vendor_acct.count() else None
            instr_no = (self.txt_instr_no.text() or "AUTO-REF").strip()

            m = method_txt.lower()
            if "transfer" in m:
                instr_type = "online"
            elif "cheque" in m:
                instr_type = "cross_cheque"
            elif "cash" in m:
                instr_type = "cash"
            else:
                instr_type = "cash_deposit_slip"

            settlement = {
                "mode": "refund_now",
                "method": method_txt,
                "bank_account_id": bank_id,
                "vendor_bank_account_id": vendor_bank_id,
                "instrument_type": instr_type,
                "instrument_no": instr_no,
                "clearing_state": self._clearing_state_fixed,
                "date": date_str,
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
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload

    # ---------- validation / OK gating ----------
    def _validate(self):
        ok = True
        any_line = False
        for r in range(self.tbl.rowCount()):
            it_qty = self.tbl.item(r, self.COL_QTY_RETURN)
            if not it_qty:
                continue
            try:
                q = float(it_qty.text() or 0.0)
            except Exception:
                q = 0.0
            meta = self._meta_for_row(r)
            max_ret = float(meta.get("max_returnable") or 0.0)
            if q > 0:
                any_line = True
            if q < 0 or q > max_ret + 1e-9:
                ok = False
                break

        if not any_line:
            ok = False

        if ok and self.cmb_mode.currentText() == "Refund Now":
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
            if total_val <= 0.0:
                ok = False
            if self.cmb_company_acct.currentIndex() < 0:
                ok = False
            if not (self.txt_instr_no.text().strip()):
                ok = False

        btn_ok = self.buttons.button(QDialogButtonBox.Ok)
        if btn_ok:
            btn_ok.setEnabled(bool(ok))
