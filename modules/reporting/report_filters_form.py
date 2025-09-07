# inventory_management/modules/reporting/report_filters_form.py
from __future__ import annotations

import importlib
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from PySide6.QtCore import Qt, QDate, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QLabel, QPushButton, QFrame, QFormLayout, QDateEdit, QComboBox,
    QSpinBox, QFileDialog, QMessageBox, QStackedWidget, QScrollArea, QSizePolicy,
    QTabWidget
)

# ---------- Helpers ----------

def _html_to_pdf(html: str, filepath: str) -> None:
    from PySide6.QtGui import QTextDocument
    from PySide6.QtPrintSupport import QPrinter
    doc = QTextDocument()
    doc.setHtml(html)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(filepath)
    printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)
    doc.print_(printer)

@dataclass
class ReportMeta:
    category: str
    name: str
    module: str
    cls: str
    description: str = ""
    defaults: Dict[str, Any] = field(default_factory=dict)

def _safe_import_widget(module_path: str, class_name: str, conn: sqlite3.Connection) -> QWidget:
    try:
        mod = importlib.import_module(module_path)
        Cls = getattr(mod, class_name)
        return Cls(conn)
    except Exception as e:
        w = QWidget()
        lay = QVBoxLayout(w)
        msg = QLabel(
            f"<b>Report not available</b><br>"
            f"Could not load <code>{module_path}.{class_name}</code>.<br>"
            f"<pre style='white-space:pre-wrap'>{e}</pre>"
        )
        msg.setTextFormat(Qt.RichText)
        msg.setWordWrap(True)
        lay.addWidget(msg)
        return w

def _call_if_has(obj: Any, method: str, *args, **kwargs) -> bool:
    fn = getattr(obj, method, None)
    if callable(fn):
        fn(*args, **kwargs)
        return True
    return False

def _force_refresh_without_recursion(w: Any) -> None:
    """
    Run a report widget's _refresh_impl() once, without letting it recurse into refresh().

    Many report tabs wrap refresh with a decorator that makes _refresh_impl()
    call self.refresh() again. Depending on how it's defined, 'refresh' can exist as:
      - a class method (descriptor), and/or
      - an instance attribute assigned in __init__ (e.g., via a decorator).
    We temporarily replace BOTH with a no-op, then call _refresh_impl(), then restore.
    """
    impl = getattr(w, "_refresh_impl", None)

    if callable(impl):
        cls = w.__class__

        # Save originals (class and instance)
        had_class_refresh = hasattr(cls, "refresh")
        orig_class_refresh = getattr(cls, "refresh", None)

        had_inst_refresh = hasattr(w, "refresh")
        orig_inst_refresh = getattr(w, "refresh", None)

        try:
            # Block any self.refresh() paths
            setattr(cls, "refresh", lambda self, *a, **k: None)
            setattr(w, "refresh", lambda *a, **k: None)

            # Do the real work once
            impl()
        finally:
            # Restore instance first (shadows class attr if present)
            if had_inst_refresh:
                setattr(w, "refresh", orig_inst_refresh)
            else:
                try:
                    delattr(w, "refresh")
                except Exception:
                    pass

            # Restore class
            if had_class_refresh:
                setattr(cls, "refresh", orig_class_refresh)
            else:
                try:
                    delattr(cls, "refresh")
                except Exception:
                    pass
        return

    # Fallback: no _refresh_impl exposed; just call refresh() directly.
    fn = getattr(w, "refresh", None)
    if callable(fn):
        fn()

def _qdate_str(qd: QDate) -> str:
    return qd.toString("yyyy-MM-dd")

# ---------- Registry (current + planned) ----------

_today = QDate.currentDate()
_start_month = QDate(_today.year(), _today.month(), 1).toString("yyyy-MM-dd")
_today_s = _today.toString("yyyy-MM-dd")

