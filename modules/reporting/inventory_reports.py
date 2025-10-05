# inventory_management/modules/reporting/inventory_reports.py
from __future__ import annotations

import sqlite3
import threading
from typing import List, Optional

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot, QAbstractTableModel
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDateEdit,
    QComboBox,
    QPushButton,
    QTableView,
    QFileDialog,
    QMessageBox,
    QRadioButton,
    QButtonGroup,
    QTabWidget,
)

# Prefer the app's table view if available; fall back to vanilla QTableView.
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

# Money formatting (reuse app helper if present)
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"

from .model import (
    InventoryStockOnHandTableModel,
    InventoryTransactionsTableModel,
)
from ...database.repositories.reporting_repo import ReportingRepo


# ------------------------------ Logic ---------------------------------------


class InventoryReports:
    """
    Thin logic layer built on ReportingRepo for inventory reporting.
    """

    # Module-level cache for static reference data with thread-safe access
    _product_cache: dict[int, str] = {}
    _cache_lock = threading.Lock()
    _cache_initialized = False

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = ReportingRepo(conn)
        self.conn.row_factory = sqlite3.Row

    def stock_on_hand_current(self) -> List[dict]:
        rows = self.repo.stock_on_hand_current()
        id_to_name = self._product_name_map()
        out: List[dict] = []
        for r in rows:
            keys = set(r.keys())
            # try to get a name from any plausible column; else look up by product_id
            name = (
                r["product_name"] if "product_name" in keys else
                r["name"] if "name" in keys else
                r["product"] if "product" in keys else
                None
            )
            if not name:
                pid = int(r["product_id"]) if "product_id" in keys and r["product_id"] is not None else None
                name = id_to_name.get(pid, f"#{pid}") if pid is not None else "(Unknown)"

            # quantity column variants
            qty = (
                float(r["qty_base"]) if "qty_base" in keys else
                float(r["on_hand_qty"]) if "on_hand_qty" in keys else
                float(r["quantity"]) if "quantity" in keys else
                float(r["qty"]) if "qty" in keys else
                0.0
            )

            # unit value variants
            uval = (
                float(r["unit_value"]) if "unit_value" in keys else
                float(r["unit_cost"]) if "unit_cost" in keys else
                0.0
            )

            # total value if present; else compute
            tval = float(r["total_value"]) if "total_value" in keys and r["total_value"] is not None else qty * uval

            # valuation date (optional)
            vdate = str(r["valuation_date"]) if "valuation_date" in keys else ""

            out.append(
                {
                    "product_name": str(name),
                    "qty_base": float(qty),
                    "unit_value": float(uval),
                    "total_value": float(tval),
                    "valuation_date": vdate,
                }
            )
        return out

    def stock_on_hand_as_of(self, as_of: str) -> List[dict]:
        rows = self.repo.stock_on_hand_as_of(as_of)
        id_to_name = self._product_name_map()
        out: List[dict] = []
        for r in rows:
            keys = set(r.keys())
            name = (
                r["product_name"] if "product_name" in keys else
                r["name"] if "name" in keys else
                r["product"] if "product" in keys else
                None
            )
            if not name:
                pid = int(r["product_id"]) if "product_id" in keys and r["product_id"] is not None else None
                name = id_to_name.get(pid, f"#{pid}") if pid is not None else "(Unknown)"

            qty = (
                float(r["qty_base"]) if "qty_base" in keys else
                float(r["on_hand_qty"]) if "on_hand_qty" in keys else
                float(r["quantity"]) if "quantity" in keys else
                float(r["qty"]) if "qty" in keys else
                0.0
            )

            uval = (
                float(r["unit_value"]) if "unit_value" in keys else
                float(r["unit_cost"]) if "unit_cost" in keys else
                0.0
            )

            tval = float(r["total_value"]) if "total_value" in keys and r["total_value"] is not None else qty * uval
            vdate = str(r["valuation_date"]) if "valuation_date" in keys else ""

            out.append(
                {
                    "product_name": str(name),
                    "qty_base": float(qty),
                    "unit_value": float(uval),
                    "total_value": float(tval),
                    "valuation_date": vdate,
                }
            )
        return out

    def transactions(self, date_from: str, date_to: str, product_id: Optional[int]) -> List[dict]:
        rows = self.repo.inventory_transactions(date_from, date_to, product_id)
        # Map product_id -> name to show a nice label if not already present
        id_to_name = self._product_name_map()
        out: List[dict] = []
        for r in rows:
            pid = int(r["product_id"])
            out.append(
                {
                    "date": str(r["date"]),
                    "product_name": id_to_name.get(pid, f"#{pid}"),
                    "type": str(r["type"]),                        # corrected: repository returns 'type', not 'transaction_type'
                    "qty_base": float(r["qty_base"] or 0.0),
                    "ref_table": str(r["ref_table"] or ""),        # corrected: repository returns 'ref_table', not 'reference_table'
                    "ref_id": str(r["ref_id"] or ""),              # corrected: repository returns 'ref_id', not 'reference_id'
                    "notes": str(r["notes"] or ""),
                }
            )
        return out

    def valuation_history(self, product_id: int, limit: int | None = 100) -> List[dict]:
        lim = int(limit or 100)
        rows = self.repo.valuation_history(product_id, lim)
        return [
            {
                "date": str(r["date"]),
                "qty_base": float(r["qty_base"] or 0.0),
                "unit_value": float(r["unit_value"] or 0.0),
                "total_value": float(
                    r["total_value"]
                    or (float(r["qty_base"] or 0.0) * float(r["unit_value"] or 0.0))
                ),
            }
            for r in rows
        ]

    # Helpers
    def list_products(self) -> List[tuple[int, str]]:
        """
        Read products for pickers.
        Expected table: products(product_id, name)
        """
        rows = list(self.conn.execute(
            "SELECT product_id, name FROM products ORDER BY name COLLATE NOCASE"
        ))
        return [(int(r["product_id"]), str(r["name"])) for r in rows]

    @classmethod
    def _ensure_product_cache(cls, conn: sqlite3.Connection) -> None:
        """
        Ensure the product cache is initialized in a thread-safe manner.
        This prevents repeated database queries for product names in large datasets.
        """
        with cls._cache_lock:
            if not cls._cache_initialized:
                # Fetch all products in a single query for the cache
                rows = list(conn.execute(
                    "SELECT product_id, name FROM products ORDER BY name COLLATE NOCASE"
                ))
                cls._product_cache = {int(r["product_id"]): str(r["name"]) for r in rows}
                cls._cache_initialized = True

    def _product_name_map(self) -> dict[int, str]:
        """
        Return a mapping of product_id to product name for efficient lookups.
        This prevents repeated database queries for product names in large datasets.
        """
        # Initialize cache if needed (thread-safe)
        self._ensure_product_cache(self.conn)
        # Return a copy of the cached data to avoid external modifications
        return self._product_cache.copy()


