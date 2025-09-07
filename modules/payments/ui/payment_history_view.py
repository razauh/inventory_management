from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    # Prefer PySide6 per spec
    from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTabWidget,
        QTableView,
        QVBoxLayout,
        QWidget,
        QHeaderView,
        QPlainTextEdit,
        QAbstractItemView,
        QMessageBox,
    )
except Exception:  # pragma: no cover
    raise


# -----------------------------
# Lightweight helpers
# -----------------------------

def _fmt_money(val: Any) -> str:
    try:
        return f"{float(val):.2f}"
    except Exception:
        return str(val)


def _fmt_or_dash(val: Any) -> str:
    return str(val) if val not in (None, "", []) else "-"


# -----------------------------
# Public API (called by controller)
# -----------------------------

def open_customer_history(customer_id: int, history: dict) -> None:
    """
    Open a read-only window that renders the given customer's
    payments/credit history. Never writes to the DB.
    """
    app = QApplication.instance()
    owns_app = False
    if app is None:
        app = QApplication([])
        owns_app = True
    dlg = _HistoryDialog(customer_id, history)
    dlg.exec()
    if owns_app:
        app.quit()


# -----------------------------
# Simple dict-backed table model
# -----------------------------

class _DictTableModel(QAbstractTableModel):
    """A tiny read-only model mapping rows of dicts into columns via callables.

    columns: Sequence[Tuple[str, callable]] — (header, extractor(row_dict) -> Any)
    rows: Sequence[dict]
    """

    def __init__(self, rows: Sequence[dict], columns: Sequence[Tuple[str, Any]], parent: Optional[QObject] = None):  # type: ignore[name-defined]
        super().__init__(parent)
        self._rows = list(rows)
        self._cols = list(columns)

    # Qt model API
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._cols)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        row = self._rows[index.row()]
        header, extractor = self._cols[index.column()]
        try:
            val = extractor(row)
        except Exception:
            val = None
        return "" if val is None else str(val)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._cols[section][0] if 0 <= section < len(self._cols) else ""
        return str(section + 1)


# -----------------------------
# History dialog (read-only)
# -----------------------------

