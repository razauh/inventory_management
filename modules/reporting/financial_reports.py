# inventory_management/modules/reporting/financial_reports.py
from __future__ import annotations

import sqlite3
from typing import List, Optional, Dict

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot, QAbstractTableModel
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDateEdit,
    QPushButton,
    QTableView,
    QSplitter,
    QFileDialog,
    QMessageBox,
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

from .model import FinancialStatementTableModel
from ...database.repositories.reporting_repo import ReportingRepo


# ------------------------------ Logic ---------------------------------------


class FinancialReports:
    """
    Financial aggregates on top of ReportingRepo.

    - AR/AP snapshot as-of
    - Income Statement (Revenue/COGS/Expenses/Operating Income)
    - Cash view: collections/disbursements by cleared_date
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)

    # ---- helpers ----

    def _pk_col(self, table: str) -> str:
        """
        Return the primary key column name for a table, using PRAGMA table_info.
        Falls back to common patterns if PRAGMA doesn't flag a PK.
        """
        cols = list(self.conn.execute(f"PRAGMA table_info({table})"))
        # PRAGMA columns: (cid, name, type, notnull, dflt_value, pk)
        for cid, name, ctype, notnull, dflt, pk in cols:
            if pk:  # part of PK
                return str(name)
        names = [str(c[1]) for c in cols]
        # fallbacks
        for candidate in ("id", f"{table[:-1]}_id", f"{table}_id"):
            if candidate in names:
                return candidate
        return names[0] if names else "id"

    # ---- headline snapshot (AR/AP) ----

    def ar_ap_snapshot_as_of(self, as_of: str) -> dict:
        # AR = customers; AP = vendors. Use correct PKs from schema.
        ar_total = 0.0
        ap_total = 0.0

        # Customers
        for row in self.conn.execute("SELECT customer_id FROM customers"):
            cust_id = int(row["customer_id"])
            # reuse repo method that returns headers as-of; same semantics as vendor
            for h in self.repo.customer_headers_as_of(cust_id, as_of):
                remaining = float(h["total_amount"] or 0.0) - float(h["paid_amount"] or 0.0) - float(
                    h["advance_payment_applied"] or 0.0
                )
                if remaining > 0:
                    ar_total += remaining

        # Vendors
        for row in self.conn.execute("SELECT vendor_id FROM vendors"):
            ven_id = int(row["vendor_id"])
            for h in self.repo.vendor_headers_as_of(ven_id, as_of):
                remaining = float(h["total_amount"] or 0.0) - float(h["paid_amount"] or 0.0) - float(
                    h["advance_payment_applied"] or 0.0
                )
                if remaining > 0:
                    ap_total += remaining

        return {"AR_total_due": ar_total, "AP_total_due": ap_total}

    # ---- Income Statement ----

    def income_statement(self, date_from: str, date_to: str) -> Dict:
        """
        Returns:
          {
            'Revenue': float,
            'COGS': float,
            'Gross Profit': float,
            'Expenses': [{'category': str, 'amount': float}, ...],
            'total_expenses': float,
            'Operating Income': float
          }
        """
        revenue = float(self.repo.revenue_total(date_from, date_to))
        cogs = float(self.repo.cogs_total(date_from, date_to))
        gross = revenue - cogs

        exp_rows = self.repo.expenses_by_category(date_from, date_to)
        expenses: List[Dict] = []
        total_exp = 0.0
        for r in exp_rows:
            amt = float(r["total_amount"] or 0.0)
            expenses.append({"category": str(r["category_name"]), "amount": amt})
            total_exp += amt

        operating_income = gross - total_exp

        return {
            "Revenue": revenue,
            "COGS": cogs,
            "Gross Profit": gross,
            "Expenses": expenses,
            "total_expenses": total_exp,
            "Operating Income": operating_income,
        }

    # ---- Cash view ----

    def cash_collections_disbursements(self, date_from: str, date_to: str) -> Dict:
        """
        Returns:
          {
            'collections': [{'date': 'YYYY-MM-DD', 'amount': float}, ...],
            'total_collections': float,
            'disbursements': [{'date': 'YYYY-MM-DD', 'amount': float}, ...],
            'total_disbursements': float
          }
        """
        cols = []
        total_cols = 0.0
        for r in self.repo.sale_collections_by_day(date_from, date_to):
            amt = float(r["amount"] or 0.0)
            cols.append({"date": str(r["date"]), "amount": amt})
            total_cols += amt

        disb = []
        total_disb = 0.0
        for r in self.repo.purchase_disbursements_by_day(date_from, date_to):
            amt = float(r["amount"] or 0.0)
            disb.append({"date": str(r["date"]), "amount": amt})
            total_disb += amt

        return {
            "collections": cols,
            "total_collections": total_cols,
            "disbursements": disb,
            "total_disbursements": total_disb,
        }


# ------------------------------ Local 2-col model (Date, Amount) ------------


class _DateAmountTableModel(QAbstractTableModel):
    """
    Minimal 2-column table model for:
      Date | Amount
    """

    HEADERS = ("Date", "Amount")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    # Qt overrides
    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 2

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
                return fmt_money(row.get("amount"))
        if role == Qt.TextAlignmentRole:
            if c == 1:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None


# ------------------------------ UI Tab --------------------------------------


class FinancialReportsTab(QWidget):
    """
    Financial Reports UI:
      - Header: AR/AP snapshot (as-of)
      - Sub-tabs:
          1) Income Statement (date_from/date_to)
          2) Cash View (date_from/date_to)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logic = FinancialReports(conn)

        # Keep raw rows for potential exports
        self._rows_arap: List[dict] = []
        self._rows_stmt: List[dict] = []
        self._rows_collect: List[dict] = []
        self._rows_disb: List[dict] = []

        self._build_ui()
        self._wire_signals()
        self.refresh()  # initial load

    # ---- UI construction ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # --- Header: AR/AP snapshot ---
        hdr_bar = QHBoxLayout()
        hdr_bar.setContentsMargins(0, 0, 0, 0)
        hdr_bar.setSpacing(8)

        hdr_bar.addWidget(QLabel("As of:"))
        self.dt_asof = QDateEdit()
        self.dt_asof.setCalendarPopup(True)
        self.dt_asof.setDisplayFormat("yyyy-MM-dd")
        self.dt_asof.setDate(QDate.currentDate())
        hdr_bar.addWidget(self.dt_asof)

        hdr_bar.addStretch(1)

        self.btn_hdr_refresh = QPushButton("Refresh")
        self.btn_hdr_print = QPushButton("Print / PDF…")
        hdr_bar.addWidget(self.btn_hdr_refresh)
        hdr_bar.addWidget(self.btn_hdr_print)

        root.addLayout(hdr_bar)

        # Two-row table for AR/AP
        self.tbl_arap = _BaseTableView()
        self.tbl_arap.setSelectionMode(QTableView.NoSelection)
        self.tbl_arap.setSortingEnabled(False)

        self.model_arap = FinancialStatementTableModel([])
        self.tbl_arap.setModel(self.model_arap)
        root.addWidget(self.tbl_arap)

        # --- Sub-tabs ---
        self.subtabs = QTabWidget(self)
        root.addWidget(self.subtabs)

        # 1) Income Statement
        self.pg_stmt = QWidget()
        v1 = QVBoxLayout(self.pg_stmt)
        v1.setContentsMargins(8, 8, 8, 8)
        v1.setSpacing(6)

        bar1 = QHBoxLayout()
        bar1.addWidget(QLabel("From:"))
        self.dt_stmt_from = QDateEdit()
        self.dt_stmt_from.setCalendarPopup(True)
        self.dt_stmt_from.setDisplayFormat("yyyy-MM-dd")
        today = QDate.currentDate()
        self.dt_stmt_from.setDate(QDate(today.year(), today.month(), 1))
        bar1.addWidget(self.dt_stmt_from)

        bar1.addSpacing(8)
        bar1.addWidget(QLabel("To:"))
        self.dt_stmt_to = QDateEdit()
        self.dt_stmt_to.setCalendarPopup(True)
        self.dt_stmt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_stmt_to.setDate(today)
        bar1.addWidget(self.dt_stmt_to)

        bar1.addStretch(1)
        self.btn_stmt_refresh = QPushButton("Refresh")
        self.btn_stmt_print = QPushButton("Print / PDF…")
        bar1.addWidget(self.btn_stmt_refresh)
        bar1.addWidget(self.btn_stmt_print)

        v1.addLayout(bar1)

        self.tbl_stmt = _BaseTableView()
        self.tbl_stmt.setSelectionMode(QTableView.NoSelection)
        self.tbl_stmt.setSortingEnabled(False)
        self.model_stmt = FinancialStatementTableModel([])
        self.tbl_stmt.setModel(self.model_stmt)
        v1.addWidget(self.tbl_stmt)

        self.subtabs.addTab(self.pg_stmt, "Income Statement")

        # 2) Cash View
        self.pg_cash = QWidget()
        v2 = QVBoxLayout(self.pg_cash)
        v2.setContentsMargins(8, 8, 8, 8)
        v2.setSpacing(6)

        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("From:"))
        self.dt_cash_from = QDateEdit()
        self.dt_cash_from.setCalendarPopup(True)
        self.dt_cash_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_cash_from.setDate(QDate(today.year(), today.month(), 1))
        bar2.addWidget(self.dt_cash_from)

        bar2.addSpacing(8)
        bar2.addWidget(QLabel("To:"))
        self.dt_cash_to = QDateEdit()
        self.dt_cash_to.setCalendarPopup(True)
        self.dt_cash_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_cash_to.setDate(today)
        bar2.addWidget(self.dt_cash_to)

        bar2.addStretch(1)
        self.btn_cash_refresh = QPushButton("Refresh")
        self.btn_cash_print = QPushButton("Print / PDF…")
        bar2.addWidget(self.btn_cash_refresh)
        bar2.addWidget(self.btn_cash_print)

        v2.addLayout(bar2)

        splitter = QSplitter(Qt.Vertical)
        # collections
        self.tbl_collect = _BaseTableView()
        self.tbl_collect.setSelectionMode(QTableView.NoSelection)
        self.tbl_collect.setSortingEnabled(False)
        self.model_collect = _DateAmountTableModel([])
        self.tbl_collect.setModel(self.model_collect)
        splitter.addWidget(self.tbl_collect)

        # disbursements
        self.tbl_disb = _BaseTableView()
        self.tbl_disb.setSelectionMode(QTableView.NoSelection)
        self.tbl_disb.setSortingEnabled(False)
        self.model_disb = _DateAmountTableModel([])
        self.tbl_disb.setModel(self.model_disb)
        splitter.addWidget(self.tbl_disb)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        v2.addWidget(splitter)

        # Totals footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.lbl_collect_total = QLabel("Collections: 0.00")
        self.lbl_disb_total = QLabel("Disbursements: 0.00")
        foot.addWidget(self.lbl_collect_total)
        foot.addSpacing(16)
        foot.addWidget(self.lbl_disb_total)
        v2.addLayout(foot)

        self.subtabs.addTab(self.pg_cash, "Cash View")

    def _wire_signals(self) -> None:
        # Header
        self.btn_hdr_refresh.clicked.connect(self.refresh_ar_ap)
        self.btn_hdr_print.clicked.connect(self._on_print_ar_ap)
        self.dt_asof.dateChanged.connect(lambda *_: self.refresh_ar_ap())

        # Income statement
        self.btn_stmt_refresh.clicked.connect(self.refresh_stmt)
        self.btn_stmt_print.clicked.connect(self._on_print_stmt)
        self.dt_stmt_from.dateChanged.connect(lambda *_: self.refresh_stmt())
        self.dt_stmt_to.dateChanged.connect(lambda *_: self.refresh_stmt())

        # Cash view
        self.btn_cash_refresh.clicked.connect(self.refresh_cash)
        self.btn_cash_print.clicked.connect(self._on_print_cash)
        self.dt_cash_from.dateChanged.connect(lambda *_: self.refresh_cash())
        self.dt_cash_to.dateChanged.connect(lambda *_: self.refresh_cash())

    # ---- Refresh orchestration ----

    @Slot()
    def refresh(self) -> None:
        self.refresh_ar_ap()
        self.refresh_stmt()
        self.refresh_cash()

    # Header AR/AP
    @Slot()
    def refresh_ar_ap(self) -> None:
        as_of = self.dt_asof.date().toString("yyyy-MM-dd")
        snap = self.logic.ar_ap_snapshot_as_of(as_of)
        rows = [
            {"line_item": "Accounts Receivable (AR)", "amount": snap["AR_total_due"], "is_total": True},
            {"line_item": "Accounts Payable (AP)", "amount": snap["AP_total_due"], "is_total": True},
        ]
        self.model_arap.set_rows(rows)
        self._autosize(self.tbl_arap)

    # Income Statement
    @Slot()
    def refresh_stmt(self) -> None:
        date_from = self.dt_stmt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_stmt_to.date().toString("yyyy-MM-dd")
        stmt = self.logic.income_statement(date_from, date_to)

        rows: List[dict] = []
        # Main lines
        rows.append({"line_item": "Revenue", "amount": stmt["Revenue"]})
        rows.append({"line_item": "COGS", "amount": stmt["COGS"]})
        rows.append({"line_item": "Gross Profit", "amount": stmt["Gross Profit"], "is_total": True})

        # Expenses section
        rows.append({"line_item": "Expenses", "amount": None, "is_header": True})
        for e in stmt["Expenses"]:
            rows.append({"line_item": f"  {e['category']}", "amount": e["amount"]})
        rows.append({"line_item": "Total Expenses", "amount": stmt["total_expenses"], "is_total": True})

        # Operating income
        rows.append({"line_item": "Operating Income", "amount": stmt["Operating Income"], "is_total": True})

        self.model_stmt.set_rows(rows)
        self._autosize(self.tbl_stmt)

    # Cash View
    @Slot()
    def refresh_cash(self) -> None:
        date_from = self.dt_cash_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_cash_to.date().toString("yyyy-MM-dd")

        data = self.logic.cash_collections_disbursements(date_from, date_to)

        self._rows_collect = data["collections"]
        self._rows_disb = data["disbursements"]

        self.model_collect.set_rows(self._rows_collect)
        self.model_disb.set_rows(self._rows_disb)

        total_cols = float(data["total_collections"] or 0.0)
        total_disb = float(data["total_disbursements"] or 0.0)
        self.lbl_collect_total.setText(f"Collections: {fmt_money(total_cols)}")
        self.lbl_disb_total.setText(f"Disbursements: {fmt_money(total_disb)}")

        self._autosize(self.tbl_collect)
        self._autosize(self.tbl_disb)

    # ---- Printing / PDF ----

    def _on_print_ar_ap(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export AR/AP to PDF", "ar_ap_snapshot.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            as_of = self.dt_asof.date().toString("yyyy-MM-dd")
            html = [f"<h2>AR/AP Snapshot</h2>", f"<p><b>As of:</b> {as_of}</p>", self._html_from_model(self.tbl_arap)]
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _on_print_stmt(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Income Statement to PDF", "income_statement.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            date_from = self.dt_stmt_from.date().toString("yyyy-MM-dd")
            date_to = self.dt_stmt_to.date().toString("yyyy-MM-dd")
            html = [
                "<h2>Income Statement</h2>",
                f"<p><b>Period:</b> {date_from} to {date_to}</p>",
                self._html_from_model(self.tbl_stmt),
            ]
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _on_print_cash(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Cash View to PDF", "cash_view.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            date_from = self.dt_cash_from.date().toString("yyyy-MM-dd")
            date_to = self.dt_cash_to.date().toString("yyyy-MM-dd")
            total_cols = sum(float(r.get("amount") or 0.0) for r in self._rows_collect)
            total_disb = sum(float(r.get("amount") or 0.0) for r in self._rows_disb)

            html = [
                "<h2>Cash View</h2>",
                f"<p><b>Period:</b> {date_from} to {date_to}</p>",
                "<h3>Collections</h3>",
                self._html_from_model(self.tbl_collect),
                f"<p><b>Total Collections:</b> {fmt_money(total_cols)}</p>",
                "<h3>Disbursements</h3>",
                self._html_from_model(self.tbl_disb),
                f"<p><b>Total Disbursements:</b> {fmt_money(total_disb)}</p>",
            ]
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
