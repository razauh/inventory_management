# inventory_management/modules/reporting/sales_reports.py
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QPushButton, QComboBox,
    QTabWidget, QSplitter, QTableView, QCheckBox, QListWidget, QListWidgetItem,
    QFormLayout, QFrame, QSpinBox, QAbstractItemView, QMessageBox
)

# Use app’s TableView if available
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

# Money formatting helper (reuse app helper if present)
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"

from ...database.repositories.reporting_repo import ReportingRepo


# ---------------------------------------------------------------------------
# Simple generic table model (dynamic columns)
# ---------------------------------------------------------------------------

from PySide6.QtCore import QAbstractTableModel

class _SimpleTableModel(QAbstractTableModel):
    """
    Minimal, flexible table model.

    headers: list[str]
    rows: list[dict] (keys should align with field_map)
    field_map: list[str] mapping column index -> dict key
    money_cols: set[int] columns to format as money
    right_cols: set[int] columns to right-align (numbers)
    """
    def __init__(self,
                 headers: List[str],
                 field_map: List[str],
                 rows: Optional[List[Dict[str, Any]]] = None,
                 money_cols: Optional[Sequence[int]] = None,
                 right_cols: Optional[Sequence[int]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._headers = headers
        self._field_map = field_map
        self._rows: List[Dict[str, Any]] = rows or []
        self._money_cols = set(money_cols or [])
        self._right_cols = set(right_cols or [])

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    # Qt API
    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._headers[section]
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        row = self._rows[r]
        key = self._field_map[c]

        if role == Qt.DisplayRole:
            val = row.get(key)
            if c in self._money_cols:
                return fmt_money(val)
            # Percent columns convention: if header endswith '%', format float as pct with 1 decimal
            if isinstance(val, float) and self._headers[c].endswith('%'):
                try:
                    return f"{val:.1%}"
                except Exception:
                    return "0.0%"
            return "" if val is None else str(val)

        if role == Qt.TextAlignmentRole:
            if c in self._right_cols or c in self._money_cols:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None


# ---------------------------------------------------------------------------
# Main Sales Reports Tab
# ---------------------------------------------------------------------------

class SalesReportsTab(QWidget):
    """
    Sales Reports with common filters and multiple sub-tabs.

    Sub-tabs:
      1) Sales by Day (granularity daily/monthly/yearly)
      2) Sales by Customer
      3) Sales by Product
      4) Sales by Category
      5) Margin by Day
      6) Margin by Customer
      7) Margin by Product
      8) Margin by Category
      9) Top Customers
     10) Top Products
     11) Returns Summary
     12) Status Breakdown
     13) Drill-down (matching sales list)

    IMPORTANT — Repo requirements (to be added in reporting_repo.py):
      - get_product_categories() -> list[str]
      - sales_by_period(date_from, date_to, granularity, statuses, customer_id, product_id, category) -> rows[{period, revenue, order_count}]
      - sales_by_customer(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{customer_id, customer_name, revenue, order_count}]
      - sales_by_product(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{product_id, product_name, qty_base, revenue}]
      - sales_by_category(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{category, qty_base, revenue}]
      - margin_by_period(date_from, date_to, granularity, statuses, customer_id, product_id, category) -> rows[{period, revenue, cogs, gross, margin_pct}]
      - margin_by_customer(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{customer_id, customer_name, revenue, cogs, gross, margin_pct}]
      - margin_by_product(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{product_id, product_name, revenue, cogs, gross, margin_pct}]
      - margin_by_category(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{category, revenue, cogs, gross, margin_pct}]
      - top_customers(date_from, date_to, statuses, limit_n) -> rows[{customer_id, customer_name, revenue, order_count}]
      - top_products(date_from, date_to, statuses, limit_n) -> rows[{product_id, product_name, qty_base, revenue}]
      - returns_summary(date_from, date_to) -> rows[{metric, value}]  (should at least return refunds_sum (negative payments) and returns_qty_base)
      - status_breakdown(date_from, date_to, customer_id, product_id, category) -> rows[{payment_status, order_count, revenue}]
      - drilldown_sales(date_from, date_to, statuses, customer_id, product_id, category) -> rows[{sale_id, date, customer_name, total_amount, paid_amount, advance_payment_applied, remaining, payment_status}]

    This widget will handle “status multiselect”, category dropdown, and date range.
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)

        self._build_ui()
        self._wire()
        self._load_categories()
        self.refresh()  # initial load

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Filter bar (top)
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        fl = QFormLayout(bar)
        fl.setLabelAlignment(Qt.AlignRight)
        fl.setFormAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        today = QDate.currentDate()
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))

        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)

        self.cmb_gran = QComboBox()
        self.cmb_gran.addItems(["daily", "monthly", "yearly"])
        self.cmb_gran.setCurrentText("daily")

        # Customer / Product ids as ints (you asked not to assume names in filter)
        self.spn_customer = QSpinBox()
        self.spn_customer.setMinimum(0)
        self.spn_customer.setMaximum(10**9)
        self.spn_customer.setSpecialValueText("Any")
        self.spn_customer.setValue(0)

        self.spn_product = QSpinBox()
        self.spn_product.setMinimum(0)
        self.spn_product.setMaximum(10**9)
        self.spn_product.setSpecialValueText("Any")
        self.spn_product.setValue(0)

        # Category dropdown from products.category distinct
        self.cmb_category = QComboBox()
        self.cmb_category.addItem("Any", userData=None)  # populated later

        # Status multi-select (paid/unpaid/partial)
        self.lst_status = QListWidget()
        self.lst_status.setSelectionMode(QAbstractItemView.MultiSelection)
        for s in ("paid", "unpaid", "partial"):
            item = QListWidgetItem(s)
            item.setSelected(True)  # default: include all
            self.lst_status.addItem(item)
        self.lst_status.setMaximumHeight(70)

        self.chk_include_returns = QCheckBox("Include returns impact (if repo supports it)")

        self.spn_topn = QSpinBox()
        self.spn_topn.setRange(1, 1000)
        self.spn_topn.setValue(10)

        self.btn_apply = QPushButton("Apply")
        self.btn_export_pdf = QPushButton("Export PDF…")
        self.btn_export_csv = QPushButton("Export CSV…")

        fl.addRow(QLabel("<b>Date Range</b>"))
        fl.addRow("From:", self.dt_from)
        fl.addRow("To:", self.dt_to)
        fl.addRow("Granularity:", self.cmb_gran)
        fl.addRow(QLabel("<b>Filters</b>"))
        fl.addRow("Customer ID:", self.spn_customer)
        fl.addRow("Product ID:", self.spn_product)
        fl.addRow("Category:", self.cmb_category)
        fl.addRow("Status:", self.lst_status)
        fl.addRow(self.chk_include_returns)
        fl.addRow(QLabel("<b>Top N</b>"))
        fl.addRow("N:", self.spn_topn)
        rowb = QHBoxLayout()
        rowb.addWidget(self.btn_apply)
        rowb.addStretch(1)
        rowb.addWidget(self.btn_export_pdf)
        rowb.addWidget(self.btn_export_csv)
        fl.addRow(rowb)

        root.addWidget(bar)

        # Tabs with results
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # Create all result tables
        self._tables: Dict[str, _BaseTableView] = {}

        def _add_tab(key: str, title: str, headers: List[str], fields: List[str],
                     money_cols: Sequence[int] = (), right_cols: Sequence[int] = ()) -> None:
            tv = _BaseTableView()
            tv.setSelectionBehavior(QTableView.SelectRows)
            tv.setSelectionMode(QTableView.SingleSelection)
            tv.setSortingEnabled(True)
            model = _SimpleTableModel(headers, fields, [], money_cols=money_cols, right_cols=right_cols, parent=tv)
            tv.setModel(model)
            self._tables[key] = tv
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(tv)
            self.tabs.addTab(page, title)

        # 1) Sales by Day
        _add_tab("sales_by_day", "Sales by Day",
                 ["Period", "Orders", "Revenue"],
                 ["period", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))

        # 2) Sales by Customer
        _add_tab("sales_by_customer", "Sales by Customer",
                 ["Customer", "Orders", "Revenue", "COGS", "Gross", "Gross %"],
                 ["customer_name", "order_count", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))

        # 3) Sales by Product
        _add_tab("sales_by_product", "Sales by Product",
                 ["Product", "Qty (base)", "Revenue", "COGS", "Gross", "Gross %"],
                 ["product_name", "qty_base", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))

        # 4) Sales by Category
        _add_tab("sales_by_category", "Sales by Category",
                 ["Category", "Qty (base)", "Revenue", "COGS", "Gross", "Gross %"],
                 ["category", "qty_base", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))

        # 5) Margin by Day
        _add_tab("margin_by_day", "Margin by Day",
                 ["Period", "Revenue", "COGS", "Gross", "Gross %"],
                 ["period", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))

        # 6) Margin by Customer
        _add_tab("margin_by_customer", "Margin by Customer",
                 ["Customer", "Revenue", "COGS", "Gross", "Gross %"],
                 ["customer_name", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))

        # 7) Margin by Product
        _add_tab("margin_by_product", "Margin by Product",
                 ["Product", "Revenue", "COGS", "Gross", "Gross %"],
                 ["product_name", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))

        # 8) Margin by Category
        _add_tab("margin_by_category", "Margin by Category",
                 ["Category", "Revenue", "COGS", "Gross", "Gross %"],
                 ["category", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))

        # 9) Top Customers
        _add_tab("top_customers", "Top Customers",
                 ["Customer", "Orders", "Revenue"],
                 ["customer_name", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))

        # 10) Top Products
        _add_tab("top_products", "Top Products",
                 ["Product", "Qty (base)", "Revenue"],
                 ["product_name", "qty_base", "revenue"],
                 money_cols=(2,), right_cols=(1,))

        # 11) Returns Summary
        _add_tab("returns_summary", "Returns Summary",
                 ["Metric", "Value"],
                 ["metric", "value"],
                 money_cols=(), right_cols=(1,))

        # 12) Status Breakdown
        _add_tab("status_breakdown", "Status Breakdown",
                 ["Status", "Orders", "Revenue"],
                 ["payment_status", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))

        # 13) Drill-down Sales
        _add_tab("drilldown", "Drill-down Sales",
                 ["Sale ID", "Date", "Customer", "Status", "Total", "Paid", "Advance Applied", "Remaining"],
                 ["sale_id", "date", "customer_name", "payment_status", "total_amount", "paid_amount", "advance_payment_applied", "remaining"],
                 money_cols=(4, 5, 6, 7), right_cols=())

    def _wire(self) -> None:
        self.btn_apply.clicked.connect(self.refresh)
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        self.btn_export_csv.clicked.connect(self._export_csv)

    # -------------- Filters helpers --------------

    def _statuses(self) -> List[str]:
        out: List[str] = []
        for i in range(self.lst_status.count()):
            it = self.lst_status.item(i)
            if it.isSelected():
                out.append(it.text())
        return out

    def _customer_id(self) -> Optional[int]:
        v = self.spn_customer.value()
        return None if v == 0 else v

    def _product_id(self) -> Optional[int]:
        v = self.spn_product.value()
        return None if v == 0 else v

    def _category_value(self) -> Optional[str]:
        ud = self.cmb_category.currentData()
        if ud is None:
            return None
        return str(ud) if ud != "" else None

    # -------------- Data loading --------------

    def _load_categories(self) -> None:
        """Populate category dropdown from repo (distinct products.category)."""
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("Any", userData=None)
        try:
            rows = getattr(self.repo, "get_product_categories")()
            for r in rows:
                # accept either a row with 'category' or a plain string
                if isinstance(r, (tuple, list)) and r:
                    cat = r[0]
                elif hasattr(r, "keys") and "category" in r.keys():  # sqlite3.Row
                    cat = r["category"]
                else:
                    cat = r
                if cat is None or str(cat).strip() == "":
                    continue
                self.cmb_category.addItem(str(cat), userData=str(cat))
        except Exception:
            # if repo method missing, just keep "Any"
            pass
        self.cmb_category.blockSignals(False)

    # -------------- Refresh dispatcher --------------

    @Slot()
    def refresh(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        gran = self.cmb_gran.currentText()
        statuses = self._statuses() or ["paid", "unpaid", "partial"]
        customer_id = self._customer_id()
        product_id = self._product_id()
        category = self._category_value()
        top_n = int(self.spn_topn.value())
        include_returns = self.chk_include_returns.isChecked()

        # Helper to set a table safely from repo method
        def load_into(key: str, repo_method: str, *args) -> None:
            tv = self._tables[key]
            model: _SimpleTableModel = tv.model()  # type: ignore
            try:
                fn = getattr(self.repo, repo_method)
            except AttributeError:
                model.set_rows([{"metric": "Info", "value": f"Repo method '{repo_method}' not implemented."}] if key == "returns_summary" else [])
                return
            try:
                rows = fn(*args)
            except Exception as e:
                # Show error as a single row for visibility
                model.set_rows([{"metric": "Error", "value": str(e)}] if key == "returns_summary" else [])
                return

            # Normalize rows (sqlite3.Row -> dict)
            out: List[Dict[str, Any]] = []
            for r in rows or []:
                if hasattr(r, "keys"):
                    out.append({k: r[k] for k in r.keys()})
                else:
                    out.append(dict(r))
            # Derived fields
            if key == "sales_by_product" and out:
                for row in out:
                    # ensure numeric display
                    for k in ("qty_base", "revenue", "cogs", "gross", "margin_pct"):
                        row[k] = row.get(k, 0.0)
            if key == "sales_by_category" and out:
                for row in out:
                    for k in ("qty_base", "revenue", "cogs", "gross", "margin_pct"):
                        row[k] = row.get(k, 0.0)
            if key.startswith("margin_") and out:
                for row in out:
                    rev = float(row.get("revenue") or 0.0)
                    cogs = float(row.get("cogs") or 0.0)
                    row["gross"] = row.get("gross", rev - cogs)
                    row["margin_pct"] = (row["gross"] / rev) if rev else 0.0
            if key == "drilldown" and out:
                for row in out:
                    total = float(row.get("total_amount") or 0.0)
                    paid = float(row.get("paid_amount") or 0.0)
                    adv = float(row.get("advance_payment_applied") or 0.0)
                    row["remaining"] = total - paid - adv

            model.set_rows(out)
            tv.resizeColumnsToContents()
            tv.horizontalHeader().setStretchLastSection(True)

        # Load each tab
        load_into("sales_by_day", "sales_by_period",
                  date_from, date_to, gran, statuses, customer_id, product_id, category)

        load_into("sales_by_customer", "sales_by_customer",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("sales_by_product", "sales_by_product",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("sales_by_category", "sales_by_category",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("margin_by_day", "margin_by_period",
                  date_from, date_to, gran, statuses, customer_id, product_id, category)

        load_into("margin_by_customer", "margin_by_customer",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("margin_by_product", "margin_by_product",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("margin_by_category", "margin_by_category",
                  date_from, date_to, statuses, customer_id, product_id, category)

        load_into("top_customers", "top_customers",
                  date_from, date_to, statuses, int(top_n))

        load_into("top_products", "top_products",
                  date_from, date_to, statuses, int(top_n))

        # Returns: only date range (repo decides details)
        # If include_returns is OFF, we still show the summary but repos can return zeros.
        try:
            fn = getattr(self.repo, "returns_summary")
            rows = fn(date_from, date_to)  # must return rows [{metric,value}, ...]
        except Exception:
            rows = [{"metric": "Info", "value": "Repo.returns_summary not implemented"}]
        model_rs: _SimpleTableModel = self._tables["returns_summary"].model()  # type: ignore
        model_rs.set_rows([dict(r) if hasattr(r, "keys") else dict(r) for r in rows or []])
        self._tables["returns_summary"].resizeColumnsToContents()
        self._tables["returns_summary"].horizontalHeader().setStretchLastSection(True)

        load_into("status_breakdown", "status_breakdown",
                  date_from, date_to, customer_id, product_id, category)

        load_into("drilldown", "drilldown_sales",
                  date_from, date_to, statuses, customer_id, product_id, category)

    # -------------- Export helpers --------------

    def _active_table(self) -> Optional[_BaseTableView]:
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None
        # find the QTableView in this page
        page = self.tabs.currentWidget()
        if not page:
            return None
        return page.findChild(_BaseTableView)

    def _export_pdf(self) -> None:
        tv = self._active_table()
        if not tv:
            QMessageBox.information(self, "Export PDF", "No table to export.")
            return
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter
        m: _SimpleTableModel = tv.model()  # type: ignore
        cols = m.columnCount()
        rows = m.rowCount()
        parts = ['<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>"]
        for c in range(cols):
            parts.append(f"<th>{m.headerData(c, Qt.Horizontal, Qt.DisplayRole)}</th>")
        parts.append("</tr></thead><tbody>")
        for r in range(rows):
            parts.append("<tr>")
            for c in range(cols):
                val = m.index(r, c).data(Qt.DisplayRole)
                parts.append(f"<td>{'' if val is None else val}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        html = "".join(parts)

        from PySide6.QtWidgets import QFileDialog
        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "sales_report.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        doc = QTextDocument()
        doc.setHtml(html)
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(fn)
        printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)
        doc.print_(printer)

    def _export_csv(self) -> None:
        tv = self._active_table()
        if not tv:
            QMessageBox.information(self, "Export CSV", "No table to export.")
            return
        from PySide6.QtWidgets import QFileDialog
        import csv
        m: _SimpleTableModel = tv.model()  # type: ignore
        fn, _ = QFileDialog.getSaveFileName(self, "Export to CSV", "sales_report.csv", "CSV Files (*.csv)")
        if not fn:
            return
        cols = m.columnCount()
        rows = m.rowCount()
        with open(fn, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            hdr = [m.headerData(c, Qt.Horizontal, Qt.DisplayRole) for c in range(cols)]
            w.writerow(hdr)
            for r in range(rows):
                w.writerow([m.index(r, c).data(Qt.DisplayRole) for c in range(cols)])