class _HistoryDialog(QDialog):
    def __init__(self, customer_id: int, history: dict, parent: Optional[QWidget] = None):  # type: ignore[override]
        super().__init__(parent)
        self.setWindowTitle(f"Payment & Credit History — Customer #{customer_id}")
        self.setModal(True)
        self._cid = customer_id
        self._h = history or {}
        self._build_ui()
        self._populate()

    # ---------- UI skeleton ----------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # --- Overview cards (simple grid-like row) ---
        header_row = QHBoxLayout()
        self.salesCountVal = QLabel("0")
        self.openDueVal = QLabel("0.00")
        self.creditBalVal = QLabel("0.00")
        self.lastDatesVal = QLabel("-")

        def make_card(title: str, value_widget: QWidget) -> QWidget:
            box = QVBoxLayout()
            lbl = QLabel(title)
            lbl.setStyleSheet("color:#666;")
            valw = value_widget
            valw.setStyleSheet("font-weight:600;")
            w = QWidget(); w.setLayout(box)
            box.addWidget(lbl)
            box.addWidget(valw)
            return w

        header_row.addWidget(make_card("Sales Count", self.salesCountVal))
        header_row.addWidget(make_card("Open Receivables", self.openDueVal))
        header_row.addWidget(make_card("Credit Balance", self.creditBalVal))
        header_row.addWidget(make_card("Last Activity", self.lastDatesVal))
        header_w = QWidget(); header_w.setLayout(header_row)
        outer.addWidget(header_w)

        # --- Tabs ---
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Timeline tab
        self.timelineTable = self._make_table()
        self.timelineEmpty = QLabel("No financial activity for this customer yet.")
        self.timelineEmpty.setAlignment(Qt.AlignCenter)
        self.timelineTab = self._wrap_table_with_empty(self.timelineTable, self.timelineEmpty)
        self.tabs.addTab(self.timelineTab, "Timeline")

        # Sales tab (master table + details)
        self.salesTable = self._make_table()
        self.salesEmpty = QLabel("No sales.")
        self.salesEmpty.setAlignment(Qt.AlignCenter)
        self.salesItemsTable = self._make_table()
        salesLayout = QVBoxLayout()
        salesLayout.addWidget(self.salesTable, 3)
        salesLayout.addWidget(QLabel("Items"))
        salesLayout.addWidget(self.salesItemsTable, 2)
        self.salesTab = QWidget(); self.salesTab.setLayout(salesLayout)
        self.tabs.addTab(self._wrap_with_empty(self.salesTab, self.salesEmpty), "Sales")

        # Receipts tab
        self.receiptsTable = self._make_table()
        self.receiptsEmpty = QLabel("No receipts.")
        self.receiptsEmpty.setAlignment(Qt.AlignCenter)
        self.receiptsTab = self._wrap_table_with_empty(self.receiptsTable, self.receiptsEmpty)
        self.tabs.addTab(self.receiptsTab, "Receipts")

        # Advances tab
        advLayout = QVBoxLayout()
        self.advBalanceLabel = QLabel("Current Credit Balance: 0.00")
        advLayout.addWidget(self.advBalanceLabel)
        self.advTable = self._make_table()
        self.advEmpty = QLabel("No deposits/credit entries.")
        self.advEmpty.setAlignment(Qt.AlignCenter)
        self.advTabInner = self._wrap_table_with_empty(self.advTable, self.advEmpty)
        advLayout.addWidget(self.advTabInner, 1)
        self.advTab = QWidget(); self.advTab.setLayout(advLayout)
        self.tabs.addTab(self.advTab, "Advances")

        # Developer JSON tab (hidden toggle)
        self.devJson = QPlainTextEdit(); self.devJson.setReadOnly(True)
        self.devTab = QWidget(); v = QVBoxLayout(); v.addWidget(self.devJson); self.devTab.setLayout(v)
        self._dev_tab_index: Optional[int] = None  # created lazily

        # --- Footer ---
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.devToggle = QCheckBox("Developer View")
        self.devToggle.toggled.connect(self._toggle_dev_tab)
        footer.addWidget(self.devToggle)

        self.copyBtn = QPushButton("Copy snapshot")
        self.copyBtn.clicked.connect(self._copy_snapshot)
        footer.addWidget(self.copyBtn)

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttonBox.rejected.connect(self.reject)
        self.buttonBox.accepted.connect(self.accept)
        footer.addWidget(self.buttonBox)
        outer.addLayout(footer)

        # ESC closes
        self.buttonBox.button(QDialogButtonBox.Close).setShortcut(QKeySequence("Esc"))

    def _make_table(self) -> QTableView:
        tv = QTableView()
        tv.setSortingEnabled(True)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        return tv

    def _wrap_table_with_empty(self, table: QTableView, empty_label: QLabel) -> QWidget:
        w = QWidget(); v = QVBoxLayout(); w.setLayout(v)
        v.addWidget(table)
        v.addWidget(empty_label)
        empty_label.setVisible(False)
        return w

    def _wrap_with_empty(self, inner: QWidget, empty_label: QLabel) -> QWidget:
        w = QWidget(); v = QVBoxLayout(); w.setLayout(v)
        v.addWidget(inner)
        v.addWidget(empty_label)
        empty_label.setVisible(False)
        return w

    # ---------- Populate UI from history ----------
    def _populate(self) -> None:
        h = self._h or {}

        # Summary
        summary = h.get("summary", {}) or {}
        self.salesCountVal.setText(str(summary.get("sales_count", 0)))
        self.openDueVal.setText(_fmt_money(summary.get("open_due_sum", 0.0)))
        self.creditBalVal.setText(_fmt_money(summary.get("credit_balance", 0.0)))
        last = f"sale={_fmt_or_dash(summary.get('last_sale_date'))}  |  " \
               f"payment={_fmt_or_dash(summary.get('last_payment_date'))}  |  " \
               f"advance={_fmt_or_dash(summary.get('last_advance_date'))}"
        self.lastDatesVal.setText(last)

        # Timeline
        timeline_rows = h.get("timeline", []) or []
        tl_cols: List[Tuple[str, Any]] = [
            ("Date", lambda r: r.get("date") or r.get("tx_date") or ""),
            ("Kind", lambda r: r.get("kind", "")),
            ("Reference", self._timeline_ref),
            ("Amount", lambda r: _fmt_money(r.get("amount"))),
            ("Remaining Due", lambda r: _fmt_money(r.get("remaining_due")) if r.get("kind") == "sale" and r.get("remaining_due") is not None else ""),
        ]
        self._bind_table(self.timelineTable, timeline_rows, tl_cols, self.timelineEmpty)

        # Sales master
        sales_rows = h.get("sales", []) or []
        sales_cols: List[Tuple[str, Any]] = [
            ("Sale#", lambda r: r.get("sale_id")),
            ("Date", lambda r: r.get("date")),
            ("Total (header)", lambda r: _fmt_money(r.get("total_amount"))),
            ("Total (calc)", lambda r: _fmt_money(r.get("calculated_total_amount"))),
            ("Paid", lambda r: _fmt_money(r.get("paid_amount"))),
            ("Advance Applied", lambda r: _fmt_money(r.get("advance_payment_applied"))),
            ("Remaining Due", lambda r: _fmt_money(r.get("remaining_due"))),
            ("Status", lambda r: r.get("payment_status")),
            ("Δ header-calc", lambda r: _fmt_money(r.get("header_vs_calc_delta"))),
        ]
        self._bind_table(self.salesTable, sales_rows, sales_cols, self.salesEmpty)
        # Sales details (items) follow selection
        self.salesTable.selectionModel().selectionChanged.connect(self._on_sale_selection_changed)  # type: ignore[attr-defined]

        # Receipts
        pay_rows = h.get("payments", []) or []
        pay_cols: List[Tuple[str, Any]] = [
            ("Payment#", lambda r: r.get("payment_id")),
            ("Date", lambda r: r.get("date")),
            ("Sale#", lambda r: r.get("sale_id")),
            ("Amount", lambda r: _fmt_money(r.get("amount"))),
            ("Method", lambda r: r.get("method")),
            ("Clearing State", lambda r: r.get("clearing_state")),
            ("Cleared Date", lambda r: r.get("cleared_date")),
            ("Bank Account", lambda r: r.get("bank_account_id")),
            ("Instrument Type", lambda r: r.get("instrument_type")),
            ("Instrument No", lambda r: r.get("instrument_no")),
            ("Instrument Date", lambda r: r.get("instrument_date")),
            ("Deposited Date", lambda r: r.get("deposited_date")),
            ("Ref", lambda r: r.get("ref_no")),
            ("Notes", lambda r: r.get("notes")),
            ("Created By", lambda r: r.get("created_by")),
        ]
        self._bind_table(self.receiptsTable, pay_rows, pay_cols, self.receiptsEmpty)

        # Advances
        adv = h.get("advances", {}) or {}
        balance = adv.get("balance", 0.0)
        self.advBalanceLabel.setText(f"Current Credit Balance: {_fmt_money(balance)}")
        adv_rows = adv.get("entries", []) or []
        adv_cols: List[Tuple[str, Any]] = [
            ("Tx#", lambda r: r.get("tx_id")),
            ("Date", lambda r: r.get("tx_date")),
            ("Amount", lambda r: _fmt_money(r.get("amount"))),
            ("Type", lambda r: r.get("source_type")),
            ("Linked Sale", lambda r: r.get("source_id")),
            ("Notes", lambda r: r.get("notes")),
            ("Created By", lambda r: r.get("created_by")),
        ]
        self._bind_table(self.advTable, adv_rows, adv_cols, self.advEmpty)

        # Dev JSON (not shown until toggled)
        try:
            self.devJson.setPlainText(json.dumps(self._h, indent=2))
        except Exception:
            self.devJson.setPlainText(str(self._h))

    # ---------- Bind helpers ----------
    def _bind_table(self, tv: QTableView, rows: Sequence[dict], cols: Sequence[Tuple[str, Any]], empty_label: QLabel) -> None:
        model = _DictTableModel(rows, cols, tv)
        tv.setModel(model)
        empty_label.setVisible(len(rows) == 0)

    # ---------- Reactions ----------
    def _on_sale_selection_changed(self):
        indexes = self.salesTable.selectionModel().selectedRows()
        if not indexes:
            self.salesItemsTable.setModel(_DictTableModel([], [], self.salesItemsTable))
            return
        row_idx = indexes[0].row()
        sales_model: _DictTableModel = self.salesTable.model()  # type: ignore[assignment]
        # Pull source dict from model
        sale_dict = self._h.get("sales", [])[row_idx] if 0 <= row_idx < len(self._h.get("sales", [])) else {}
        items = sale_dict.get("items", []) or []
        item_cols: List[Tuple[str, Any]] = []
        # Build columns dynamically from first item keys for flexibility
        if items:
            keys = list(items[0].keys())
            # Prefer a conventional order if present
            preferred = ["product_id", "name", "quantity", "uom_id", "unit_price", "item_discount", "line_total"]
            ordered = [k for k in preferred if k in keys] + [k for k in keys if k not in preferred]
            for k in ordered:
                item_cols.append((k, lambda r, kk=k: r.get(kk)))
        self._bind_table(self.salesItemsTable, items, item_cols, QLabel(""))

    # ---------- Timeline helpers ----------
    def _timeline_ref(self, r: dict) -> str:
        kind = r.get("kind")
        if kind == "sale":
            sid = r.get("sale_id") or r.get("id")
            return f"Sale {sid}" if sid is not None else "Sale"
        if kind == "receipt":
            sid = r.get("sale_id"); pid = r.get("payment_id")
            ref = []
            if sid is not None:
                ref.append(f"Sale {sid}")
            if pid is not None:
                ref.append(f"Payment {pid}")
            return " / ".join(ref) if ref else "Receipt"
        if kind == "advance":
            tx = r.get("tx_id")
            return f"Advance {tx}" if tx is not None else "Advance"
        if kind == "advance_applied":
            tx = r.get("tx_id"); src = r.get("source_id")
            ref = []
            if tx is not None:
                ref.append(f"Tx {tx}")
            if src is not None:
                ref.append(f"Sale {src}")
            return " → ".join(ref) if ref else "Advance Applied"
        return _fmt_or_dash(r.get("reference"))

    # ---------- Developer tab toggle ----------
    def _toggle_dev_tab(self, checked: bool) -> None:
        if checked and self._dev_tab_index is None:
            self._dev_tab_index = self.tabs.addTab(self.devTab, "Summary JSON")
            self.tabs.setCurrentIndex(self._dev_tab_index)
        elif not checked and self._dev_tab_index is not None:
            idx = self._dev_tab_index
            self._dev_tab_index = None
            self.tabs.removeTab(idx)

    # ---------- Copy snapshot ----------
    def _copy_snapshot(self) -> None:
        s = []
        summary = self._h.get("summary", {}) or {}
        s.append(f"Customer #{self._cid}")
        s.append(
            f"Sales count: {summary.get('sales_count', 0)} | "
            f"Open due: {_fmt_money(summary.get('open_due_sum', 0.0))} | "
            f"Credit: {_fmt_money(summary.get('credit_balance', 0.0))}"
        )
        s.append(
            f"Last: sale={_fmt_or_dash(summary.get('last_sale_date'))} "
            f"payment={_fmt_or_dash(summary.get('last_payment_date'))} "
            f"advance={_fmt_or_dash(summary.get('last_advance_date'))}"
        )
        s.append("")
        s.append("Recent timeline:")
        timeline_rows = list(self._h.get("timeline", []) or [])[-10:]
        for r in timeline_rows:
            date = r.get("date") or r.get("tx_date")
            kind = r.get("kind")
            ref = self._timeline_ref(r)
            amt = _fmt_money(r.get("amount"))
            extra = ""
            if kind == "sale" and r.get("remaining_due") is not None:
                extra = f", remaining_due={_fmt_money(r.get('remaining_due'))}"
            s.append(f"{date} {kind} {ref} amount={amt}{extra}")
        QApplication.clipboard().setText("\n".join(s))

