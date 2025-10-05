# inventory_management/modules/reporting/enhanced_payment_reports.py
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
    QPushButton,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QTableView,
    QTabWidget,
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


# ------------------------------ Small model: Date | Amount | Status -------------------
from PySide6.QtCore import QAbstractTableModel, QModelIndex

class _DateAmountStatusTableModel(QAbstractTableModel):
    HEADERS = ("Date", "Amount", "Status", "Type")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._rows) or c >= 4:
            return None
        row = self._rows[r]

        if role == Qt.DisplayRole:
            if c == 0:
                return row.get("date", "")
            elif c == 1:
                return fmt_money(row.get("amount"))
            elif c == 2:
                return row.get("status", "")
            elif c == 3:
                return row.get("type", "")
        elif role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c == 1 else (Qt.AlignLeft | Qt.AlignVCenter)
        elif role == Qt.BackgroundRole and c == 2:
            status = row.get("status", "").lower()
            from PySide6.QtGui import QColor
            if status == "cleared":
                return QColor(144, 238, 144)  # Light green
            elif status == "bounced":
                return QColor(255, 182, 193)  # Light red
            elif status == "pending":
                return QColor(255, 255, 224)  # Light yellow
            elif status == "posted":
                return QColor(211, 211, 211)  # Light gray
        return None


