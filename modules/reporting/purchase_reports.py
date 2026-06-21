# inventory_management/modules/reporting/purchase_reports.py
from __future__ import annotations

import sqlite3
from itertools import islice
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot, QAbstractTableModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QPushButton,
    QTabWidget, QTableView, QComboBox, QSpinBox, QAbstractItemView, QMessageBox,
    QFrame, QGridLayout, QSizePolicy, QFileDialog
)

# Prefer the app's enhanced TableView if available; otherwise fall back.
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

from .html_export import html_table_from_model
from .csv_export import safe_csv_row
from .date_range import validate_date_range
from .large_results import maybe_resize_columns
from ...database.repositories.reporting_repo import ReportingRepo
from ...modules.notifications import notify_info


# ------------------------------ Simple model ------------------------------
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

    # Qt
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
            return "" if val is None else str(val)

        if role == Qt.TextAlignmentRole:
            if c in self._right_cols or c in self._money_cols:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None


# ------------------------------ Purchases Reports Tab -----------------------
class PurchaseReportsTab(QWidget):
    MAX_ROWS_PER_TABLE = 1000
    PAGE_SIZE = 100
    _TAB_KEYS = [
        "purch_by_period",
        "purch_by_vendor",
        "purch_by_product",
        "purch_by_category",
        "top_vendors",
        "top_products",
        "returns_summary",
        "status_breakdown",
        "open_purchases",
        "drilldown",
        "payments_timeline",
    ]

    """
    Rich purchase analytics:

      1) Purchases by Period (daily/monthly/yearly)
      2) Purchases by Vendor
      3) Purchases by Product
      4) Purchases by Category
      5) Top Vendors
      6) Top Products
      7) Returns Summary
      8) Status Breakdown
      9) Open Purchases
     10) Drill-down Purchases
     11) Payments Timeline (cleared cash outflow by date)
    """

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
        self._has_next_page: Dict[str, bool] = {}
        self._use_background_refresh = use_background_refresh

        self._build_ui()
        self._wire()
        self._load_categories()
        if auto_refresh:
            self.refresh()

    # ---------- UI ----------
    def _fix_width(self, w, max_w: int) -> None:
        w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        w.setMinimumWidth(max_w)
        w.setMaximumWidth(max_w)

    def _row(self, label: str, widget: QWidget, label_w: int = 90) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        lab = QLabel(label)
        lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._fix_width(lab, label_w)
        hl.addWidget(lab, 0)
        hl.addWidget(widget, 0)
        hl.addStretch(1)
        return row

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Filter bar (compact 3-column grid)
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
        grid.setColumnStretch(2, 1)

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
        self._fix_width(self.cmb_gran, 100)

        self.spn_vendor = QSpinBox()
        self.spn_vendor.setRange(0, 10**9)
        self.spn_vendor.setSpecialValueText("Any")
        self._fix_width(self.spn_vendor, 120)

        self.spn_product = QSpinBox()
        self.spn_product.setRange(0, 10**9)
        self.spn_product.setSpecialValueText("Any")
        self._fix_width(self.spn_product, 120)

        self.cmb_category = QComboBox()
        self.cmb_category.addItem("Any", userData=None)
        self.cmb_category.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._fix_width(self.cmb_category, 160)

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
        self.btn_pdf = QPushButton("Export PDF…")
        self._fix_width(self.btn_pdf, 110)
        self.btn_csv = QPushButton("Export CSV…")
        self._fix_width(self.btn_csv, 110)

        grid.addWidget(QLabel("<b>Date</b>"), 0, 0, 1, 1, Qt.AlignLeft)
        grid.addWidget(self._row("From:", self.dt_from), 1, 0)
        grid.addWidget(self._row("To:", self.dt_to), 2, 0)
        grid.addWidget(self._row("Granularity:", self.cmb_gran), 3, 0)

        grid.addWidget(QLabel("<b>Filters</b>"), 0, 1, 1, 1, Qt.AlignLeft)
        grid.addWidget(self._row("Vendor ID:", self.spn_vendor), 1, 1)
        grid.addWidget(self._row("Product ID:", self.spn_product), 2, 1)
        grid.addWidget(self._row("Category:", self.cmb_category), 3, 1)

        grid.addWidget(QLabel("<b>Actions</b>"), 0, 2, 1, 1, Qt.AlignLeft)
        act = QWidget()
        al = QHBoxLayout(act)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(QLabel("Top N:"))
        al.addWidget(self.spn_topn)
        al.addStretch(1)
        al.addWidget(self.btn_apply)
        al.addWidget(self.btn_prev_page)
        al.addWidget(self.lbl_page)
        al.addWidget(self.btn_next_page)
        al.addWidget(self.btn_pdf)
        al.addWidget(self.btn_csv)
        grid.addWidget(act, 1, 2, 3, 1)

        root.addWidget(bar, 0)

        # Tabs
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # Table registry
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

        # Tabs
        _add_tab("purch_by_period", "Purchases by Period",
                 ["Period", "Orders", "Spend"],
                 ["period", "order_count", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("purch_by_vendor", "Purchases by Vendor",
                 ["Vendor", "Orders", "Spend"],
                 ["vendor_name", "order_count", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("purch_by_product", "Purchases by Product",
                 ["Product", "Qty (base)", "Spend"],
                 ["product_name", "qty_base", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("purch_by_category", "Purchases by Category",
                 ["Category", "Qty (base)", "Spend"],
                 ["category", "qty_base", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("top_vendors", "Top Vendors",
                 ["Vendor", "Orders", "Spend"],
                 ["vendor_name", "order_count", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("top_products", "Top Products",
                 ["Product", "Qty (base)", "Spend"],
                 ["product_name", "qty_base", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("returns_summary", "Returns Summary",
                 ["Metric", "Value"],
                 ["metric", "value"],
                 right_cols=(1,))

        _add_tab("status_breakdown", "Status Breakdown",
                 ["Status", "Orders", "Spend"],
                 ["payment_status", "order_count", "spend"],
                 money_cols=(2,), right_cols=(1,))

        _add_tab("open_purchases", "Open Purchases",
                 ["Doc No", "Date", "Vendor", "Total", "Paid", "Advance Applied", "Remaining"],
                 ["purchase_id", "date", "vendor_name", "total_amount", "paid_amount", "adv", "remaining"],
                 money_cols=(3, 4, 5, 6), right_cols=())

        _add_tab("drilldown", "Drill-down Purchases",
                 ["Doc No", "Date", "Vendor", "Status", "Total", "Paid", "Advance Applied", "Remaining"],
                 ["purchase_id", "date", "vendor_name", "payment_status", "total_amount", "paid_amount", "adv", "remaining"],
                 money_cols=(4, 5, 6, 7), right_cols=())

        _add_tab("payments_timeline", "Payments Timeline",
                 ["Date", "Cleared Outflow"],
                 ["date", "amount_out"],
                 money_cols=(1,), right_cols=())

    def _wire(self) -> None:
        self.btn_apply.clicked.connect(self.refresh)
        self.btn_prev_page.clicked.connect(self._prev_page)
        self.btn_next_page.clicked.connect(self._next_page)
        self.btn_pdf.clicked.connect(self._export_pdf)
        self.btn_csv.clicked.connect(self._export_csv)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)

    # ---------- Helpers: current filters ----------
    def _vendor_id(self) -> Optional[int]:
        v = self.spn_vendor.value()
        return None if v == 0 else v

    def _product_id(self) -> Optional[int]:
        v = self.spn_product.value()
        return None if v == 0 else v

    def _category_value(self) -> Optional[str]:
        ud = self.cmb_category.currentData()
        return None if ud is None or ud == "" else str(ud)

    def _load_categories(self) -> None:
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("Any", userData=None)
        try:
            for r in self.conn.execute("SELECT DISTINCT category FROM products WHERE COALESCE(TRIM(category),'') <> '' ORDER BY category"):
                self.cmb_category.addItem(str(r["category"]), userData=str(r["category"]))
        except Exception:
            pass
        self.cmb_category.blockSignals(False)

    # ------------------------------ Refresh ------------------------------
    def _filters(self) -> Dict[str, Any]:
        df = self.dt_from.date().toString("yyyy-MM-dd")
        dt = self.dt_to.date().toString("yyyy-MM-dd")
        return {
            "df": df,
            "dt": dt,
            "gran": self.cmb_gran.currentText(),
            "topn": int(self.spn_topn.value()),
            "vendor_id": self._vendor_id(),
            "product_id": self._product_id(),
            "category": self._category_value(),
        }

    def _load_key(
        self,
        key: str,
        filters: Dict[str, Any],
        *,
        page_limit: int | None = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        df = filters["df"]
        dt = filters["dt"]
        gran = filters["gran"]
        topn = filters["topn"]
        vendor_id = filters["vendor_id"]
        product_id = filters["product_id"]
        category = filters["category"]

        if key == "purch_by_period":
            fmt = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "yearly": "%Y"}[gran]
            sql = f"""
                SELECT strftime('{fmt}', p.date) AS period,
                       COUNT(*) AS order_count,
                       SUM(COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))) AS spend
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                LEFT JOIN vendors v ON v.vendor_id = p.vendor_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                  {"AND p.vendor_id = ?" if vendor_id else ""}
                  {"AND EXISTS (SELECT 1 FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id AND pi.product_id = ?)" if product_id else ""}
                  {"AND EXISTS (SELECT 1 FROM purchase_items pi JOIN products pr ON pr.product_id = pi.product_id WHERE pi.purchase_id = p.purchase_id AND pr.category = ?)" if category else ""}
                GROUP BY strftime('{fmt}', p.date)
                ORDER BY period
            """
            params: List[Any] = [df, dt]
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            return [
                {"period": r["period"], "order_count": int(r["order_count"] or 0), "spend": float(r["spend"] or 0.0)}
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "purch_by_vendor":
            sql = """
                SELECT v.name AS vendor_name,
                       COUNT(*) AS order_count,
                       SUM(COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))) AS spend
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                JOIN vendors v ON v.vendor_id = p.vendor_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                  {vend}
                  {prod}
                  {cat}
                GROUP BY v.vendor_id, v.name
                ORDER BY spend DESC, vendor_name
            """.format(
                vend="AND p.vendor_id = ?" if vendor_id else "",
                prod="AND EXISTS (SELECT 1 FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id AND pi.product_id = ?)" if product_id else "",
                cat="AND EXISTS (SELECT 1 FROM purchase_items pi JOIN products pr ON pr.product_id = pi.product_id WHERE pi.purchase_id = p.purchase_id AND pr.category = ?)" if category else "",
            )
            params = [df, dt]
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            return [
                {
                    "vendor_name": r["vendor_name"],
                    "order_count": int(r["order_count"] or 0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "purch_by_product":
            sql = """
                WITH qty_by_product AS (
                    SELECT pi.product_id,
                           pr.name AS product_name,
                           COALESCE(SUM(CAST(pi.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)), 0.0) AS qty_base
                    FROM purchases p
                    JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
                    LEFT JOIN product_uoms pu ON pu.product_id = pi.product_id AND pu.uom_id = pi.uom_id
                    JOIN products pr ON pr.product_id = pi.product_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                      {vend}
                      {prod}
                      {cat}
                    GROUP BY pi.product_id, pr.name
                ),
                spend_by_product AS (
                    SELECT e.product_id,
                           COALESCE(SUM(CAST(e.spend AS REAL)), 0.0) AS spend
                    FROM purchases p
                    JOIN purchase_financial_events e ON e.purchase_id = p.purchase_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                      {vend_spend}
                      {prod_spend}
                      {cat_spend}
                    GROUP BY e.product_id
                )
                SELECT q.product_name,
                       q.qty_base,
                       COALESCE(s.spend, 0.0) AS spend
                FROM qty_by_product q
                LEFT JOIN spend_by_product s ON s.product_id = q.product_id
                ORDER BY spend DESC, product_name
            """.format(
                vend="AND p.vendor_id = ?" if vendor_id else "",
                prod="AND pi.product_id = ?" if product_id else "",
                cat="AND pr.category = ?" if category else "",
                vend_spend="AND p.vendor_id = ?" if vendor_id else "",
                prod_spend="AND e.product_id = ?" if product_id else "",
                cat_spend="AND pr.category = ?" if category else "",
            )
            params = [df, dt]
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            params.extend([df, dt])
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            return [
                {
                    "product_name": r["product_name"],
                    "qty_base": float(r["qty_base"] or 0.0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "purch_by_category":
            sql = """
                WITH qty_by_category AS (
                    SELECT CASE WHEN pr.category IS NULL OR pr.category = '' THEN '(Uncategorized)' ELSE pr.category END AS category,
                           COALESCE(SUM(CAST(pi.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)), 0.0) AS qty_base
                    FROM purchases p
                    JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
                    LEFT JOIN product_uoms pu ON pu.product_id = pi.product_id AND pu.uom_id = pi.uom_id
                    JOIN products pr ON pr.product_id = pi.product_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                      {vend}
                      {prod}
                      {cat_any}
                    GROUP BY CASE WHEN pr.category IS NULL OR pr.category = '' THEN '(Uncategorized)' ELSE pr.category END
                ),
                spend_by_category AS (
                    SELECT CASE WHEN pr.category IS NULL OR pr.category = '' THEN '(Uncategorized)' ELSE pr.category END AS category,
                           COALESCE(SUM(CAST(e.spend AS REAL)), 0.0) AS spend
                    FROM purchases p
                    JOIN purchase_financial_events e ON e.purchase_id = p.purchase_id
                    JOIN products pr ON pr.product_id = e.product_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                      {vend_spend}
                      {prod_spend}
                      {cat_spend}
                    GROUP BY CASE WHEN pr.category IS NULL OR pr.category = '' THEN '(Uncategorized)' ELSE pr.category END
                )
                SELECT q.category,
                       q.qty_base,
                       COALESCE(s.spend, 0.0) AS spend
                FROM qty_by_category q
                LEFT JOIN spend_by_category s ON s.category = q.category
                ORDER BY spend DESC, q.category
            """.format(
                vend="AND p.vendor_id = ?" if vendor_id else "",
                prod="AND pi.product_id = ?" if product_id else "",
                cat_any="AND pr.category = ?" if category else "",
                vend_spend="AND p.vendor_id = ?" if vendor_id else "",
                prod_spend="AND e.product_id = ?" if product_id else "",
                cat_spend="AND pr.category = ?" if category else "",
            )
            params = [df, dt]
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            params.extend([df, dt])
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            return [
                {
                    "category": r["category"] if r["category"] is not None else "",
                    "qty_base": float(r["qty_base"] or 0.0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "top_vendors":
            sql = """
                SELECT v.name AS vendor_name,
                       COUNT(*) AS order_count,
                       SUM(COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))) AS spend
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                JOIN vendors v ON v.vendor_id = p.vendor_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                GROUP BY v.vendor_id, v.name
                ORDER BY spend DESC
                LIMIT ?
            """
            return [
                {
                    "vendor_name": r["vendor_name"],
                    "order_count": int(r["order_count"] or 0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, (df, dt, topn))
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "top_products":
            sql = """
                WITH qty_by_product AS (
                    SELECT pi.product_id,
                           pr.name AS product_name,
                           COALESCE(SUM(CAST(pi.quantity AS REAL) * COALESCE(CAST(pu.factor_to_base AS REAL), 1.0)), 0.0) AS qty_base
                    FROM purchases p
                    JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
                    LEFT JOIN product_uoms pu ON pu.product_id = pi.product_id AND pu.uom_id = pi.uom_id
                    JOIN products pr ON pr.product_id = pi.product_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                    GROUP BY pi.product_id, pr.name
                ),
                spend_by_product AS (
                    SELECT e.product_id,
                           COALESCE(SUM(CAST(e.spend AS REAL)), 0.0) AS spend
                    FROM purchases p
                    JOIN purchase_financial_events e ON e.purchase_id = p.purchase_id
                    WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                    GROUP BY e.product_id
                )
                SELECT q.product_name,
                       q.qty_base,
                       COALESCE(s.spend, 0.0) AS spend
                FROM qty_by_product q
                LEFT JOIN spend_by_product s ON s.product_id = q.product_id
                ORDER BY spend DESC
                LIMIT ?
            """
            return [
                {
                    "product_name": r["product_name"],
                    "qty_base": float(r["qty_base"] or 0.0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, (df, dt, df, dt, topn))
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "returns_summary":
            try:
                sql = """
                    SELECT
                      SUM(CAST(qty_returned_base AS REAL)) AS qty_returned,
                      SUM(CASE WHEN valuation_status = 'resolved'
                               THEN CAST(return_value AS REAL) END) AS return_value,
                      SUM(CASE WHEN valuation_status = 'unresolved' THEN 1 ELSE 0 END) AS unresolved_count
                    FROM purchase_return_valuations
                    WHERE DATE(return_date) BETWEEN DATE(?) AND DATE(?)
                """
                r = self.conn.execute(sql, (df, dt)).fetchone()
                qty = float(r["qty_returned"] or 0.0) if r else 0.0
                val = float(r["return_value"] or 0.0) if r else 0.0
                unresolved = int(r["unresolved_count"] or 0) if r else 0
                return [
                    {"metric": "Returned Qty (base)", "value": qty},
                    {"metric": "Return Value", "value": val},
                    {"metric": "Unresolved Legacy Returns", "value": unresolved},
                ][: self.MAX_ROWS_PER_TABLE]
            except Exception:
                return [{"metric": "Info", "value": "purchase_return_valuations view not found"}]

        if key == "status_breakdown":
            sql = """
                SELECT p.payment_status,
                       COUNT(*) AS order_count,
                       SUM(COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL))) AS spend
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                GROUP BY p.payment_status
                ORDER BY spend DESC
            """
            return [
                {
                    "payment_status": r["payment_status"],
                    "order_count": int(r["order_count"] or 0),
                    "spend": float(r["spend"] or 0.0),
                }
                for r in self.conn.execute(sql, (df, dt))
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "open_purchases":
            sql = """
                SELECT p.purchase_id, p.date, v.name AS vendor_name,
                       COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) AS total_amount,
                       CAST(p.paid_amount  AS REAL) AS paid_amount,
                       CAST(p.advance_payment_applied AS REAL) AS adv,
                       (COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS remaining
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                JOIN vendors v ON v.vendor_id = p.vendor_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                  AND (COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) > 1e-9
                ORDER BY DATE(p.date) DESC, p.purchase_id DESC
                {page}
            """.format(
                page="LIMIT ? OFFSET ?" if page_limit is not None else "",
            )
            params = [df, dt]
            if page_limit is not None:
                params.extend([int(page_limit), max(0, int(offset))])
            return [
                {k: (float(r[k]) if k in ("total_amount", "paid_amount", "adv", "remaining") else r[k]) for k in r.keys()}
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        if key == "drilldown":
            sql = """
                SELECT p.purchase_id, p.date, v.name AS vendor_name, p.payment_status,
                       COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) AS total_amount,
                       CAST(p.paid_amount  AS REAL) AS paid_amount,
                       CAST(p.advance_payment_applied AS REAL) AS adv,
                       (COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL)) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS remaining
                FROM purchases p
                LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                JOIN vendors v ON v.vendor_id = p.vendor_id
                WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
                  {vend}
                  {prod}
                  {cat}
                ORDER BY DATE(p.date) DESC, p.purchase_id DESC
                {page}
            """
            sql = sql.format(
                vend="AND p.vendor_id = ?" if vendor_id else "",
                prod="AND EXISTS (SELECT 1 FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id AND pi.product_id = ?)" if product_id else "",
                cat="AND EXISTS (SELECT 1 FROM purchase_items pi JOIN products pr ON pr.product_id = pi.product_id WHERE pi.purchase_id = p.purchase_id AND pr.category = ?)" if category else "",
                page="LIMIT ? OFFSET ?" if page_limit is not None else "",
            )
            params = [df, dt]
            if vendor_id:
                params.append(vendor_id)
            if product_id:
                params.append(product_id)
            if category:
                params.append(category)
            if page_limit is not None:
                params.extend([int(page_limit), max(0, int(offset))])
            return [
                {k: (float(r[k]) if k in ("total_amount", "paid_amount", "adv", "remaining") else r[k]) for k in r.keys()}
                for r in self.conn.execute(sql, params)
            ][: self.MAX_ROWS_PER_TABLE]

        sql = """
            SELECT date AS date,
                   SUM(CASE WHEN CAST(amount AS REAL) > 0 THEN CAST(amount AS REAL) ELSE 0.0 END) AS amount_out
            FROM purchase_payments
            WHERE DATE(date) BETWEEN DATE(?) AND DATE(?)
              AND clearing_state = 'cleared'
            GROUP BY date
            ORDER BY DATE(date)
        """
        return [
            {"date": r["date"], "amount_out": float(r["amount_out"] or 0.0)}
            for r in self.conn.execute(sql, (df, dt))
        ][: self.MAX_ROWS_PER_TABLE]

    def _ensure_loaded(self, key: str, force: bool = False) -> None:
        if not force and key in self._loaded_rows:
            return
        filters = self._filters()
        with self.repo.read_snapshot():
            if key in {"open_purchases", "drilldown"}:
                rows = self._load_key(
                    key,
                    filters,
                    page_limit=self.PAGE_SIZE + 1,
                    offset=self._page_index.get(key, 0) * self.PAGE_SIZE,
                )
                self._has_next_page[key] = len(rows) > self.PAGE_SIZE
                self._loaded_rows[key] = rows[: self.PAGE_SIZE]
            else:
                self._has_next_page[key] = False
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
        self._has_next_page.clear()
        self._page_index.clear()
        if self._uses_in_memory_db():
            filters = self._filters()
            with self.repo.read_snapshot():
                for key in self._TAB_KEYS:
                    self._has_next_page[key] = False
                    self._loaded_rows[key] = self._load_key(key, filters)
            for key in self._TAB_KEYS:
                self._apply_page(key)
            self._sync_page_label()
            return
        key = self._current_table_key()
        if key:
            self._ensure_loaded(key, force=True)
        self._sync_page_label()

    def _uses_in_memory_db(self) -> bool:
        try:
            row = self.conn.execute("PRAGMA database_list").fetchone()
            if not row:
                return False
            path = row["file"] if hasattr(row, "keys") else row[2]
            return not str(path or "").strip()
        except Exception:
            return False

    # ------------------------------ Export ------------------------------
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
            notify_info(self, "Export PDF", "No table to export.")
            return
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter
        m: _SimpleTableModel = tv.model()  # type: ignore
        html = html_table_from_model(m)

        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "purchase_report.pdf", "PDF Files (*.pdf)")
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
        if not self._validate_date_ranges():
            return
        tv = self._active_table()
        if not tv:
            notify_info(self, "Export CSV", "No table to export.")
            return
        from PySide6.QtWidgets import QFileDialog
        import csv
        m: _SimpleTableModel = tv.model()  # type: ignore
        fn, _ = QFileDialog.getSaveFileName(self, "Export to CSV", "purchase_report.csv", "CSV Files (*.csv)")
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
        if key in {"open_purchases", "drilldown"}:
            current = self._page_index.get(key, 0)
            return current + (1 if self._has_next_page.get(key, False) else 0)
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
        start = 0 if key in {"open_purchases", "drilldown"} else self._page_index[key] * self.PAGE_SIZE
        model: _SimpleTableModel = tv.model()  # type: ignore
        model.set_rows(rows[start:start + self.PAGE_SIZE])
        maybe_resize_columns(tv)
        self._sync_page_label()

    def _prev_page(self) -> None:
        key = self._current_table_key()
        if not key:
            return
        self._page_index[key] = max(0, self._page_index.get(key, 0) - 1)
        if key in {"open_purchases", "drilldown"}:
            self._ensure_loaded(key, force=True)
        else:
            self._apply_page(key)

    def _next_page(self) -> None:
        key = self._current_table_key()
        if not key:
            return
        self._page_index[key] = min(self._max_page(key), self._page_index.get(key, 0) + 1)
        if key in {"open_purchases", "drilldown"}:
            self._ensure_loaded(key, force=True)
        else:
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
        return validate_date_range(self, self.dt_from.date(), self.dt_to.date(), "Purchase period")

    @Slot(int)
    def _on_current_tab_changed(self, *_args) -> None:
        key = self._current_table_key()
        if key and self._validate_date_ranges():
            self._ensure_loaded(key)
        self._sync_page_label()