# ------------------------------ Local model (Valuation History) -------------


class ValuationHistoryTableModel(QAbstractTableModel):
    """
    Simple list model for valuation history:
      Date | Qty (base) | Unit Value | Total Value
    """

    HEADERS = ("Date", "Qty (base)", "Unit Value", "Total Value")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    # Qt required overrides
    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        row = self._rows[r]

        if role == Qt.DisplayRole:
            if c == 0:
                return row.get("date", "")
            if c == 1:
                try:
                    return f"{float(row.get('qty_base') or 0.0):,.3f}".rstrip("0").rstrip(".")
                except Exception:
                    return "0"
            if c == 2:
                return fmt_money(row.get("unit_value"))
            if c == 3:
                return fmt_money(row.get("total_value"))

        if role == Qt.TextAlignmentRole:
            if c in (1, 2, 3):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None


# ------------------------------ UI Tab --------------------------------------


class InventoryReportsTab(QWidget):
    """
    Inventory Reports UI with three sub-tabs:
      1) Stock on Hand (Current / As-of)
      2) Transactions (date range + product)
      3) Valuation History (product + limit)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logic = InventoryReports(conn)

        # Keep raw rows for potential exports
        self._rows_stock: List[dict] = []
        self._rows_txns: List[dict] = []
        self._rows_valhist: List[dict] = []

        self._build_ui()
        self._wire_signals()
        self._load_products()

    # ---- UI construction ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Sub-tabs
        self.subtabs = QTabWidget(self)
        root.addWidget(self.subtabs)

        # 1) Stock on Hand
        self.pg_stock = QWidget()
        layout_stock = QVBoxLayout(self.pg_stock)
        layout_stock.setContentsMargins(8, 8, 8, 8)
        layout_stock.setSpacing(6)

        # Stock toolbar
        bar_s = QHBoxLayout()
        bar_s.addWidget(QLabel("View:"))
        self.rad_stock_current = QRadioButton("Current")
        self.rad_stock_asof = QRadioButton("As of")
        self.rad_stock_current.setChecked(True)
        self.grp_stock = QButtonGroup(self.pg_stock)
        self.grp_stock.addButton(self.rad_stock_current)
        self.grp_stock.addButton(self.rad_stock_asof)
        bar_s.addWidget(self.rad_stock_current)
        bar_s.addWidget(self.rad_stock_asof)

        self.dt_stock_asof = QDateEdit()
        self.dt_stock_asof.setCalendarPopup(True)
        self.dt_stock_asof.setDisplayFormat("yyyy-MM-dd")
        self.dt_stock_asof.setDate(QDate.currentDate())
        self.dt_stock_asof.setEnabled(False)
        bar_s.addWidget(self.dt_stock_asof)

        bar_s.addStretch(1)

        self.btn_stock_refresh = QPushButton("Refresh")
        self.btn_stock_print = QPushButton("Print / PDF…")
        bar_s.addWidget(self.btn_stock_refresh)
        bar_s.addWidget(self.btn_stock_print)

        layout_stock.addLayout(bar_s)

        # Stock table
        self.tbl_stock = _BaseTableView()
        self.tbl_stock.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_stock.setSelectionMode(QTableView.SingleSelection)
        self.tbl_stock.setSortingEnabled(False)

        self.model_stock = InventoryStockOnHandTableModel([])
        self.tbl_stock.setModel(self.model_stock)
        layout_stock.addWidget(self.tbl_stock)

        self.subtabs.addTab(self.pg_stock, "Stock on Hand")

        # 2) Transactions
        self.pg_txn = QWidget()
        layout_txn = QVBoxLayout(self.pg_txn)
        layout_txn.setContentsMargins(8, 8, 8, 8)
        layout_txn.setSpacing(6)

        bar_t = QHBoxLayout()
        bar_t.addWidget(QLabel("From:"))
        self.dt_txn_from = QDateEdit()
        self.dt_txn_from.setCalendarPopup(True)
        self.dt_txn_from.setDisplayFormat("yyyy-MM-dd")
        today = QDate.currentDate()
        self.dt_txn_from.setDate(QDate(today.year(), today.month(), 1))
        bar_t.addWidget(self.dt_txn_from)

        bar_t.addSpacing(8)
        bar_t.addWidget(QLabel("To:"))
        self.dt_txn_to = QDateEdit()
        self.dt_txn_to.setCalendarPopup(True)
        self.dt_txn_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_txn_to.setDate(today)
        bar_t.addWidget(self.dt_txn_to)

        bar_t.addSpacing(12)
        bar_t.addWidget(QLabel("Product:"))
        self.cmb_txn_product = QComboBox()
        self.cmb_txn_product.setMinimumWidth(260)
        bar_t.addWidget(self.cmb_txn_product)

        bar_t.addStretch(1)
        self.btn_txn_refresh = QPushButton("Refresh")
        self.btn_txn_print = QPushButton("Print / PDF…")
        bar_t.addWidget(self.btn_txn_refresh)
        bar_t.addWidget(self.btn_txn_print)

        layout_txn.addLayout(bar_t)

        self.tbl_txn = _BaseTableView()
        self.tbl_txn.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_txn.setSelectionMode(QTableView.SingleSelection)
        self.tbl_txn.setSortingEnabled(False)

        self.model_txn = InventoryTransactionsTableModel([])
        self.tbl_txn.setModel(self.model_txn)
        layout_txn.addWidget(self.tbl_txn)

        self.subtabs.addTab(self.pg_txn, "Transactions")

        # 3) Valuation History
        self.pg_val = QWidget()
        layout_val = QVBoxLayout(self.pg_val)
        layout_val.setContentsMargins(8, 8, 8, 8)
        layout_val.setSpacing(6)

        bar_v = QHBoxLayout()
        bar_v.addWidget(QLabel("Product:"))
        self.cmb_val_product = QComboBox()
        self.cmb_val_product.setMinimumWidth(260)
        bar_v.addWidget(self.cmb_val_product)

        bar_v.addSpacing(12)
        bar_v.addWidget(QLabel("Limit:"))
        self.cmb_val_limit = QComboBox()
        self.cmb_val_limit.addItems(["50", "100", "500"])
        self.cmb_val_limit.setCurrentText("100")
        bar_v.addWidget(self.cmb_val_limit)

        bar_v.addStretch(1)
        self.btn_val_refresh = QPushButton("Refresh")
        self.btn_val_print = QPushButton("Print / PDF…")
        bar_v.addWidget(self.btn_val_refresh)
        bar_v.addWidget(self.btn_val_print)

        layout_val.addLayout(bar_v)

        self.tbl_val = _BaseTableView()
        self.tbl_val.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_val.setSelectionMode(QTableView.SingleSelection)
        self.tbl_val.setSortingEnabled(False)

        self.model_val = ValuationHistoryTableModel([])
        self.tbl_val.setModel(self.model_val)
        layout_val.addWidget(self.tbl_val)

        self.subtabs.addTab(self.pg_val, "Valuation History")

    def _wire_signals(self) -> None:
        # Stock
        self.rad_stock_current.toggled.connect(self._on_stock_toggle)
        self.dt_stock_asof.dateChanged.connect(lambda *_: self.refresh_stock())
        self.btn_stock_refresh.clicked.connect(self.refresh_stock)
        self.btn_stock_print.clicked.connect(self._on_print_stock)

        # Transactions
        self.btn_txn_refresh.clicked.connect(self.refresh_txn)
        self.btn_txn_print.clicked.connect(self._on_print_txn)
        self.dt_txn_from.dateChanged.connect(lambda *_: self.refresh_txn())
        self.dt_txn_to.dateChanged.connect(lambda *_: self.refresh_txn())
        self.cmb_txn_product.currentIndexChanged.connect(lambda *_: self.refresh_txn())

        # Valuation history
        self.btn_val_refresh.clicked.connect(self.refresh_val)
        self.btn_val_print.clicked.connect(self._on_print_val)
        self.cmb_val_product.currentIndexChanged.connect(lambda *_: self.refresh_val())
        self.cmb_val_limit.currentIndexChanged.connect(lambda *_: self.refresh_val())

    def _load_products(self) -> None:
        # Fill product combos
        self.cmb_txn_product.blockSignals(True)
        self.cmb_val_product.blockSignals(True)

        self.cmb_txn_product.clear()
        self.cmb_txn_product.addItem("All Products", None)

        self.cmb_val_product.clear()

        try:
            for pid, name in self.logic.list_products():
                self.cmb_txn_product.addItem(name, pid)
                self.cmb_val_product.addItem(name, pid)
        except Exception:
            pass

        self.cmb_txn_product.blockSignals(False)
        self.cmb_val_product.blockSignals(False)

        # Initial refresh for all tabs
        self.refresh_stock()
        self.refresh_txn()
        # choose first product for valuation history if exists
        if self.cmb_val_product.count() > 0:
            self.cmb_val_product.setCurrentIndex(0)
        self.refresh_val()

    # ---- Stock on Hand tab ----

    def _on_stock_toggle(self, checked: bool) -> None:
        # Enable/disable as-of date picker
        self.dt_stock_asof.setEnabled(self.rad_stock_asof.isChecked())
        self.refresh_stock()

    @Slot()
    def refresh_stock(self) -> None:
        if self.rad_stock_current.isChecked():
            self._rows_stock = self.logic.stock_on_hand_current()
        else:
            as_of = self.dt_stock_asof.date().toString("yyyy-MM-dd")
            self._rows_stock = self.logic.stock_on_hand_as_of(as_of)

        self.model_stock.set_rows(self._rows_stock)
        self._autosize(self.tbl_stock)

    def _on_print_stock(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Stock to PDF", "stock_on_hand.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            html = []
            html.append("<h2>Stock on Hand</h2>")
            if self.rad_stock_current.isChecked():
                html.append("<p><b>View:</b> Current</p>")
            else:
                as_of = self.dt_stock_asof.date().toString("yyyy-MM-dd")
                html.append(f"<p><b>View:</b> As of {as_of}</p>")
            html.append(self._html_from_model(self.tbl_stock))
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    # ---- Transactions tab ----

    @Slot()
    def refresh_txn(self) -> None:
        date_from = self.dt_txn_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_txn_to.date().toString("yyyy-MM-dd")
        pid = self.cmb_txn_product.currentData()
        product_id = int(pid) if isinstance(pid, int) else None

        self._rows_txns = self.logic.transactions(date_from, date_to, product_id)
        self.model_txn.set_rows(self._rows_txns)
        self._autosize(self.tbl_txn)

    def _on_print_txn(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Transactions to PDF", "inventory_transactions.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            date_from = self.dt_txn_from.date().toString("yyyy-MM-dd")
            date_to = self.dt_txn_to.date().toString("yyyy-MM-dd")
            prod_txt = self.cmb_txn_product.currentText()

            html = []
            html.append("<h2>Inventory Transactions</h2>")
            html.append(f"<p><b>Period:</b> {date_from} to {date_to}<br>")
            html.append(f"<b>Product:</b> {prod_txt}</p>")
            html.append(self._html_from_model(self.tbl_txn))
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    # ---- Valuation History tab ----

    @Slot()
    def refresh_val(self) -> None:
        pid = self.cmb_val_product.currentData()
        if not isinstance(pid, int):
            self.model_val.set_rows([])
            self._autosize(self.tbl_val)
            return

        lim = int(self.cmb_val_limit.currentText() or "100")
        self._rows_valhist = self.logic.valuation_history(pid, lim)
        self.model_val.set_rows(self._rows_valhist)
        self._autosize(self.tbl_val)

    def _on_print_val(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Valuation History to PDF", "valuation_history.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            prod_txt = self.cmb_val_product.currentText()
            lim = self.cmb_val_limit.currentText()

            html = []
            html.append("<h2>Valuation History</h2>")
            html.append(f"<p><b>Product:</b> {prod_txt} &nbsp;&nbsp; <b>Limit:</b> {lim}</p>")
            html.append(self._html_from_model(self.tbl_val))
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    # ---- Shared helpers ----

    def _autosize(self, tv: QTableView) -> None:
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)

    def _html_from_model(self, tv: QTableView) -> str:
        """
        Lightweight HTML table dump of a QTableView's model.
        """
        m = tv.model()
        if m is None:
            return "<p>(No data)</p>"
        cols = m.columnCount()
        rows = m.rowCount()
        parts = ['<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>"]
        for c in range(cols):
            hdr = m.headerData(c, Qt.Horizontal, Qt.DisplayRole)
            parts.append(f"<th>{hdr}</th>")
        parts.append("</tr></thead><tbody>")
        for r in range(rows):
            parts.append("<tr>")
            for c in range(cols):
                idx: QModelIndex = m.index(r, c)
                val = m.data(idx, Qt.DisplayRole)
                parts.append(f"<td>{val if val is not None else ''}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        return "".join(parts)

    def _render_pdf(self, html: str, filepath: str) -> None:
        """
        Render given HTML to PDF via QTextDocument/QPrinter.
        """
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter

        doc = QTextDocument()
        doc.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filepath)
        printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)

        doc.print_(printer)

    # Public hook expected by controller
    @Slot()
    def refresh(self) -> None:
        # Refresh current sub-tab to keep work lightweight
        idx = self.subtabs.currentIndex()
        if idx == 0:
            self.refresh_stock()
        elif idx == 1:
            self.refresh_txn()
        else:
            self.refresh_val()
