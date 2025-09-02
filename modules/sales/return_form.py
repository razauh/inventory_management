from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QLabel,
    QCheckBox, QDialogButtonBox, QDateEdit, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QDate
from ...utils.helpers import today_str, fmt_money
from ...database.repositories.sales_repo import SalesRepo


class SaleReturnForm(QDialog):
    """
    Returned value (after order discount proration):
        returned_value = sum(qty_return * (unit_price - item_discount)) * (total_after_od / net_subtotal)

    Footer shows:
      - Returned Value  (after OD proration)
      - Cash Refund (now) -> operator-entered value, capped at min(Returned Value, Paid)

    Quick mode:
      If constructed with sale_id, the dialog hides the search UI and preloads that sale.
    """
    def __init__(self, parent=None, repo: SalesRepo | None = None, sale_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sale Return")
        self.setModal(True)
        self.repo = repo
        self._initial_sale_id = sale_id

        lay = QVBoxLayout(self)

        # --- search bar (can be hidden in quick mode) ---
        self._search_row = QHBoxLayout()
        self.edt_q = QLineEdit()
        self.edt_q.setPlaceholderText("SO number or customer name…")
        self.edt_date = QDateEdit()
        self.edt_date.setCalendarPopup(True)
        self.edt_date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))
        self.btn_find = QPushButton("Find")
        self._search_row.addWidget(QLabel("Search:"))
        self._search_row.addWidget(self.edt_q, 2)
        self._search_row.addWidget(QLabel("Date:"))
        self._search_row.addWidget(self.edt_date)
        self._search_row.addWidget(self.btn_find)
        lay.addLayout(self._search_row)

        # --- sales results ---
        self.tbl_sales = QTableWidget(0, 5)
        self.tbl_sales.setHorizontalHeaderLabels(["SO", "Date", "Customer", "Total", "Paid"])
        self.tbl_sales.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_sales.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self.tbl_sales, 1)

        # --- items of selected sale ---
        self.tbl_items = QTableWidget(0, 6)
        self.tbl_items.setHorizontalHeaderLabels(["ItemID", "Product", "Qty Sold", "Unit Price", "Qty Return", "Line Refund"])
        self.tbl_items.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_items.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self.tbl_items, 2)

        # --- options (return-all + refund) ---
        opt = QHBoxLayout()
        self.chk_return_all = QCheckBox("Return whole order")
        self.chk_refund = QCheckBox("Refund now?")
        opt.addWidget(self.chk_return_all)
        opt.addWidget(self.chk_refund)
        opt.addStretch(1)

        # footer values
        self.lbl_returned_value = QLabel("0.00")

        # Cash refund (operator editable)
        self.spin_cash = QDoubleSpinBox()
        self.spin_cash.setDecimals(2)
        self.spin_cash.setMinimum(0.0)
        self.spin_cash.setMaximum(0.0)  # set dynamically
        self.spin_cash.setEnabled(False)
        self._cash_user_set = False  # becomes True the first time user edits while enabled

        self.lbl_cash_cap = QLabel("(max: 0.00)")
        self.lbl_cash_cap.setStyleSheet("color:#666;")

        opt.addWidget(QLabel("Returned Value:"))
        opt.addWidget(self.lbl_returned_value)
        opt.addSpacing(16)
        opt.addWidget(QLabel("Cash Refund (now):"))
        opt.addWidget(self.spin_cash)
        opt.addWidget(self.lbl_cash_cap)
        lay.addLayout(opt)

        # helpful note when cap/credit applies
        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet("color:#a22;")
        lay.addWidget(self.lbl_note)

        # --- dialog buttons ---
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        # wiring
        self.btn_find.clicked.connect(self._search)
        self.tbl_sales.itemSelectionChanged.connect(self._load_items)
        self.tbl_items.cellChanged.connect(self._recalc)
        self.chk_return_all.toggled.connect(self._toggle_return_all)
        self.chk_refund.toggled.connect(self._on_refund_toggle)
        self.spin_cash.valueChanged.connect(self._on_cash_changed)

        # window size
        self.resize(960, 620)

        # state
        self._selected_sid: str | None = None
        self._refund_amount: float = 0.0           # returned value AFTER order-discount proration
        self._sale_total_after_od: float = 0.0     # sales.total_amount (after ORDER discount)
        self._sale_paid: float = 0.0               # sales.paid_amount
        self._sale_od: float = 0.0                 # sales.order_discount
        self._sale_net_subtotal: float = 0.0       # Σ qty * (unit_price - item_discount), BEFORE order discount

        # Quick mode: pre-select a sale and skip search UI
        if self._initial_sale_id:
            self._prime_with_sale_id(self._initial_sale_id)

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _is_sale_row(row) -> bool:
        """Best-effort check that the row represents a real sale (not a quotation)."""
        try:
            if isinstance(row, dict):
                dt = row.get("doc_type")
            else:
                # sqlite3.Row supports mapping; .keys() may exist or not, so guard
                dt = row["doc_type"] if "doc_type" in row.keys() else None
            return (dt or "sale") == "sale"
        except Exception:
            # If doc_type is absent, assume it's a sale (legacy behavior),
            # but our search path tries to request doc_type='sale' anyway.
            return True

    # ---- quick-mode priming ----
    def _prime_with_sale_id(self, sid: str):
        if not self.repo:
            return

        # Try repo.search_sales with doc_type filter if supported
        rows = []
        try:
            rows = self.repo.search_sales(query=sid, date=None, doc_type="sale") or []
        except TypeError:
            # Fallback to legacy signature then filter locally
            rows = self.repo.search_sales(query=sid, date=None) or []
            rows = [r for r in rows if self._is_sale_row(r)]

        row = next((r for r in rows if str(r["sale_id"]) == str(sid)), None)

        if not row:
            h = self.repo.get_header(sid)
            if not h or str(h.get("doc_type", "sale")) != "sale":
                return
            row = {
                "sale_id": h["sale_id"],
                "date": h["date"],
                "customer_name": "(customer)",
                "total_amount": float(h["total_amount"] or 0.0),
                "paid_amount": float(h["paid_amount"] or 0.0),
            }

        for i in reversed(range(self._search_row.count())):
            w = self._search_row.itemAt(i).widget()
            if w is not None:
                w.setVisible(False)

        self.setWindowTitle(f"Sale Return — {sid}")

        self.tbl_sales.setRowCount(1)
        self.tbl_sales.setItem(0, 0, QTableWidgetItem(str(row["sale_id"])))
        self.tbl_sales.setItem(0, 1, QTableWidgetItem(row["date"]))
        self.tbl_sales.setItem(0, 2, QTableWidgetItem(row.get("customer_name", "")))
        self.tbl_sales.setItem(0, 3, QTableWidgetItem(fmt_money(row["total_amount"])))
        self.tbl_sales.setItem(0, 4, QTableWidgetItem(fmt_money(row["paid_amount"])))
        self.tbl_sales.selectRow(0)  # triggers _load_items

    # ---- search and load ----
    def _search(self):
        if not self.repo:
            return
        q = (self.edt_q.text() or "").strip()
        d = self.edt_date.date().toString("yyyy-MM-dd") if self.edt_date.date() else None

        # Prefer repo-side doc_type filtering; fallback to local filter
        try:
            rows = self.repo.search_sales(q, d, doc_type="sale")
        except TypeError:
            rows = self.repo.search_sales(q, d)
            rows = [r for r in (rows or []) if self._is_sale_row(r)]

        rows = rows or []
        self.tbl_sales.setRowCount(len(rows))
        for r, x in enumerate(rows):
            self.tbl_sales.setItem(r, 0, QTableWidgetItem(x["sale_id"]))
            self.tbl_sales.setItem(r, 1, QTableWidgetItem(x["date"]))
            self.tbl_sales.setItem(r, 2, QTableWidgetItem(x.get("customer_name", "")))
            self.tbl_sales.setItem(r, 3, QTableWidgetItem(fmt_money(x["total_amount"])))
            self.tbl_sales.setItem(r, 4, QTableWidgetItem(fmt_money(x["paid_amount"])))

    def _load_items(self):
        if not self.repo:
            return
        idxs = self.tbl_sales.selectionModel().selectedRows()
        if not idxs:
            return
        sid = self.tbl_sales.item(idxs[0].row(), 0).text()
        self._selected_sid = sid

        # Header (paid + order discount)
        h = self.repo.get_header(sid) or {}
        # Guard: if somehow a quotation slipped through, do nothing
        if str(h.get("doc_type", "sale")) != "sale":
            return

        self._sale_paid = float(h.get("paid_amount") or 0.0)
        self._sale_od   = float(h.get("order_discount") or 0.0)

        # Canonical totals from DB view (preferred), safe fallback if not present
        totals_ok = False
        try:
            if hasattr(self.repo, "get_sale_totals"):
                t = self.repo.get_sale_totals(sid) or {}
                self._sale_net_subtotal   = float(t.get("net_subtotal") or 0.0)
                self._sale_total_after_od = float(t.get("total_after_od") or 0.0)
                totals_ok = True
        except Exception:
            totals_ok = False

        items = self.repo.list_items(sid)
        if not totals_ok:
            self._sale_total_after_od = float(h.get("total_amount") or 0.0)
            self._sale_net_subtotal = 0.0

        self.tbl_items.blockSignals(True)
        self.tbl_items.setRowCount(len(items))
        for r, it in enumerate(items):
            unit_net = float(it["unit_price"]) - float(it["item_discount"])
            qty_sold = float(it["quantity"])
            if not totals_ok:
                self._sale_net_subtotal += qty_sold * unit_net
            self.tbl_items.setItem(r, 0, QTableWidgetItem(str(it["item_id"])))
            self.tbl_items.setItem(r, 1, QTableWidgetItem(it["product_name"]))
            self.tbl_items.setItem(r, 2, QTableWidgetItem(f'{qty_sold:g}'))
            self.tbl_items.setItem(r, 3, QTableWidgetItem(fmt_money(unit_net)))
            qret = QTableWidgetItem("0"); qret.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_items.setItem(r, 4, qret)
            self.tbl_items.setItem(r, 5, QTableWidgetItem("0.00"))
        self.tbl_items.blockSignals(False)

        # Enable refund-now checkbox when something was paid
        self.chk_refund.setEnabled(self._sale_paid > 0.0)
        # Spinner enabled whenever there is paid>0 (no need to tick first)
        self.spin_cash.setEnabled(self._sale_paid > 0.0)
        if self._sale_paid <= 0.0:
            self.chk_refund.setChecked(False)
            self._cash_user_set = False
            self.spin_cash.blockSignals(True)
            self.spin_cash.setValue(0.0)
            self.spin_cash.blockSignals(False)

        if self.chk_return_all.isChecked():
            self._toggle_return_all(True)

        self._recalc()

    def _toggle_return_all(self, checked: bool):
        if self.tbl_items.rowCount() == 0:
            return
        self.tbl_items.blockSignals(True)
        for r in range(self.tbl_items.rowCount()):
            sold = self.tbl_items.item(r, 2)
            target = self.tbl_items.item(r, 4)
            if sold and target:
                target.setText(sold.text() if checked else "0")
        self.tbl_items.blockSignals(False)
        self._recalc()

    def _on_refund_toggle(self, checked: bool):
        # Spinner stays enabled based on paid>0; just refresh defaults/notes.
        if not checked:
            pass
        self._recalc()

    def _on_cash_changed(self, _=None):
        # If user types a positive value, auto-check "Refund now?"
        if self.spin_cash.isEnabled() and self.spin_cash.value() > 0 and not self.chk_refund.isChecked():
            self.chk_refund.setChecked(True)
        self._cash_user_set = True
        self._update_note()

    # ---- math helpers ----
    def _order_factor(self) -> float:
        if self._sale_net_subtotal <= 0:
            return 1.0
        return float(self._sale_total_after_od) / float(self._sale_net_subtotal)

    # ---- recompute totals ----
    def _recalc(self, *args):
        total = 0.0
        of = self._order_factor()
        for r in range(self.tbl_items.rowCount()):
            try:
                sold = float(self.tbl_items.item(r, 2).text() or 0)
                unit_net = float((self.tbl_items.item(r, 3).text() or "0").replace(",", ""))
                qty = float(self.tbl_items.item(r, 4).text() or 0)
            except Exception:
                continue

            over = qty > sold
            it = self.tbl_items.item(r, 4)
            if it:
                it.setBackground(Qt.red if over else Qt.white)
            if over:
                lt = self.tbl_items.item(r, 5)
                if lt:
                    lt.setText(fmt_money(0.0))
                continue

            line_refund = qty * unit_net * of
            total += line_refund
            lt = self.tbl_items.item(r, 5)
            if lt:
                lt.setText(fmt_money(line_refund))

        # Returned value AFTER order-discount proration
        self._refund_amount = total
        self.lbl_returned_value.setText(fmt_money(self._refund_amount))

        # Cap for cash refund now
        cap = min(self._refund_amount, self._sale_paid)
        self.lbl_cash_cap.setText(f"(max: {fmt_money(cap)})")
        self.spin_cash.setMaximum(max(0.0, cap))

        # Default the spinner if user hasn't edited yet
        self.spin_cash.blockSignals(True)
        if self.spin_cash.isEnabled():
            if not self._cash_user_set:
                self.spin_cash.setValue(cap)
            else:
                if self.spin_cash.value() > cap:
                    self.spin_cash.setValue(cap)
        else:
            self.spin_cash.setValue(0.0)
        self.spin_cash.blockSignals(False)

        self._update_note()

    def _update_note(self):
        cap = min(self._refund_amount, self._sale_paid)
        cash_now = self.spin_cash.value() if self.spin_cash.isEnabled() else 0.0
        if cap <= 0:
            self.lbl_note.setText("")
            return

        if cash_now < cap:
            credited = self._refund_amount - cash_now
            self.lbl_note.setText(
                f"Paying {fmt_money(cash_now)} now. "
                f"{fmt_money(credited)} will reduce balance / be credited."
            )
        elif self._refund_amount > self._sale_paid:
            self.lbl_note.setText(
                f"Note: Paid is {fmt_money(self._sale_paid)}. "
                f"Cash refund is capped at that amount; the remainder will be credited/reduce balance."
            )
        else:
            self.lbl_note.setText("")

    # ---- payload ----
    def get_payload(self):
        if not self._selected_sid:
            return None
        lines = []
        for r in range(self.tbl_items.rowCount()):
            qty = float(self.tbl_items.item(r, 4).text() or 0)
            sold = float(self.tbl_items.item(r, 2).text() or 0)
            if qty <= 0 or qty > sold:
                continue
            lines.append({
                "item_id": int(self.tbl_items.item(r, 0).text()),
                "qty_return": qty
            })
        if not lines:
            return None
        return {
            "sale_id": self._selected_sid,
            "lines": lines,
            # Consider it a "refund now" if either box is checked or a positive cash value is set
            "refund_now": self.chk_refund.isChecked() or (self.spin_cash.isEnabled() and self.spin_cash.value() > 0),
            "refund_amount": self._refund_amount,                 # returned value (after OD proration)
            "cash_refund_now": float(self.spin_cash.value()) if self.spin_cash.isEnabled() else 0.0,
        }

    def accept(self):
        p = self.get_payload()
        if not p:
            return
        self._payload = p
        super().accept()

    def payload(self):
        return getattr(self, "_payload", None)