# ------------------------------ All-Payments Reports Tab ------------------------
class EnhancedPaymentReportsTab(QWidget):
    """
    Enhanced Payments reports showing complete payment picture:
      • All payments by status (not just cleared)
      • All payments by date (not just cleared)
      • Uncleared payments summary  
      • Payment status timeline
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)

        # Keep raw rows for export
        self._rows_all_payments: List[dict] = []
        self._rows_by_status: List[dict] = []
        self._rows_uncleared: List[dict] = []

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

        # Tab widget for different payment views
        self.tabs = QTabWidget()

        # All Payments Tab
        all_payments_widget = QWidget()
        all_layout = QVBoxLayout(all_payments_widget)

        self.tbl_all = _BaseTableView()
        self.tbl_all.setSelectionMode(QTableView.NoSelection)
        self.tbl_all.setSortingEnabled(False)
        self.model_all = _DateAmountStatusTableModel([])
        self.tbl_all.setModel(self.model_all)

        self.lbl_all_title = QLabel("<b>All Payments</b>")
        all_layout.addWidget(self.lbl_all_title)
        all_layout.addWidget(self.tbl_all)
        self.tabs.addTab(all_payments_widget, "All Payments")

        # By Status Tab
        by_status_widget = QWidget()
        status_layout = QVBoxLayout(by_status_widget)

        self.tbl_status = _BaseTableView()
        self.tbl_status.setSelectionMode(QTableView.NoSelection)
        self.tbl_status.setSortingEnabled(False)
        self.model_status = _DateAmountStatusTableModel([])
        self.tbl_status.setModel(self.model_status)

        self.lbl_status_title = QLabel("<b>Payments by Status</b>")
        status_layout.addWidget(self.lbl_status_title)
        status_layout.addWidget(self.tbl_status)
        self.tabs.addTab(by_status_widget, "By Status")

        # Uncleared Payments Tab  
        uncleared_widget = QWidget()
        uncleared_layout = QVBoxLayout(uncleared_widget)

        self.tbl_uncleared = _BaseTableView()
        self.tbl_uncleared.setSelectionMode(QTableView.NoSelection)
        self.tbl_uncleared.setSortingEnabled(False)
        self.model_uncleared = _DateAmountStatusTableModel([])
        self.tbl_uncleared.setModel(self.model_uncleared)

        self.lbl_uncleared_title = QLabel("<b>Uncleared Payments</b>")
        uncleared_layout.addWidget(self.lbl_uncleared_title)
        uncleared_layout.addWidget(self.tbl_uncleared)
        self.tabs.addTab(uncleared_widget, "Uncleared")

        root.addWidget(self.tabs, 1)

        # Totals footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.lbl_all_total = QLabel("Total: 0.00")
        self.lbl_uncleared_total = QLabel("Uncleared: 0.00")
        foot.addWidget(self.lbl_all_total)
        foot.addSpacing(16)
        foot.addWidget(self.lbl_uncleared_total)
        root.addLayout(foot)

    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_pdf.clicked.connect(self._on_export_pdf)
        self.btn_csv.clicked.connect(self._on_export_csv)
        self.dt_from.dateChanged.connect(lambda *_: self.refresh())
        self.dt_to.dateChanged.connect(lambda *_: self.refresh())

    # ---- Data refresh ----
    @Slot()
    def refresh(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")

        # Get all payments (collections and disbursements)
        all_rows = []
        
        # Collections (sale payments)
        for r in self.repo.conn.execute("""
            SELECT sp.date, sp.cleared_date, sp.amount, sp.clearing_state as state
            FROM sale_payments sp
            WHERE sp.date >= ? AND sp.date <= ?
            ORDER BY sp.date
        """, (date_from, date_to)):
            all_rows.append({
                "date": r["cleared_date"] if r["state"] == "cleared" else r["date"],
                "amount": float(r["amount"] or 0.0),
                "status": str(r["state"]),
                "type": "Collection"
            })

        # Disbursements (purchase payments)
        for r in self.repo.conn.execute("""
            SELECT pp.date, pp.cleared_date, pp.amount, pp.clearing_state as state
            FROM purchase_payments pp
            WHERE pp.date >= ? AND pp.date <= ?
            ORDER BY pp.date
        """, (date_from, date_to)):
            all_rows.append({
                "date": r["cleared_date"] if r["state"] == "cleared" else r["date"],
                "amount": float(r["amount"] or 0.0),
                "status": str(r["state"]),
                "type": "Disbursement"
            })

        # All payments table
        self._rows_all_payments = all_rows
        self.model_all.set_rows(all_rows)
        
        # Calculate totals
        all_total = sum(float(r.get("amount", 0.0)) for r in all_rows)
        uncleared_rows = [r for r in all_rows if r.get("status") not in ["cleared"]]
        uncleared_total = sum(float(r.get("amount", 0.0)) for r in uncleared_rows)

        # Update UI
        self.lbl_all_total.setText(f"Total: {fmt_money(all_total)}")
        self.lbl_uncleared_total.setText(f"Uncleared: {fmt_money(uncleared_total)}")
        
        # All payments title
        self.lbl_all_title.setText(f"<b>All Payments</b> — {date_from} to {date_to}")
        
        # By status table (same as all, but we could group differently)
        self.model_status.set_rows(all_rows)
        
        # Uncleared table
        self._rows_uncleared = uncleared_rows
        self.model_uncleared.set_rows(uncleared_rows)
        
        # Update titles
        self.lbl_status_title.setText(f"<b>Payments by Status</b> — {date_from} to {date_to}")
        self.lbl_uncleared_title.setText(f"<b>Uncleared Payments</b> — {date_from} to {date_to}")

        # Auto-size tables
        self._autosize(self.tbl_all)
        self._autosize(self.tbl_status)
        self._autosize(self.tbl_uncleared)

    # ---- Export helpers ----
    def _on_export_pdf(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Payments to PDF", "enhanced_payments.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            html = self._html_export()
            self._render_pdf(html, fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _on_export_csv(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Payments to CSV", "enhanced_payments.csv", "CSV Files (*.csv)")
        if not fn:
            return
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["All Payments"])
                w.writerow(["Date", "Amount", "Status", "Type"])
                for r in self._rows_all_payments:
                    w.writerow([r["date"], f"{float(r['amount']):.2f}", r["status"], r["type"]])
                w.writerow([])
                w.writerow(["Uncleared Payments"])
                w.writerow(["Date", "Amount", "Status", "Type"])
                for r in self._rows_uncleared:
                    w.writerow([r["date"], f"{float(r['amount']):.2f}", r["status"], r["type"]])
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export CSV:\n{e}")

    def _html_export(self) -> str:
        df = self.dt_from.date().toString("yyyy-MM-dd")
        dt = self.dt_to.date().toString("yyyy-MM-dd")

        def _table(title: str, rows: List[dict]) -> str:
            if not rows:
                return f"<h3>{title}</h3><p>No data</p>"
                
            parts = [f'<h3>{title}</h3>', '<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>",
                     "<th>Date</th>", "<th>Amount</th>", "<th>Status</th>", "<th>Type</th>", "</tr></thead><tbody>"]
            for r in rows:
                parts.append("<tr>")
                parts.append(f"<td>{r.get('date','')}</td>")
                parts.append(f"<td style='text-align:right'>{fmt_money(r.get('amount'))}</td>")
                parts.append(f"<td>{r.get('status','')}</td>")
                parts.append(f"<td>{r.get('type','')}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            return "".join(parts)

        total_all = sum(float(r.get("amount") or 0.0) for r in self._rows_all_payments)
        total_uncleared = sum(float(r.get("amount") or 0.0) for r in self._rows_uncleared)

        html = [
            "<h2>Enhanced Payment Reports</h2>",
            f"<p><b>Period:</b> {df} to {dt}</p>",
            _table("All Payments", self._rows_all_payments),
            f"<p><b>Total Payments:</b> {fmt_money(total_all)}</p>",
            _table("Uncleared Payments", self._rows_uncleared),
            f"<p><b>Total Uncleared:</b> {fmt_money(total_uncleared)}</p>",
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