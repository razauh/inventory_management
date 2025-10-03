# inventory_management/modules/reporting/expense_reports.py
from __future__ import annotations

import sqlite3
from typing import List, Optional

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDateEdit,
    QComboBox,
    QPushButton,
    QTableView,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QFrame,
)

# Prefer the app's table view if available; fall back to vanilla QTableView.
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

from .model import ExpenseSummaryTableModel, ExpenseListTableModel

# Money formatting (reuse app helper if present)
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"

# Reporting repo consolidates the SQL
from ...database.repositories.reporting_repo import ReportingRepo


# ------------------------------ Logic ---------------------------------------


class ExpenseReports:
    """
    Thin logic layer for Expense reporting built on top of ReportingRepo.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = ReportingRepo(conn)
        self.conn.row_factory = sqlite3.Row

    def summary_by_category(
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> List[dict]:
        """
        Return rows:
          { category_id, category_name, total_amount }
        """
        rows = self.repo.expense_summary_by_category(date_from, date_to, category_id)
        return [
            {
                "category_id": int(r["category_id"]),
                "category_name": str(r["category_name"]),
                "total_amount": float(r["total_amount"] or 0.0),
            }
            for r in rows
        ]

    def list_expenses(
        self, date_from: str, date_to: str, category_id: Optional[int]
    ) -> List[dict]:
        """
        Return rows:
          { expense_id, date, category_name, description, amount }
        Ordered by date desc, id desc (enforced in repo).
        """
        rows = self.repo.expense_lines(date_from, date_to, category_id)
        out: List[dict] = []
        for r in rows:
            out.append(
                {
                    "expense_id": int(r["expense_id"]),
                    "date": str(r["date"]),
                    "category_name": str(r["category_name"]),
                    "description": (r["description"] or ""),
                    "amount": float(r["amount"] or 0.0),
                }
            )
        return out

    # Helper for UI to load category list
    def list_categories(self) -> List[tuple[int, str]]:
        """
        Read categories for the combo box.
        Expected table: expense_categories(id, name)
        """
        # Performance optimization: Use single query to fetch all categories
        rows = list(self.conn.execute("SELECT id, name FROM expense_categories ORDER BY name COLLATE NOCASE"))
        return [(int(r["id"]), str(r["name"])) for r in rows]


# ------------------------------ UI Tab --------------------------------------


class ExpenseReportsTab(QWidget):
    """
    Expense Reports UI:
      - Toolbar: From/To date, Category (All or one), Refresh, Print/PDF
      - Top table: summary by category (% computed in model)
      - Bottom table: raw expense lines
      - Footer: grand total label (sum of summary)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logic = ExpenseReports(conn)

        self._rows_summary: List[dict] = []
        self._rows_lines: List[dict] = []

        self._build_ui()
        self._wire_signals()
        self._reload_categories()

    # ---- UI construction ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        bar.addWidget(QLabel("From:"))
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        # default to first of current month
        today = QDate.currentDate()
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        bar.addWidget(self.dt_from)

        bar.addSpacing(8)
        bar.addWidget(QLabel("To:"))
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)
        bar.addWidget(self.dt_to)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Category:"))
        self.cmb_category = QComboBox()
        self.cmb_category.setMinimumWidth(220)
        bar.addWidget(self.cmb_category)

        bar.addStretch(1)

        self.btn_refresh = QPushButton("Refresh")
        bar.addWidget(self.btn_refresh)

        self.btn_print = QPushButton("Print / PDF…")
        bar.addWidget(self.btn_print)

        root.addLayout(bar)

        # Splitter for tables
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        # Top: summary
        self.tbl_summary = _BaseTableView()
        self.tbl_summary.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_summary.setSelectionMode(QTableView.SingleSelection)
        self.tbl_summary.setSortingEnabled(False)
        split.addWidget(self.tbl_summary)

        # Bottom: lines
        self.tbl_lines = _BaseTableView()
        self.tbl_lines.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_lines.setSelectionMode(QTableView.SingleSelection)
        self.tbl_lines.setSortingEnabled(False)
        split.addWidget(self.tbl_lines)

        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split)

        # Footer: grand total
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addStretch(1)
        self.lbl_total = QLabel("Total: 0.00")
        self.lbl_total.setObjectName("ExpenseGrandTotal")
        footer.addWidget(self.lbl_total)
        root.addLayout(footer)

        # Models
        self.model_summary = ExpenseSummaryTableModel([])
        self.model_lines = ExpenseListTableModel([])
        self.tbl_summary.setModel(self.model_summary)
        self.tbl_lines.setModel(self.model_lines)

    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_print.clicked.connect(self._on_print_pdf)

        self.dt_from.dateChanged.connect(lambda *_: self.refresh())
        self.dt_to.dateChanged.connect(lambda *_: self.refresh())
        self.cmb_category.currentIndexChanged.connect(lambda *_: self.refresh())

    def _reload_categories(self) -> None:
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("All Categories", None)
        try:
            for cid, name in self.logic.list_categories():
                self.cmb_category.addItem(name, cid)
        except Exception:
            # Keep "All Categories" if lookup fails
            pass
        self.cmb_category.blockSignals(False)

    # ---- Behavior ----

    @Slot()
    def refresh(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        category_id = self.cmb_category.currentData()
        cat_id = int(category_id) if isinstance(category_id, int) else None

        # Top: summary
        self._rows_summary = self.logic.summary_by_category(date_from, date_to, cat_id)
        self.model_summary.set_rows(self._rows_summary)
        self._autosize(self.tbl_summary)

        # Bottom: lines
        self._rows_lines = self.logic.list_expenses(date_from, date_to, cat_id)
        self.model_lines.set_rows(self._rows_lines)
        self._autosize(self.tbl_lines)

        # Footer total (sum of summary)
        grand_total = sum(float(r.get("total_amount") or 0.0) for r in self._rows_summary)
        self.lbl_total.setText(f"Total: {fmt_money(grand_total)}")

    def _autosize(self, tv: QTableView) -> None:
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)

    # ---- Print / PDF ----

    @Slot()
    def _on_print_pdf(self) -> None:
        """
        Export summary + lines to a single PDF.
        """
        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "expenses.pdf", "PDF Files (*.pdf)")
        if not fn:
            return

        try:
            date_from = self.dt_from.date().toString("yyyy-MM-dd")
            date_to = self.dt_to.date().toString("yyyy-MM-dd")
            cat_txt = self.cmb_category.currentText()

            html = []
            html.append(f"<h2>Expense Reports</h2>")
            html.append(f"<p><b>Period:</b> {date_from} to {date_to}<br>")
            html.append(f"<b>Category:</b> {cat_txt}</p>")

            # Summary
            html.append("<h3>Summary by Category</h3>")
            html.append(self._html_from_model(self.tbl_summary))
            html.append(f"<p><b>Grand Total:</b> {fmt_money(sum(float(r.get('total_amount') or 0.0) for r in self._rows_summary))}</p>")

            # Lines
            if self.model_lines.rowCount() > 0:
                html.append("<h3>Expense Lines</h3>")
                html.append(self._html_from_model(self.tbl_lines))

            self._render_pdf("\n".join(html), fn)

        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

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

    # Public hook for controller
    @Slot()
    def refresh_tab(self) -> None:
        self.refresh()

    # The controller expects a generic `refresh()` (for consistency with other tabs).
    @Slot()
    def refresh(self) -> None:
        self.refresh.__wrapped__(self) if hasattr(self.refresh, "__wrapped__") else self._refresh_impl()

    def _refresh_impl(self) -> None:
        # Idempotent implementation
        pass
