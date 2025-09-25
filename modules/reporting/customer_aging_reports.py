# inventory_management/modules/reporting/customer_aging_reports.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

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
)

# Prefer the app's table widget if available; fallback to vanilla QTableView if not.
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover - graceful fallback
    _BaseTableView = QTableView

from .model import (
    AgingSnapshotTableModel,
    OpenInvoicesTableModel,
)
from ...database.repositories.reporting_repo import ReportingRepo

# Try to reuse app-wide money formatter
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"


# ------------------------------ Logic ---------------------------------------


@dataclass
class _Customer:
    id: int
    name: str


def _parse_iso(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


class CustomerAgingReports:
    """
    Pure computation for Customer Aging built on top of ReportingRepo.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = ReportingRepo(conn)

    def _list_customers(self) -> List[_Customer]:
        """
        Minimal reader for customers (id + name) used by the UI 'All' mode.
        Adjust column names here if your customer table differs.
        """
        self.conn.row_factory = sqlite3.Row
        rows = list(self.conn.execute("SELECT id, name FROM customers ORDER BY name COLLATE NOCASE"))
        return [_Customer(int(r["id"]), str(r["name"])) for r in rows]

    def compute_aging_snapshot(
        self,
        as_of: str,
        buckets: Tuple[Tuple[int, int], ...] = ((0, 30), (31, 60), (61, 90), (91, 10_000)),
        include_credit_column: bool = True,
        customer_id: Optional[int] = None,
    ) -> List[dict]:
        """
        Returns one row per customer:
          {
            "customer_id": int,
            "name": str,
            "total_due": float,
            "b0_30": float,
            "b31_60": float,
            "b61_90": float,
            "b91_plus": float,
            "available_credit": float
          }
        Only documents with positive remaining are considered.
        """
        asof = _parse_iso(as_of)

        # Resolve which customers to include
        customers: List[_Customer]
        if customer_id is not None:
            # Fetch just the single customer (id + name)
            self.conn.row_factory = sqlite3.Row
            r = self.conn.execute("SELECT id, name FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if not r:
                return []
            customers = [_Customer(int(r["id"]), str(r["name"]))]
        else:
            customers = self._list_customers()

        out: List[dict] = []
        for cust in customers:
            headers = self.repo.customer_headers_as_of(cust.id, as_of)
            b_totals = [0.0, 0.0, 0.0, 0.0]
            total_due = 0.0

            for h in headers:
                doc_date = _parse_iso(str(h["date"]))
                remaining = float(h["total_amount"] or 0.0) - float(h["paid_amount"] or 0.0) - float(
                    h["advance_payment_applied"] or 0.0
                )
                # Only consider positive outstanding
                if remaining <= 0.0:
                    continue

                age_days = (asof - doc_date).days
                # Bucket by age
                for i, (lo, hi) in enumerate(buckets):
                    if lo <= age_days <= hi:
                        b_totals[i] += remaining
                        break
                total_due += remaining

            # Skip rows with no outstanding at all (common practice for aging)
            if total_due <= 0.0:
                continue

            credit = 0.0
            if include_credit_column:
                credit = self.repo.customer_credit_as_of(cust.id, as_of) or 0.0

            out.append(
                {
                    "customer_id": cust.id,
                    "name": cust.name,
                    "total_due": total_due,
                    "b0_30": b_totals[0],
                    "b31_60": b_totals[1],
                    "b61_90": b_totals[2],
                    "b91_plus": b_totals[3],
                    "available_credit": credit,
                }
            )

        # Sort by Name ascending for stable presentation
        out.sort(key=lambda r: r["name"].lower() if r.get("name") else "")
        return out

    def list_open_invoices(self, customer_id: int, as_of: str) -> List[dict]:
        """
        Returns open sales documents for a customer as of date (remaining > 0), with:
          {
            "doc_no": str,
            "date": "YYYY-MM-DD",
            "total_amount": float,
            "paid_amount": float,
            "advance_payment_applied": float,
            "remaining": float,
            "days_outstanding": int
          }
        """
        headers = self.repo.customer_headers_as_of(customer_id, as_of)
        asof = _parse_iso(as_of)
        rows: List[dict] = []
        for h in headers:
            total = float(h["total_amount"] or 0.0)
            paid = float(h["paid_amount"] or 0.0)
            adv = float(h["advance_payment_applied"] or 0.0)
            remaining = total - paid - adv
            if remaining <= 0.0:
                continue
            d = str(h["date"])
            days = (asof - _parse_iso(d)).days
            rows.append(
                {
                    "doc_no": str(h["doc_no"]),
                    "date": d,
                    "total_amount": total,
                    "paid_amount": paid,
                    "advance_payment_applied": adv,
                    "remaining": remaining,
                    "days_outstanding": int(days),
                }
            )
        # Oldest first for natural review
        rows.sort(key=lambda r: (r["date"], r["doc_no"]))
        return rows


# ------------------------------ UI Tab --------------------------------------


class CustomerAgingTab(QWidget):
    """
    UI wrapper for Customer Aging:
      - Toolbar: As-of date, Customer (All / one), Refresh, Print/PDF
      - Top table: Aging snapshot (AgingSnapshotTableModel)
      - Bottom table: Open invoices for selected row (OpenInvoicesTableModel)
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logic = CustomerAgingReports(conn)

        self._rows_snapshot: List[dict] = []  # keep raw rows for selection drill-down
        self._rows_invoices: List[dict] = []

        self._build_ui()
        self._wire_signals()

    # ---- UI construction ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        bar.addWidget(QLabel("As of:"))
        self.dt_asof = QDateEdit()
        self.dt_asof.setCalendarPopup(True)
        self.dt_asof.setDisplayFormat("yyyy-MM-dd")
        self.dt_asof.setDate(QDate.currentDate())
        bar.addWidget(self.dt_asof)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Customer:"))
        self.cmb_customer = QComboBox()
        self.cmb_customer.setMinimumWidth(240)
        bar.addWidget(self.cmb_customer)

        bar.addStretch(1)

        self.btn_refresh = QPushButton("Refresh")
        bar.addWidget(self.btn_refresh)

        self.btn_print = QPushButton("Print / PDF…")
        bar.addWidget(self.btn_print)

        root.addLayout(bar)

        # Split tables
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        # Top (snapshot)
        self.tbl_snapshot = _BaseTableView()
        self.tbl_snapshot.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_snapshot.setSelectionMode(QTableView.SingleSelection)
        self.tbl_snapshot.setSortingEnabled(False)
        split.addWidget(self.tbl_snapshot)

        # Bottom (open invoices)
        self.tbl_invoices = _BaseTableView()
        self.tbl_invoices.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_invoices.setSelectionMode(QTableView.SingleSelection)
        self.tbl_invoices.setSortingEnabled(False)
        split.addWidget(self.tbl_invoices)

        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        root.addWidget(split)

        # Models
        self.model_snapshot = AgingSnapshotTableModel([])
        self.model_invoices = OpenInvoicesTableModel([])

        self.tbl_snapshot.setModel(self.model_snapshot)
        self.tbl_invoices.setModel(self.model_invoices)

        # Populate customer combo
        self._reload_customers()

    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_print.clicked.connect(self._on_print_pdf)

        sel = self.tbl_snapshot.selectionModel()
        if sel:
            sel.selectionChanged.connect(self._on_snapshot_selection)  # pragma: no cover (Qt wiring)

        self.dt_asof.dateChanged.connect(lambda *_: self.refresh())
        self.cmb_customer.currentIndexChanged.connect(lambda *_: self.refresh())

    def _reload_customers(self) -> None:
        self.cmb_customer.blockSignals(True)
        self.cmb_customer.clear()
        self.cmb_customer.addItem("All Customers", None)
        try:
            for c in self.logic._list_customers():
                self.cmb_customer.addItem(c.name, c.id)
        except Exception:
            # In the unlikely event of a lookup failure, retain "All Customers" only
            pass
        self.cmb_customer.blockSignals(False)

    # ---- Behavior ----

    @Slot()
    def refresh(self) -> None:
        as_of = self.dt_asof.date().toString("yyyy-MM-dd")
        cust_id = self.cmb_customer.currentData()
        # Compute snapshot
        self._rows_snapshot = self.logic.compute_aging_snapshot(
            as_of=as_of,
            buckets=((0, 30), (31, 60), (61, 90), (91, 10_000)),
            include_credit_column=True,
            customer_id=cust_id if isinstance(cust_id, int) else None,
        )
        self.model_snapshot.set_rows(self._rows_snapshot)
        self._autosize(self.tbl_snapshot)

        # If a single customer is selected in the combo, pre-fill invoices
        if isinstance(cust_id, int):
            self._rows_invoices = self.logic.list_open_invoices(cust_id, as_of)
            self.model_invoices.set_rows(self._rows_invoices)
            self._autosize(self.tbl_invoices)
        else:
            # Clear invoices until a row is selected
            self.model_invoices.set_rows([])
            self._autosize(self.tbl_invoices)

        # Reselect first row to trigger details
        if self.model_snapshot.rowCount() > 0:
            self.tbl_snapshot.selectRow(0)
            self._load_invoices_for_row(0)

    def _autosize(self, tv: QTableView) -> None:
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)

    @Slot()
    def _on_print_pdf(self) -> None:
        """
        Export the current snapshot (and, if present, the open invoices) to a single PDF.
        """
        # Ask destination
        fn, _ = QFileDialog.getSaveFileName(self, "Export to PDF", "customer_aging.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            # Build a simple HTML doc
            as_of = self.dt_asof.date().toString("yyyy-MM-dd")
            cust_txt = self.cmb_customer.currentText()
            html = []
            html.append(f"<h2>Customer Aging (as of {as_of})</h2>")
            html.append(f"<p><b>Customer Filter:</b> {cust_txt}</p>")

            # Snapshot table
            html.append("<h3>Snapshot</h3>")
            html.append(self._html_from_model(self.tbl_snapshot))

            # Invoices if any
            if self.model_invoices.rowCount() > 0:
                html.append("<h3>Open Invoices</h3>")
                html.append(self._html_from_model(self.tbl_invoices))

            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    def _html_from_model(self, tv: QTableView) -> str:
        """
        Create a lightweight HTML table from the current model/selection.
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
        Render the supplied HTML to PDF using QTextDocument and QPrinter.
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

    def _on_snapshot_selection(self, *_):
        # selection changed signal (guard if selection model recreated)
        index = self.tbl_snapshot.currentIndex()
        if not index.isValid():
            return
        self._load_invoices_for_row(index.row())

    def _load_invoices_for_row(self, row: int) -> None:
        if not (0 <= row < len(self._rows_snapshot)):
            return
        as_of = self.dt_asof.date().toString("yyyy-MM-dd")
        cust_id = self._rows_snapshot[row].get("customer_id")
        if cust_id is None:
            self.model_invoices.set_rows([])
            return
        self._rows_invoices = self.logic.list_open_invoices(int(cust_id), as_of)
        self.model_invoices.set_rows(self._rows_invoices)
        self._autosize(self.tbl_invoices)

    # Public hook the controller calls on tab change
    @Slot()
    def refresh(self) -> None:
        self.refresh.__wrapped__(self) if hasattr(self.refresh, "__wrapped__") else self._refresh_impl()

    # Keep actual logic separate (helps if decorators are added later)
    def _refresh_impl(self) -> None:
        # Idempotent implementation
        pass

