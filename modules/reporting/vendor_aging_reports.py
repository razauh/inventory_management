# inventory_management/modules/reporting/vendor_aging_reports.py
from __future__ import annotations

import sqlite3
from datetime import datetime, date
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDateEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QFileDialog,
    QMessageBox,
)

# Prefer the app’s styled table view if present
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

# Money formatting helper (reuse app helper if available)
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"

from .model import AgingSnapshotTableModel, OpenInvoicesTableModel
from ...database.repositories.reporting_repo import ReportingRepo


def _days_between(older_yyyy_mm_dd: str, asof_yyyy_mm_dd: str) -> int:
    """Inclusive day span: (as_of - older_date)."""
    try:
        d1 = datetime.strptime(older_yyyy_mm_dd, "%Y-%m-%d").date()
        d2 = datetime.strptime(asof_yyyy_mm_dd, "%Y-%m-%d").date()
        return (d2 - d1).days
    except Exception:
        return 0


class VendorAgingTab(QWidget):
    """
    Vendor Aging:
      - Top: filter bar (As of, Refresh, Export)
      - Splitter:
          * Top table: per-vendor aging buckets (Total Due, 0–30, 31–60, 61–90, 91+, Available Credit)
          * Bottom table: open purchase headers for the selected vendor
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.repo = ReportingRepo(conn)

        # Keep raw rows for export/drilldown
        self._aging_rows: List[Dict] = []
        self._open_rows: List[Dict] = []

        self._build_ui()
        self._wire()
        self.refresh()

    # ---------------------------- UI ---------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Filter bar
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        bar.addWidget(QLabel("As of:"))
        self.dt_asof = QDateEdit()
        self.dt_asof.setCalendarPopup(True)
        self.dt_asof.setDisplayFormat("yyyy-MM-dd")
        self.dt_asof.setDate(QDate.currentDate())
        bar.addWidget(self.dt_asof)

        bar.addStretch(1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_export_pdf = QPushButton("Export PDF…")
        self.btn_export_csv = QPushButton("Export CSV…")
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_export_pdf)
        bar.addWidget(self.btn_export_csv)

        root.addLayout(bar)

        # Splitter: Aging (top) + Open Items (bottom)
        split = QSplitter(Qt.Vertical)
        root.addWidget(split, 1)

        # Aging grid
        self.tbl_aging = _BaseTableView()
        self.tbl_aging.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_aging.setSelectionMode(QTableView.SingleSelection)
        self.tbl_aging.setSortingEnabled(True)
        self.model_aging = AgingSnapshotTableModel([])
        self.tbl_aging.setModel(self.model_aging)
        split.addWidget(self.tbl_aging)

        # Open items
        self.tbl_open = _BaseTableView()
        self.tbl_open.setSelectionBehavior(QTableView.SelectRows)
        self.tbl_open.setSelectionMode(QTableView.NoSelection)
        self.tbl_open.setSortingEnabled(True)
        self.model_open = OpenInvoicesTableModel([])
        self.tbl_open.setModel(self.model_open)
        split.addWidget(self.tbl_open)

        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)

    def _wire(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        self.dt_asof.dateChanged.connect(lambda *_: self.refresh())

        # Selection → load open headers
        # We'll connect in refresh() after model reset to avoid stale selection models.

    # ---------------------------- Data / Refresh ----------------------

    @Slot()
    def refresh(self) -> None:
        """Rebuild the aging snapshot and re-bind selection."""
        as_of = self.dt_asof.date().toString("yyyy-MM-dd")
        self._aging_rows = self._build_vendor_aging(as_of)
        self.model_aging.set_rows(self._aging_rows)
        self._autosize(self.tbl_aging)

        # (Re)connect selection listener safely
        sel = self.tbl_aging.selectionModel()
        if sel:
            try:
                sel.selectionChanged.disconnect(self._on_aging_selection_changed)
            except Exception:
                pass
            sel.selectionChanged.connect(self._on_aging_selection_changed)

        # Auto-select first vendor if available
        if self.model_aging.rowCount() > 0:
            self.tbl_aging.selectRow(0)
            self._load_open_for_row(0, as_of)
        else:
            self.model_open.set_rows([])
            self._autosize(self.tbl_open)

    def _build_vendor_aging(self, as_of: str) -> List[Dict]:
        """
        Build rows for AgingSnapshotTableModel:
          keys: name, total_due, b_0_30, b_31_60, b_61_90, b_91_plus, available_credit
        """
        rows: List[Dict] = []
        # Fetch vendors (id + display name)
        vendors = list(self.conn.execute(
            "SELECT vendor_id, COALESCE(name, CAST(vendor_id AS TEXT)) AS name "
            "FROM vendors ORDER BY name COLLATE NOCASE"
        ))

        for v in vendors:
            vid = int(v["vendor_id"])
            vname = str(v["name"] or vid)

            total_due = 0.0
            b_0_30 = b_31_60 = b_61_90 = b_91_plus = 0.0

            for h in self.repo.vendor_headers_as_of(vid, as_of):
                total_amount = float(h["total_amount"] or 0.0)
                paid_amount = float(h["paid_amount"] or 0.0)
                adv_applied = float(h["advance_payment_applied"] or 0.0)
                remaining = total_amount - paid_amount - adv_applied
                if remaining <= 0:
                    continue
                days = _days_between(str(h["date"]), as_of)
                total_due += remaining
                if days <= 30:
                    b_0_30 += remaining
                elif days <= 60:
                    b_31_60 += remaining
                elif days <= 90:
                    b_61_90 += remaining
                else:
                    b_91_plus += remaining

            if total_due == 0.0:
                # Still include the vendor (common accounting practice varies);
                # here we keep zero rows out to reduce noise. Comment next line to include zeros.
                continue

            avail_credit = float(self.repo.vendor_credit_as_of(vid, as_of) or 0.0)

            rows.append({
                "vendor_id": vid,          # keep internal id for drill-down
                "name": vname,
                "total_due": total_due,
                "b_0_30": b_0_30,
                "b_31_60": b_31_60,
                "b_61_90": b_61_90,
                "b_91_plus": b_91_plus,
                "available_credit": avail_credit,
            })

        # Sort by name ASC (model sorts visually too; keep deterministic data order)
        rows.sort(key=lambda r: r["name"].lower())
        return rows

    def _load_open_for_row(self, row_index: int, as_of: str) -> None:
        """Populate bottom table with open purchases for the selected vendor."""
        if row_index < 0 or row_index >= len(self._aging_rows):
            self.model_open.set_rows([])
            self._autosize(self.tbl_open)
            return

        ven_id = int(self._aging_rows[row_index]["vendor_id"])
        opens: List[Dict] = []

        for h in self.repo.vendor_headers_as_of(ven_id, as_of):
            total_amount = float(h["total_amount"] or 0.0)
            paid_amount = float(h["paid_amount"] or 0.0)
            adv_applied = float(h["advance_payment_applied"] or 0.0)
            remaining = total_amount - paid_amount - adv_applied
            if remaining <= 0:
                continue
            hdr_date = str(h["date"])
            opens.append({
                "doc_no": str(h["doc_no"]),
                "date": hdr_date,
                "total": total_amount,
                "paid": paid_amount,
                "advance_applied": adv_applied,
                "remaining": remaining,
                "days_outstanding": max(0, _days_between(hdr_date, as_of)),
            })

        # Most recent first helps users
        opens.sort(key=lambda r: (r["date"], r["doc_no"]), reverse=True)
        self._open_rows = opens
        self.model_open.set_rows(opens)
        self._autosize(self.tbl_open)

    # ---------------------------- Signals --------------------------------

    @Slot()
    def _on_aging_selection_changed(self, *_args) -> None:
        """Selection in aging table changed → reload open items for that vendor."""
        as_of = self.dt_asof.date().toString("yyyy-MM-dd")
        sel = self.tbl_aging.selectionModel()
        if not sel:
            return
        indexes = sel.selectedRows()
        if not indexes:
            self.model_open.set_rows([])
            self._autosize(self.tbl_open)
            return
        row = indexes[0].row()
        self._load_open_for_row(row, as_of)

    # ---------------------------- Export ---------------------------------

    def _html_from_table(self, tv: QTableView, title: str) -> str:
        m = tv.model()
        if m is None:
            return "<p>(No data)</p>"
        cols = m.columnCount()
        rows = m.rowCount()
        parts = [f"<h3>{title}</h3>", '<table border="1" cellspacing="0" cellpadding="4">', "<thead><tr>"]
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
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter

        doc = QTextDocument()
        doc.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filepath)
        printer.setPageMargins(12, 12, 12, 12, QPrinter.Point)

        doc.print_(printer)

    @Slot()
    def _on_export_pdf(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Vendor Aging to PDF", "vendor_aging.pdf", "PDF Files (*.pdf)")
        if not fn:
            return
        try:
            as_of = self.dt_asof.date().toString("yyyy-MM-dd")
            html = [
                "<h2>Vendor Aging</h2>",
                f"<p><b>As of:</b> {as_of}</p>",
                self._html_from_table(self.tbl_aging, "Aging Summary"),
                self._html_from_table(self.tbl_open, "Open Purchases (Selected Vendor)"),
            ]
            self._render_pdf("\n".join(html), fn)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export PDF:\n{e}")

    @Slot()
    def _on_export_csv(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Export Vendor Aging to CSV", "vendor_aging.csv", "CSV Files (*.csv)")
        if not fn:
            return
        try:
            import csv

            # Export both grids: first aging, then open items (if any)
            with open(fn, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Aging header
                m = self.tbl_aging.model()
                if m and m.columnCount() > 0:
                    writer.writerow(["Vendor Aging"])
                    hdr = [m.headerData(c, Qt.Horizontal, Qt.DisplayRole) for c in range(m.columnCount())]
                    writer.writerow(hdr)
                    for r in range(m.rowCount()):
                        row_vals = [m.index(r, c).data(Qt.DisplayRole) for c in range(m.columnCount())]
                        writer.writerow(row_vals)
                    writer.writerow([])

                # Open items for selected vendor
                m2 = self.tbl_open.model()
                if m2 and m2.columnCount() > 0 and m2.rowCount() > 0:
                    writer.writerow(["Open Purchases (Selected Vendor)"])
                    hdr2 = [m2.headerData(c, Qt.Horizontal, Qt.DisplayRole) for c in range(m2.columnCount())]
                    writer.writerow(hdr2)
                    for r in range(m2.rowCount()):
                        row_vals2 = [m2.index(r, c).data(Qt.DisplayRole) for c in range(m2.columnCount())]
                        writer.writerow(row_vals2)
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Export failed", f"Could not export CSV:\n{e}")

    # ---------------------------- Helpers --------------------------------

    def _autosize(self, tv: QTableView) -> None:
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)

    # Optional API for the launcher/filters (safe to ignore if not used)
    def set_filters(self, filters: Dict) -> None:
        """
        Recognized:
          - as_of: 'YYYY-MM-DD'
        """
        as_of = filters.get("as_of")
        if isinstance(as_of, str):
            try:
                y, m, d = (int(x) for x in as_of.split("-"))
                self.dt_asof.setDate(QDate(y, m, d))
            except Exception:
                pass
