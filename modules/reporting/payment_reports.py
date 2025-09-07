# inventory_management/modules/reporting/payment_reports.py
from __future__ import annotations

import sqlite3
from typing import List, Optional

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot, QAbstractTableModel
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDateEdit,
    QPushButton,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QTableView,
)

# Prefer the app's fancy TableView if available; otherwise use Qt's.
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

# Money formatting: reuse app helper if present
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"

from ...database.repositories.reporting_repo import ReportingRepo


# ------------------------------ Small model: Date | Amount -------------------

class _DateAmountTableModel(QAbstractTableModel):
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
            return (Qt.AlignRight | Qt.AlignVCenter) if c == 1 else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ Payments Reports Tab ------------------------

class PaymentReportsTab(QWidget):
    """
    Payments reports (schema-safe):
      • Collections by cleared date (from sale_payments, clearing_state='cleared')
      • Disbursements by cleared date (from purchase_payments, clearing_state='cleared')

    All data comes from ReportingRepo:
      - sale_collections_by_day(date_from, date_to)
      - purchase_disbursements_by_day(date_from, date_to)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)

        # Keep raw rows for export
        self._rows_collect: List[dict] = []
        self._rows_disb: List[dict] = []

        self._build_ui()
        self._wire_signals()
        self.refresh()  # initial load

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Filter bar
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        today = QDate.currentDate()
        bar.addWidget(QLabel("From:"))
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        bar.addWidget(self.dt_from)

        bar.addSpacing(8)
        bar.addWidget(QLabel("To:"))
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)
        bar.addWidget(self.dt_to)

        bar.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_pdf = QPushButton("Export PDF…")
        self.btn_csv = QPushButton("Export CSV…")
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_pdf)
        bar.addWidget(self.btn_csv)

        root.addLayout(bar)

        # Splitter: top = Collections, bottom = Disbursements
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # Collections
        self.tbl_collect = _BaseTableView()
        self.tbl_collect.setSelectionMode(QTableView.NoSelection)
        self.tbl_collect.setSortingEnabled(False)
        self.model_collect = _DateAmountTableModel([])
        self.tbl_collect.setModel(self.model_collect)

        # Add a title above each table
        collect_wrap = QWidget()
        v1 = QVBoxLayout(collect_wrap)
        v1.setContentsMargins(0, 0, 0, 0)
        v1.setSpacing(4)
        self.lbl_collect_title = QLabel("<b>Collections (cleared)</b>")
        v1.addWidget(self.lbl_collect_title)
        v1.addWidget(self.tbl_collect)

        splitter.addWidget(collect_wrap)

        # Disbursements
        self.tbl_disb = _BaseTableView()
        self.tbl_disb.setSelectionMode(QTableView.NoSelection)
        self.tbl_disb.setSortingEnabled(False)
        self.model_disb = _DateAmountTableModel([])
        self.tbl_disb.setModel(self.model_disb)

        disb_wrap = QWidget()
        v2 = QVBoxLayout(disb_wrap)
        v2.setContentsMargins(0, 0, 0, 0)
        v2.setSpacing(4)
        self.lbl_disb_title = QLabel("<b>Disbursements (cleared)</b>")
        v2.addWidget(self.lbl_disb_title)
        v2.addWidget(self.tbl_disb)

        splitter.addWidget(disb_wrap)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Totals footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.lbl_collect_total = QLabel("Collections: 0.00")
        self.lbl_disb_total = QLabel("Disbursements: 0.00")
        foot.addWidget(self.lbl_collect_total)
        foot.addSpacing(16)
        foot.addWidget(self.lbl_disb_total)
        root.addLayout(foot)

    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_pdf.clicked.connect(self._on_export_pdf)
        self.btn_csv.clicked.connect(self._on_export_csv)
        self.dt_from.dateChanged.connect(lambda *_: self.refresh())
        self.dt_to.dateChanged.connect(lambda *_: self.refresh())

    # ---- Public API (optional: allows external filter application) ----
    def set_filters(self, filters: dict) -> None:
        """
        Optional integration point: if another screen calls set_filters(),
        we accept date_from/date_to (YYYY-MM-DD). Others are ignored.
        """
        def _apply_date(key: str, widget: QDateEdit):
            val = filters.get(key)
            if isinstance(val, str):
                try:
                    y, m, d = (int(x) for x in val.split("-"))
                    widget.setDate(QDate(y, m, d))
                except Exception:
                    pass

        _apply_date("date_from", self.dt_from)
        _apply_date("date_to", self.dt_to)

    # ---- Data refresh ----
    @Slot()
    def refresh(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")

        # Collections
        rows_c = []
        total_c = 0.0
        for r in self.repo.sale_collections_by_day(date_from, date_to):
            amt = float(r["amount"] or 0.0)
            rows_c.append({"date": str(r["date"]), "amount": amt})
            total_c += amt
        self._rows_collect = rows_c
        self.model_collect.set_rows(rows_c)

        # Disbursements
        rows_d = []
        total_d = 0.0
        for r in self.repo.purchase_disbursements_by_day(date_from, date_to):
            amt = float(r["amount"] or 0.0)
            rows_d.append({"date": str(r["date"]), "amount": amt})
            total_d += amt
        self._rows_disb = rows_d
        self.model_disb.set_rows(rows_d)

        # Totals + titles
        self.lbl_collect_total.setText(f"Collections: {fmt_money(total_c)}")
        self.lbl_disb_total.setText(f"Disbursements: {fmt_money(total_d)}")
        self.lbl_collect_title.setText(f"<b>Collections (cleared)</b> — {date_from} to {date_to}")
        self.lbl_disb_title.setText(f"<b>Disbursements (cleared)</b> — {date_from} to {date_to}")

        self._autosize(self.tbl_collect)
        self._autosize(self.tbl_disb)

    # ---- Export helpers ----
    def _on_export_pdf(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Payments to PDF", "payments.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            html = self._html_export()
            self._render_pdf(html, fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _on_export_csv(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Payments to CSV", "payments.csv", "CSV Files (*.csv)")
        if not fn:
            return
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                # Collections
                w.writerow(["Collections"])
                w.writerow(["Date", "Amount"])
                for r in self._rows_collect:
                    w.writerow([r["date"], f"{float(r['amount']):.2f}"])
                w.writerow([])
                # Disbursements
                w.writerow(["Disbursements"])
                w.writerow(["Date", "Amount"])
                for r in self._rows_disb:
                    w.writerow([r["date"], f"{float(r['amount']):.2f}"])
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export CSV:\n{e}")

    def _html_export(self) -> str:
        df = self.dt_from.date().toString("yyyy-MM-dd")
        dt = self.dt_to.date().toString("yyyy-MM-dd")

        def _table(rows: List[dict]) -> str:
            parts = ['<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>",
                     "<th>Date</th>", "<th>Amount</th>", "</tr></thead><tbody>"]
            for r in rows:
                parts.append("<tr>")
                parts.append(f"<td>{r.get('date','')}</td>")
                parts.append(f"<td style='text-align:right'>{fmt_money(r.get('amount'))}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            return "".join(parts)

        total_c = sum(float(r.get("amount") or 0.0) for r in self._rows_collect)
        total_d = sum(float(r.get("amount") or 0.0) for r in self._rows_disb)

        html = [
            "<h2>Payment Reports</h2>",
            f"<p><b>Period:</b> {df} to {dt}</p>",
            "<h3>Collections (cleared)</h3>",
            _table(self._rows_collect),
            f"<p><b>Total Collections:</b> {fmt_money(total_c)}</p>",
            "<h3>Disbursements (cleared)</h3>",
            _table(self._rows_disb),
            f"<p><b>Total Disbursements:</b> {fmt_money(total_d)}</p>",
        ]
        return "\n".join(html)

    def _render_pdf(self, html: str, filepath: str) -> None:
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter

        doc = QTextDocument()
        doc.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filepath)
        printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)

        doc.print_(printer)

    # ---- Misc helpers ----
    def _autosize(self, tv: QTableView) -> None:
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)
