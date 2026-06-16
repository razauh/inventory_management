# inventory_management/modules/reporting/sales_reports.py
from __future__ import annotations

import html
import sqlite3
from itertools import islice
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QPushButton, QComboBox,
    QTabWidget, QTableView, QCheckBox, QListWidget, QListWidgetItem,
    QFrame, QSpinBox, QAbstractItemView, QMessageBox, QGridLayout, QSizePolicy
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
from .csv_export import safe_csv_row
from .date_range import validate_date_range
from .large_results import maybe_resize_columns

from PySide6.QtCore import QAbstractTableModel


# ----------------------------- Simple model ------------------------------
class _SimpleTableModel(QAbstractTableModel):
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


# --------------------------- Main widget ---------------------------------
class SalesReportsTab(QWidget):
    MAX_ROWS_PER_TABLE = 1000
    PAGE_SIZE = 100

    _TAB_KEYS = [
        "sales_by_day",
        "sales_by_customer",
        "sales_by_product",
        "sales_by_category",
        "margin_by_day",
        "margin_by_customer",
        "margin_by_product",
        "margin_by_category",
        "top_customers",
        "top_products",
        "returns_summary",
        "status_breakdown",
        "drilldown",
    ]

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent=None,
        auto_refresh: bool = True,
        use_background_refresh: bool = False,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)
        self._loaded_rows: Dict[str, List[Dict[str, Any]]] = {}
        self._page_index: Dict[str, int] = {}
        self._use_background_refresh = use_background_refresh

        self._build_ui()
        self._wire()
        self._load_categories()
        if auto_refresh:
            self.refresh()

    # ---------------- UI ----------------
    def _fix_width(self, w, max_w: int) -> None:
        """Clamp a widget to a fixed, compact width."""
        w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        w.setMinimumWidth(max_w)
        w.setMaximumWidth(max_w)

    def _build_row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        lab = QLabel(label)
        lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._fix_width(lab, 90)
        hl.addWidget(lab, 0)
        hl.addWidget(widget, 0)  # widget is fixed-size; won't stretch
        hl.addStretch(1)         # consume leftover so row stays tight
        return row

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Filter bar — 3 compact columns
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        bar.setContentsMargins(8, 8, 8, 8)
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid = QGridLayout(bar)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)  # actions column grows a bit if needed

        today = QDate.currentDate()

        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        self._fix_width(self.dt_from, 110)

        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)
        self._fix_width(self.dt_to, 110)

        self.cmb_gran = QComboBox()
        self.cmb_gran.addItems(["daily", "monthly", "yearly"])
        self.cmb_gran.setCurrentText("daily")
        self.cmb_gran.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._fix_width(self.cmb_gran, 100)

        self.spn_customer = QSpinBox()
        self.spn_customer.setRange(0, 10**9)
        self.spn_customer.setSpecialValueText("Any")
        self.spn_customer.setValue(0)
        self._fix_width(self.spn_customer, 120)

        self.spn_product = QSpinBox()
        self.spn_product.setRange(0, 10**9)
        self.spn_product.setSpecialValueText("Any")
        self.spn_product.setValue(0)
        self._fix_width(self.spn_product, 120)

        self.cmb_category = QComboBox()
        self.cmb_category.addItem("Any", userData=None)
        self.cmb_category.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._fix_width(self.cmb_category, 160)

        self.lst_status = QListWidget()
        self.lst_status.setSelectionMode(QAbstractItemView.MultiSelection)
        for s in ("paid", "unpaid", "partial"):
            it = QListWidgetItem(s)
            it.setSelected(True)
            self.lst_status.addItem(it)
        self.lst_status.setMaximumHeight(64)
        self._fix_width(self.lst_status, 140)

        self.chk_include_returns = QCheckBox("Include returns")
        # keep text short; no width clamp needed

        self.spn_topn = QSpinBox()
        self.spn_topn.setRange(1, 1000)
        self.spn_topn.setValue(10)
        self._fix_width(self.spn_topn, 60)

        self.btn_apply = QPushButton("Apply")
        self._fix_width(self.btn_apply, 80)
        self.btn_prev_page = QPushButton("Prev Page")
        self._fix_width(self.btn_prev_page, 100)
        self.btn_next_page = QPushButton("Next Page")
        self._fix_width(self.btn_next_page, 100)
        self.lbl_page = QLabel("Page 1 / 1")
        self.lbl_page.setMinimumWidth(120)
        self.btn_export_pdf = QPushButton("Export PDF…")
        self._fix_width(self.btn_export_pdf, 110)
        self.btn_export_csv = QPushButton("Export CSV…")
        self._fix_width(self.btn_export_csv, 110)

        # --- place rows into 3 columns ---
        grid.addWidget(QLabel("<b>Date</b>"),           0, 0, 1, 1, Qt.AlignLeft)
        grid.addWidget(self._build_row("From:", self.dt_from), 1, 0)
        grid.addWidget(self._build_row("To:",   self.dt_to),   2, 0)
        grid.addWidget(self._build_row("Granularity:", self.cmb_gran), 3, 0)

        grid.addWidget(QLabel("<b>Filters</b>"),        0, 1, 1, 1, Qt.AlignLeft)
        grid.addWidget(self._build_row("Customer ID:", self.spn_customer), 1, 1)
        grid.addWidget(self._build_row("Product ID:",  self.spn_product),  2, 1)
        grid.addWidget(self._build_row("Category:",    self.cmb_category), 3, 1)

        grid.addWidget(QLabel("<b>Status & Actions</b>"), 0, 2, 1, 1, Qt.AlignLeft)
        # status row
        srow = QWidget()
        srl = QHBoxLayout(srow)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        lab_status = QLabel("Status:")
        self._fix_width(lab_status, 60)
        srl.addWidget(lab_status, 0)
        srl.addWidget(self.lst_status, 0)
        srl.addStretch(1)
        grid.addWidget(srow, 1, 2)

        # options row
        opt = QWidget()
        ol = QHBoxLayout(opt)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(10)
        ol.addWidget(self.chk_include_returns, 0)
        ol.addWidget(QLabel("Top N:"), 0)
        ol.addWidget(self.spn_topn, 0)
        ol.addStretch(1)
        grid.addWidget(opt, 2, 2)

        # buttons row
        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addWidget(self.btn_apply, 0)
        bl.addStretch(1)
        bl.addWidget(self.btn_prev_page, 0)
        bl.addWidget(self.lbl_page, 0)
        bl.addWidget(self.btn_next_page, 0)
        bl.addWidget(self.btn_export_pdf, 0)
        bl.addWidget(self.btn_export_csv, 0)
        grid.addWidget(brow, 3, 2)

        root.addWidget(bar, 0)

        # Results tabs
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # Tables
        self._tables: Dict[str, _BaseTableView] = {}

        def _add_tab(key: str, title: str, headers: List[str], fields: List[str],
                     money_cols: Sequence[int] = (), right_cols: Sequence[int] = ()) -> None:
            tv = _BaseTableView()
            tv.setSelectionBehavior(QTableView.SelectRows)
            tv.setSelectionMode(QTableView.SingleSelection)
            tv.setSortingEnabled(True)
            model = _SimpleTableModel(headers, fields, [], money_cols=money_cols, right_cols=right_cols, parent=tv)
            tv.setModel(model)
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(tv)
            self._tables[key] = tv
            self.tabs.addTab(page, title)

        _add_tab("sales_by_day", "Sales by Day",
                 ["Period", "Orders", "Revenue"],
                 ["period", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))
        _add_tab("sales_by_customer", "Sales by Customer",
                 ["Customer", "Orders", "Revenue", "COGS", "Gross", "Gross %"],
                 ["customer_name", "order_count", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))
        _add_tab("sales_by_product", "Sales by Product",
                 ["Product", "Qty (base)", "Revenue", "COGS", "Gross", "Gross %"],
                 ["product_name", "qty_base", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))
        _add_tab("sales_by_category", "Sales by Category",
                 ["Category", "Qty (base)", "Revenue", "COGS", "Gross", "Gross %"],
                 ["category", "qty_base", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(2, 3, 4), right_cols=(1, 5))
        _add_tab("margin_by_day", "Margin by Day",
                 ["Period", "Revenue", "COGS", "Gross", "Gross %"],
                 ["period", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))
        _add_tab("margin_by_customer", "Margin by Customer",
                 ["Customer", "Revenue", "COGS", "Gross", "Gross %"],
                 ["customer_name", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))
        _add_tab("margin_by_product", "Margin by Product",
                 ["Product", "Revenue", "COGS", "Gross", "Gross %"],
                 ["product_name", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))
        _add_tab("margin_by_category", "Margin by Category",
                 ["Category", "Revenue", "COGS", "Gross", "Gross %"],
                 ["category", "revenue", "cogs", "gross", "margin_pct"],
                 money_cols=(1, 2, 3), right_cols=(4,))
        _add_tab("top_customers", "Top Customers",
                 ["Customer", "Orders", "Revenue"],
                 ["customer_name", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))
        _add_tab("top_products", "Top Products",
                 ["Product", "Qty (base)", "Revenue"],
                 ["product_name", "qty_base", "revenue"],
                 money_cols=(2,), right_cols=(1,))
        _add_tab("returns_summary", "Returns Summary",
                 ["Metric", "Value"],
                 ["metric", "value"],
                 money_cols=(), right_cols=(1,))
        _add_tab("status_breakdown", "Status Breakdown",
                 ["Status", "Orders", "Revenue"],
                 ["payment_status", "order_count", "revenue"],
                 money_cols=(2,), right_cols=(1,))
        _add_tab("drilldown", "Drill-down Sales",
                 ["Sale ID", "Date", "Customer", "Status", "Total", "Paid", "Advance Applied", "Remaining"],
                 ["sale_id", "date", "customer_name", "payment_status", "total_amount", "paid_amount", "advance_payment_applied", "remaining"],
                 money_cols=(4, 5, 6, 7), right_cols=())

    def _wire(self) -> None:
        self.btn_apply.clicked.connect(self.refresh)
        self.btn_prev_page.clicked.connect(self._prev_page)
        self.btn_next_page.clicked.connect(self._next_page)
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)

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
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("Any", userData=None)
        try:
            rows = getattr(self.repo, "get_product_categories")()
            for r in rows:
                if isinstance(r, (tuple, list)) and r:
                    cat = r[0]
                elif hasattr(r, "keys") and "category" in r.keys():
                    cat = r["category"]
                else:
                    cat = r
                if cat is None or str(cat).strip() == "":
                    continue
                self.cmb_category.addItem(str(cat), userData=str(cat))
        except Exception:
            pass
        self.cmb_category.blockSignals(False)

    # -------------- Refresh dispatcher --------------
    def _filters(self) -> Dict[str, Any]:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        return {
            "date_from": date_from,
            "date_to": date_to,
            "gran": self.cmb_gran.currentText(),
            "statuses": self._statuses() or ["paid", "unpaid", "partial"],
            "customer_id": self._customer_id(),
            "product_id": self._product_id(),
            "category": self._category_value(),
            "top_n": int(self.spn_topn.value()),
        }

    def _load_key(self, key: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        args_map = {
            "sales_by_day": ("sales_by_period", filters["date_from"], filters["date_to"], filters["gran"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "sales_by_customer": ("sales_by_customer", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "sales_by_product": ("sales_by_product", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "sales_by_category": ("sales_by_category", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "margin_by_day": ("margin_by_period", filters["date_from"], filters["date_to"], filters["gran"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "margin_by_customer": ("margin_by_customer", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "margin_by_product": ("margin_by_product", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "margin_by_category": ("margin_by_category", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
            "top_customers": ("top_customers", filters["date_from"], filters["date_to"], filters["statuses"], filters["top_n"]),
            "top_products": ("top_products", filters["date_from"], filters["date_to"], filters["statuses"], filters["top_n"]),
            "returns_summary": ("returns_summary", filters["date_from"], filters["date_to"]),
            "status_breakdown": ("status_breakdown", filters["date_from"], filters["date_to"], filters["customer_id"], filters["product_id"], filters["category"]),
            "drilldown": ("drilldown_sales", filters["date_from"], filters["date_to"], filters["statuses"], filters["customer_id"], filters["product_id"], filters["category"]),
        }
        repo_method, *args = args_map[key]
        try:
            fn = getattr(self.repo, repo_method)
            rows = fn(*args)
        except AttributeError:
            if key == "returns_summary":
                return [{"metric": "Info", "value": f"Repo method '{repo_method}' not implemented."}]
            return []
        except Exception as exc:
            if key == "returns_summary":
                return [{"metric": "Error", "value": str(exc)}]
            return []

        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if hasattr(row, "keys"):
                out.append({k: row[k] for k in row.keys()})
            else:
                out.append(dict(row))
        if key.startswith("margin_"):
            for row in out:
                revenue = float(row.get("revenue") or 0.0)
                cogs = float(row.get("cogs") or 0.0)
                row["gross"] = row.get("gross", revenue - cogs)
                row["margin_pct"] = (row["gross"] / revenue) if revenue else 0.0
        if key == "drilldown":
            for row in out:
                total = float(row.get("total_amount") or 0.0)
                paid = float(row.get("paid_amount") or 0.0)
                adv = float(row.get("advance_payment_applied") or 0.0)
                row["remaining"] = total - paid - adv
        return out[: self.MAX_ROWS_PER_TABLE]

    def _ensure_loaded(self, key: str, force: bool = False) -> None:
        if not force and key in self._loaded_rows:
            return
        filters = self._filters()
        with self.repo.read_snapshot():
            self._loaded_rows[key] = self._load_key(key, filters)
        self._apply_page(key)

    def refresh_active_page(self) -> None:
        if not self._validate_date_ranges():
            return
        key = self._current_table_key()
        if key:
            self._ensure_loaded(key, force=True)
        self._sync_page_label()

    @Slot()
    def refresh(self) -> None:
        if not self._validate_date_ranges():
            return
        self._loaded_rows.clear()
        filters = self._filters()
        with self.repo.read_snapshot():
            for key in self._TAB_KEYS:
                self._loaded_rows[key] = self._load_key(key, filters)
        for key in self._TAB_KEYS:
            self._apply_page(key)
        self._sync_page_label()

    # -------------- Export helpers --------------
    def _active_table(self) -> Optional[_BaseTableView]:
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None
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
            header = m.headerData(c, Qt.Horizontal, Qt.DisplayRole)
            parts.append(f"<th>{html.escape('' if header is None else str(header))}</th>")
        parts.append("</tr></thead><tbody>")
        for r in range(rows):
            parts.append("<tr>")
            for c in range(cols):
                val = m.index(r, c).data(Qt.DisplayRole)
                parts.append(f"<td>{html.escape('' if val is None else str(val))}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        report_html = "".join(parts)

        from PySide6.QtWidgets import QFileDialog
        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "sales_report.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        doc = QTextDocument()
        doc.setHtml(report_html)
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(fn)
        printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)
        doc.print_(printer)

    def _export_csv(self) -> None:
        if not self._validate_date_ranges():
            return
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
                w.writerow(safe_csv_row([m.index(r, c).data(Qt.DisplayRole) for c in range(cols)]))

    def _current_table_key(self) -> Optional[str]:
        idx = self.tabs.currentIndex()
        if idx < 0 or idx >= len(self._TAB_KEYS):
            return None
        return self._TAB_KEYS[idx]

    def _max_page(self, key: str) -> int:
        rows = self._loaded_rows.get(key, [])
        if not rows:
            return 0
        return max(0, (len(rows) - 1) // self.PAGE_SIZE)

    def _apply_page(self, key: Optional[str]) -> None:
        if not key:
            return
        self._page_index[key] = max(0, min(self._page_index.get(key, 0), self._max_page(key)))
        tv = self._tables.get(key)
        if not tv:
            return
        rows = self._loaded_rows.get(key, [])
        start = self._page_index[key] * self.PAGE_SIZE
        model: _SimpleTableModel = tv.model()  # type: ignore
        model.set_rows(rows[start:start + self.PAGE_SIZE])
        maybe_resize_columns(tv)
        self._sync_page_label()

    def _prev_page(self) -> None:
        key = self._current_table_key()
        if not key:
            return
        self._page_index[key] = max(0, self._page_index.get(key, 0) - 1)
        self._apply_page(key)

    def _next_page(self) -> None:
        key = self._current_table_key()
        if not key:
            return
        self._page_index[key] = min(self._max_page(key), self._page_index.get(key, 0) + 1)
        self._apply_page(key)

    def _sync_page_label(self) -> None:
        key = self._current_table_key()
        if not key or key not in self._loaded_rows:
            self.lbl_page.setText("Page 1 / 1")
            return
        page = self._page_index.get(key, 0) + 1
        total = self._max_page(key) + 1
        self.lbl_page.setText(f"Page {page} / {total}")

    def _validate_date_ranges(self) -> bool:
        return validate_date_range(self, self.dt_from.date(), self.dt_to.date(), "Sales period")

    @Slot(int)
    def _on_current_tab_changed(self, *_args) -> None:
        key = self._current_table_key()
        if key and self._validate_date_ranges():
            self._ensure_loaded(key)
        self._sync_page_label()
