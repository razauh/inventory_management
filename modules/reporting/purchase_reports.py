# inventory_management/modules/reporting/purchase_reports.py
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


# ------------------------------ Models --------------------------------------

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


class _OpenPurchasesTableModel(QAbstractTableModel):
    HEADERS = ("Doc No", "Date", "Total", "Paid", "Advance Applied", "Remaining")

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
        return 0 if parent.isValid() else 6

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
                return row.get("doc_no", "")
            if c == 1:
                return row.get("date", "")
            if c == 2:
                return fmt_money(row.get("total"))
            if c == 3:
                return fmt_money(row.get("paid"))
            if c == 4:
                return fmt_money(row.get("advance_applied"))
            if c == 5:
                return fmt_money(row.get("remaining"))
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c in (2, 3, 4, 5) else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ Purchases Reports Tab -----------------------

class PurchaseReportsTab(QWidget):
    """
    Purchase reports (schema-safe, no extra assumptions):

      • Purchases by day (sum of purchases.total_amount within date range)
      • Open purchases list (remaining = total_amount - paid_amount - advance_payment_applied)

    Uses only columns already referenced elsewhere in the app:
      purchases(purchase_id, vendor_id, date, total_amount, paid_amount, advance_payment_applied)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

        # Data caches for export
        self._rows_by_day: List[dict] = []
        self._rows_open: List[dict] = []

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

        # Split: top = Purchases by Day, bottom = Open Purchases
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # Purchases by Day
        self.tbl_by_day = _BaseTableView()
        self.tbl_by_day.setSelectionMode(QTableView.NoSelection)
        self.tbl_by_day.setSortingEnabled(False)
        self.model_by_day = _DateAmountTableModel([])
        self.tbl_by_day.setModel(self.model_by_day)

        wrap1 = QWidget()
        v1 = QVBoxLayout(wrap1)
        v1.setContentsMargins(0, 0, 0, 0)
        v1.setSpacing(4)
        self.lbl_by_day_title = QLabel("<b>Purchases by Day</b>")
        v1.addWidget(self.lbl_by_day_title)
        v1.addWidget(self.tbl_by_day)

        splitter.addWidget(wrap1)

        # Open Purchases
        self.tbl_open = _BaseTableView()
        self.tbl_open.setSelectionMode(QTableView.NoSelection)
        self.tbl_open.setSortingEnabled(False)
        self.model_open = _OpenPurchasesTableModel([])
        self.tbl_open.setModel(self.model_open)

        wrap2 = QWidget()
        v2 = QVBoxLayout(wrap2)
        v2.setContentsMargins(0, 0, 0, 0)
        v2.setSpacing(4)
        self.lbl_open_title = QLabel("<b>Open Purchases</b>")
        v2.addWidget(self.lbl_open_title)
        v2.addWidget(self.tbl_open)

        splitter.addWidget(wrap2)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Totals footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.lbl_total_purchases = QLabel("Total Purchases: 0.00")
        self.lbl_total_remaining = QLabel("Total Remaining (Open): 0.00")
        foot.addWidget(self.lbl_total_purchases)
        foot.addSpacing(16)
        foot.addWidget(self.lbl_total_remaining)
        root.addLayout(foot)

    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_pdf.clicked.connect(self._on_export_pdf)
        self.btn_csv.clicked.connect(self._on_export_csv)
        self.dt_from.dateChanged.connect(lambda *_: self.refresh())
        self.dt_to.dateChanged.connect(lambda *_: self.refresh())

    # ---- Public API (optional) ----
    def set_filters(self, filters: dict) -> None:
        """
        Accept date_from/date_to if provided (YYYY-MM-DD). Others are ignored.
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
        df = self.dt_from.date().toString("yyyy-MM-dd")
        dt = self.dt_to.date().toString("yyyy-MM-dd")

        # 1) Purchases by Day (sum of total_amount)
        sql_by_day = """
            SELECT
              p.date AS date,
              COALESCE(SUM(CAST(p.total_amount AS REAL)), 0.0) AS amount
            FROM purchases p
            WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
            GROUP BY p.date
            ORDER BY DATE(p.date)
        """
        rows_day = []
        total_purch = 0.0
        for r in self.conn.execute(sql_by_day, (df, dt)):
            amt = float(r["amount"] or 0.0)
            rows_day.append({"date": str(r["date"]), "amount": amt})
            total_purch += amt
        self._rows_by_day = rows_day
        self.model_by_day.set_rows(rows_day)

        # 2) Open Purchases (remaining > 0)
        sql_open = """
            SELECT
              p.purchase_id AS doc_no,
              p.date        AS date,
              COALESCE(CAST(p.total_amount AS REAL), 0.0)            AS total_amount,
              COALESCE(CAST(p.paid_amount AS REAL), 0.0)             AS paid_amount,
              COALESCE(CAST(p.advance_payment_applied AS REAL), 0.0) AS adv
            FROM purchases p
            WHERE DATE(p.date) BETWEEN DATE(?) AND DATE(?)
            ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        rows_open = []
        total_remaining = 0.0
        for r in self.conn.execute(sql_open, (df, dt)):
            total = float(r["total_amount"] or 0.0)
            paid = float(r["paid_amount"] or 0.0)
            adv = float(r["adv"] or 0.0)
            remaining = total - paid - adv
            if remaining > 0.0000001:  # treat tiny negatives as zero
                rows_open.append({
                    "doc_no": str(r["doc_no"]),
                    "date": str(r["date"]),
                    "total": total,
                    "paid": paid,
                    "advance_applied": adv,
                    "remaining": remaining,
                })
                total_remaining += remaining
        self._rows_open = rows_open
        self.model_open.set_rows(rows_open)

        # Titles + totals
        self.lbl_by_day_title.setText(f"<b>Purchases by Day</b> — {df} to {dt}")
        self.lbl_open_title.setText(f"<b>Open Purchases</b> — {df} to {dt}")
        self.lbl_total_purchases.setText(f"Total Purchases: {fmt_money(total_purch)}")
        self.lbl_total_remaining.setText(f"Total Remaining (Open): {fmt_money(total_remaining)}")

        self._autosize(self.tbl_by_day)
        self._autosize(self.tbl_open)

    # ---- Export helpers ----
    def _on_export_pdf(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Purchase Reports to PDF", "purchase_reports.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            html = self._html_export()
            self._render_pdf(html, fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _on_export_csv(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Purchase Reports to CSV", "purchase_reports.csv", "CSV Files (*.csv)")
        if not fn:
            return
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                # Purchases by Day
                w.writerow(["Purchases by Day"])
                w.writerow(["Date", "Amount"])
                for r in self._rows_by_day:
                    w.writerow([r["date"], f"{float(r['amount']):.2f}"])
                w.writerow([])

                # Open Purchases
                w.writerow(["Open Purchases"])
                w.writerow(["Doc No", "Date", "Total", "Paid", "Advance Applied", "Remaining"])
                for r in self._rows_open:
                    w.writerow([
                        r["doc_no"], r["date"],
                        f"{float(r['total']):.2f}",
                        f"{float(r['paid']):.2f}",
                        f"{float(r['advance_applied']):.2f}",
                        f"{float(r['remaining']):.2f}",
                    ])
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export CSV:\n{e}")

    def _html_export(self) -> str:
        df = self.dt_from.date().toString("yyyy-MM-dd")
        dt = self.dt_to.date().toString("yyyy-MM-dd")

        def _table(headers: List[str], rows: List[List[str]]) -> str:
            parts = ['<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>"]
            for h in headers:
                parts.append(f"<th>{h}</th>")
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{cell}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            return "".join(parts)

        total_purch = sum(float(r.get("amount") or 0.0) for r in self._rows_by_day)
        total_rem = sum(float(r.get("remaining") or 0.0) for r in self._rows_open)

        html = [
            "<h2>Purchase Reports</h2>",
            f"<p><b>Period:</b> {df} to {dt}</p>",
            "<h3>Purchases by Day</h3>",
            _table(["Date", "Amount"], [[r["date"], fmt_money(r["amount"])] for r in self._rows_by_day]),
            f"<p><b>Total Purchases:</b> {fmt_money(total_purch)}</p>",
            "<h3>Open Purchases</h3>",
            _table(
                ["Doc No", "Date", "Total", "Paid", "Advance Applied", "Remaining"],
                [[
                    r["doc_no"], r["date"],
                    fmt_money(r["total"]),
                    fmt_money(r["paid"]),
                    fmt_money(r["advance_applied"]),
                    fmt_money(r["remaining"]),
                ] for r in self._rows_open],
            ),
            f"<p><b>Total Remaining (Open):</b> {fmt_money(total_rem)}</p>",
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