REPORTS: List[ReportMeta] = [
    # Already implemented
    ReportMeta("Aging", "Vendor Aging",
               "inventory_management.modules.reporting.vendor_aging_reports", "VendorAgingTab",
               "AP aging summary and open items as of a date.",
               defaults={"as_of": _today_s}),
    ReportMeta("Aging", "Customer Aging",
               "inventory_management.modules.reporting.customer_aging_reports", "CustomerAgingTab",
               "AR aging summary and open items as of a date.",
               defaults={"as_of": _today_s}),
    ReportMeta("Inventory", "Inventory Reports",
               "inventory_management.modules.reporting.inventory_reports", "InventoryReportsTab",
               "Stock on hand, transactions, valuation history."),
    ReportMeta("Expenses", "Expense Reports",
               "inventory_management.modules.reporting.expense_reports", "ExpenseReportsTab",
               "Expense summary by category and detailed expense lines.",
               defaults={"date_from": _start_month, "date_to": _today_s}),
    ReportMeta("Financials", "Income Statement",
               "inventory_management.modules.reporting.financial_reports", "FinancialReportsTab",
               "Accrual P&L (Revenue, COGS via moving avg, Expenses).",
               defaults={"date_from": _start_month, "date_to": _today_s}),

    # Planned (loaders will show a friendly placeholder until implemented)
    ReportMeta("Sales", "Sales Reports",
               "inventory_management.modules.reporting.sales_reports", "SalesReportsTab",
               "Sales summaries, margins, returns, conversion.",
               defaults={"date_from": _start_month, "date_to": _today_s}),
    ReportMeta("Purchases", "Purchase Reports",
               "inventory_management.modules.reporting.purchase_reports", "PurchaseReportsTab",
               "Purchases by vendor/category, price variance, returns.",
               defaults={"date_from": _start_month, "date_to": _today_s}),
    ReportMeta("Payments", "Payment Reports",
               "inventory_management.modules.reporting.payment_reports", "PaymentReportsTab",
               "Bank ledger, clearing aging, collections vs disbursements.",
               defaults={"date_from": _start_month, "date_to": _today_s}),
    ReportMeta("Quotations", "Quotation Reports",
               "inventory_management.modules.reporting.quotation_reports", "QuotationReportsTab",
               "Quotation pipeline, status, conversion funnel.",
               defaults={"date_from": _start_month, "date_to": _today_s}),
]

# ---------- Main widget ----------

class ReportFiltersForm(QWidget):
    """
    Two-tab UX:
      - Tab 1: "Select & Filter" → catalog (left) + large filter form (right)
      - Tab 2: "View Report" → big results area with Back / Refresh / Export

    Apply Filters loads/updates the selected report and auto-switches to tab 2.
    """

    def __init__(self, conn: sqlite3.Connection, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.conn = conn

        self._last_filters: Dict[str, Dict[str, Any]] = {}
        self._item_to_meta: Dict[QTreeWidgetItem, ReportMeta] = {}
        self._key_to_widget: Dict[str, QWidget] = {}
        self._current_meta: Optional[ReportMeta] = None

        self._build_ui()
        self._populate_catalog()

    # ----- UI -----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.tabs = QTabWidget(self)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        # ---- Tab 1: Select & Filter
        t1 = QWidget()
        t1_lay = QVBoxLayout(t1)
        t1_lay.setContentsMargins(0, 0, 0, 0)
        t1_lay.setSpacing(6)

        t1_splitter = QSplitter(Qt.Horizontal, t1)
        t1_splitter.setChildrenCollapsible(False)
        t1_lay.addWidget(t1_splitter, 1)

        # Left: catalog
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search reports…")
        self.search.textChanged.connect(self._on_search_changed)
        left_lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self._on_report_selected)
        left_lay.addWidget(self.tree, 1)

        t1_splitter.addWidget(left)
        t1_splitter.setStretchFactor(0, 0)
        t1_splitter.setSizes([300, 900])

        # Right: filters (spacious)
        filt_frame = QFrame()
        filt_frame.setFrameShape(QFrame.StyledPanel)
        filt_outer = QVBoxLayout(filt_frame)
        filt_outer.setContentsMargins(12, 12, 12, 12)
        filt_outer.setSpacing(10)

        title = QLabel("<b>Filters</b>")
        title.setTextFormat(Qt.RichText)
        filt_outer.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        _minw = 260

        today = QDate.currentDate()
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        self.dt_from.setMinimumWidth(_minw)

        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)
        self.dt_to.setMinimumWidth(_minw)

        self.dt_asof = QDateEdit()
        self.dt_asof.setCalendarPopup(True)
        self.dt_asof.setDisplayFormat("yyyy-MM-dd")
        self.dt_asof.setDate(today)
        self.dt_asof.setMinimumWidth(_minw)

        self.cmb_gran = QComboBox()
        self.cmb_gran.addItems(["daily", "monthly", "yearly"])
        self.cmb_gran.setMinimumWidth(_minw)

        self.inp_customer = QSpinBox()
        self.inp_customer.setMinimum(0); self.inp_customer.setMaximum(10**9)
        self.inp_customer.setSpecialValueText("Any"); self.inp_customer.setValue(0)
        self.inp_customer.setMinimumWidth(_minw)

        self.inp_vendor = QSpinBox()
        self.inp_vendor.setMinimum(0); self.inp_vendor.setMaximum(10**9)
        self.inp_vendor.setSpecialValueText("Any"); self.inp_vendor.setValue(0)
        self.inp_vendor.setMinimumWidth(_minw)

        self.inp_product = QSpinBox()
        self.inp_product.setMinimum(0); self.inp_product.setMaximum(10**9)
        self.inp_product.setSpecialValueText("Any"); self.inp_product.setValue(0)
        self.inp_product.setMinimumWidth(_minw)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Any", userData=None)
        for s in ["draft", "sent", "accepted", "expired", "cancelled", "paid", "unpaid", "partial"]:
            self.cmb_status.addItem(s)
        self.cmb_status.setMinimumWidth(_minw)

        self.inp_query = QLineEdit()
        self.inp_query.setPlaceholderText("Free text…")
        self.inp_query.setMinimumWidth(_minw)

        # group in sections
        form.addRow(QLabel("<b>Date Range</b>"))
        form.addRow("From:", self.dt_from)
        form.addRow("To:", self.dt_to)
        form.addRow("As of:", self.dt_asof)
        form.addRow("Granularity:", self.cmb_gran)

        form.addRow(QLabel("<b>Entities</b>"))
        form.addRow("Customer ID:", self.inp_customer)
        form.addRow("Vendor ID:", self.inp_vendor)
        form.addRow("Product ID:", self.inp_product)

        form.addRow(QLabel("<b>Other</b>"))
        form.addRow("Status:", self.cmb_status)
        form.addRow("Query:", self.inp_query)

        filt_outer.addLayout(form)

        row_btns = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Filters → View Report")
        self.btn_reset = QPushButton("Reset")
        row_btns.addWidget(self.btn_apply)
        row_btns.addWidget(self.btn_reset)
        row_btns.addStretch(1)
        filt_outer.addLayout(row_btns)

        self.btn_apply.clicked.connect(self._apply_filters_and_switch)
        self.btn_reset.clicked.connect(self._reset_filters)

        # scroll (in case of many options later)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(filt_frame)
        sa.setMinimumWidth(500)
        sa.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        t1_splitter.addWidget(sa)
        t1_splitter.setStretchFactor(1, 1)

        self.tabs.addTab(t1, "Select & Filter")

        # ---- Tab 2: View Report
        t2 = QWidget()
        t2_lay = QVBoxLayout(t2)
        t2_lay.setContentsMargins(6, 6, 6, 6)
        t2_lay.setSpacing(6)

        # Top bar
        bar = QHBoxLayout()
        self.lbl_current = QLabel("Report:")
        self.btn_back = QPushButton("← Back to Filters")
        self.btn_back.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        self.btn_refresh = QPushButton("Refresh")
        self.btn_export_pdf = QPushButton("Export PDF…")
        self.btn_export_csv = QPushButton("Export CSV…")

        bar.addWidget(self.lbl_current)
        bar.addStretch(1)
        bar.addWidget(self.btn_back)
        bar.addSpacing(12)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_export_pdf)
        bar.addWidget(self.btn_export_csv)
        t2_lay.addLayout(bar)

        # Host
        self.host = QStackedWidget()
        self.host.addWidget(self._placeholder("(No report loaded)"))
        t2_lay.addWidget(self.host, 1)

        self.btn_refresh.clicked.connect(self._refresh_current)
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        self.btn_export_csv.clicked.connect(self._export_csv)

        self.tabs.addTab(t2, "View Report")

    def _placeholder(self, text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lay.addStretch(1)
        lay.addWidget(lbl, 0, Qt.AlignCenter)
        lay.addStretch(1)
        return w

    # ----- Catalog -----

    def _populate_catalog(self) -> None:
        self.tree.clear()
        cat_to_item: Dict[str, QTreeWidgetItem] = {}
        for meta in REPORTS:
            cat_item = cat_to_item.get(meta.category)
            if cat_item is None:
                cat_item = QTreeWidgetItem([meta.category])
                cat_item.setFirstColumnSpanned(True)
                cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsSelectable)
                self.tree.addTopLevelItem(cat_item)
                cat_to_item[meta.category] = cat_item
            it = QTreeWidgetItem([meta.name])
            it.setToolTip(0, meta.description or f"{meta.module}.{meta.cls}")
            cat_item.addChild(it)
            self._item_to_meta[it] = meta
        self.tree.expandAll()

    @Slot()
    def _on_search_changed(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(cat.childCount()):
                it = cat.child(j)
                meta = self._item_to_meta.get(it)
                visible = True
                if needle:
                    hay = f"{cat.text(0)} {it.text(0)} {(meta.description if meta else '')}".lower()
                    visible = needle in hay
                it.setHidden(not visible)
                any_visible |= visible
            cat.setHidden(not any_visible)

    @Slot()
    def _on_report_selected(self) -> None:
        items = self.tree.selectedItems()
        self._current_meta = self._item_to_meta.get(items[0]) if items else None
        # prefill defaults/last-used on select
        if self._current_meta:
            key = self._key_for(self._current_meta)
            filt = dict(self._current_meta.defaults)
            if key in self._last_filters:
                filt.update(self._last_filters[key])
            self._apply_filters_to_form(filt)

    # ----- Filters -----

    def _collect_filters_from_form(self) -> Dict[str, Any]:
        def _val_or_none(spin: QSpinBox) -> Optional[int]:
            v = spin.value()
            return None if v == 0 else v

        return {
            "date_from": _qdate_str(self.dt_from.date()),
            "date_to": _qdate_str(self.dt_to.date()),
            "as_of": _qdate_str(self.dt_asof.date()),
            "granularity": self.cmb_gran.currentText(),
            "customer_id": _val_or_none(self.inp_customer),
            "vendor_id": _val_or_none(self.inp_vendor),
            "product_id": _val_or_none(self.inp_product),
            "status": (self.cmb_status.currentData() if self.cmb_status.currentData() is not None
                       else (self.cmb_status.currentText() if self.cmb_status.currentText() != "Any" else None)),
            "query": (self.inp_query.text().strip() or None),
        }

    def _apply_filters_to_form(self, filters: Dict[str, Any]) -> None:
        def _set_date(widget: QDateEdit, key: str) -> None:
            val = filters.get(key)
            if isinstance(val, str):
                try:
                    y, m, d = (int(x) for x in val.split("-"))
                    widget.setDate(QDate(y, m, d))
                except Exception:
                    pass

        def _set_spin(spin: QSpinBox, key: str) -> None:
            v = filters.get(key)
            spin.setValue(v if isinstance(v, int) and v > 0 else 0)

        if filters.get("granularity") in ("daily", "monthly", "yearly"):
            self.cmb_gran.setCurrentText(filters["granularity"])

        _set_date(self.dt_from, "date_from")
        _set_date(self.dt_to, "date_to")
        _set_date(self.dt_asof, "as_of")
        _set_spin(self.inp_customer, "customer_id")
        _set_spin(self.inp_vendor, "vendor_id")
        _set_spin(self.inp_product, "product_id")

        status = filters.get("status")
        if status is None:
            self.cmb_status.setCurrentIndex(0)
        else:
            idx = self.cmb_status.findText(str(status))
            if idx >= 0:
                self.cmb_status.setCurrentIndex(idx)
        self.inp_query.setText(filters.get("query") or "")

    @Slot()
    def _reset_filters(self) -> None:
        today = QDate.currentDate()
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        self.dt_to.setDate(today)
        self.dt_asof.setDate(today)
        self.cmb_gran.setCurrentText("monthly")
        self.inp_customer.setValue(0)
        self.inp_vendor.setValue(0)
        self.inp_product.setValue(0)
        self.cmb_status.setCurrentIndex(0)
        self.inp_query.clear()

    # ----- Apply & switch -----

    def _key_for(self, meta: ReportMeta) -> str:
        return f"{meta.module}.{meta.cls}"

    @Slot()
    def _apply_filters_and_switch(self) -> None:
        if not self._current_meta:
            QMessageBox.information(self, "Select report", "Please select a report on the left.")
            return

        meta = self._current_meta
        key = self._key_for(meta)
        filters = self._collect_filters_from_form()
        self._last_filters[key] = dict(filters)

        # load/cache widget
        w = self._key_to_widget.get(key)
        if w is None:
            w = _safe_import_widget(meta.module, meta.cls, self.conn)
            self._key_to_widget[key] = w
            self.host.addWidget(w)

        # set filters + refresh (safe refresh avoids recursion)
        _call_if_has(w, "set_filters", filters)
        _force_refresh_without_recursion(w)

        # update header + switch tab
        self.lbl_current.setText(f"Report: <b>{meta.category} › {meta.name}</b>")
        self.host.setCurrentWidget(w)
        self.tabs.setCurrentIndex(1)

    # ----- Tab 2 actions -----

    @Slot()
    def _refresh_current(self) -> None:
        w = self.host.currentWidget()
        if w:
            _call_if_has(w, "refresh")

    @Slot()
    def _export_pdf(self) -> None:
        w = self.host.currentWidget()
        if w is None:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "report.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        if _call_if_has(w, "export_pdf", fn):
            return
        try:
            html = self._best_effort_html_dump(w)
            _html_to_pdf(html, fn)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    @Slot()
    def _export_csv(self) -> None:
        w = self.host.currentWidget()
        if w is None:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export to CSV", "report.csv", "CSV Files (*.csv)")
        if not fn:
            return
        if _call_if_has(w, "export_csv", fn):
            return
        try:
            import csv
            from PySide6.QtWidgets import QTableView
            tv = w.findChild(QTableView)
            if not tv or not tv.model():
                raise RuntimeError("No table available for CSV export.")
            m = tv.model()
            rows = m.rowCount()
            cols = m.columnCount()
            with open(fn, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                hdr = [m.headerData(c, Qt.Horizontal) for c in range(cols)]
                writer.writerow(hdr)
                for r in range(rows):
                    writer.writerow([m.index(r, c).data(Qt.DisplayRole) for c in range(cols)])
        except Exception as e:
            QMessageBox.warning(self, "Export failed", f"Could not export CSV:\n{e}")

    # ----- HTML dump utility -----

    def _best_effort_html_dump(self, w: QWidget) -> str:
        from PySide6.QtWidgets import QTableView
        tv = w.findChild(QTableView)
        filters = self._collect_filters_from_form() if self._current_meta else {}
        head = [
            "<h2>Report Export</h2>",
            f"<p><b>Report:</b> {self.lbl_current.text()}</p>",
            "<p><b>Filters:</b> "
            + ", ".join(f"{k}={v}" for k, v in filters.items() if v not in (None, "", 0))
            + "</p>",
        ]
        if tv and tv.model():
            m = tv.model()
            cols = m.columnCount()
            rows = m.rowCount()
            parts = ['<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>"]
            for c in range(cols):
                parts.append(f"<th>{m.headerData(c, Qt.Horizontal, Qt.DisplayRole)}</th>")
            parts.append("</tr></thead><tbody>")
            for r in range(rows):
                parts.append("<tr>")
                for c in range(cols):
                    parts.append(f"<td>{m.index(r, c).data(Qt.DisplayRole) or ''}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            return "".join(head + parts)
        return "".join(head + ["<p>(No tabular data available)</p>"])
