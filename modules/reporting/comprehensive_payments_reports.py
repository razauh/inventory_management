# inventory_management/modules/reporting/comprehensive_payments_reports.py
from __future__ import annotations

import sqlite3
from typing import List, Optional, Dict, Any

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QComboBox, 
    QPushButton, QSplitter, QTabWidget, QTableView, QFrame,
    QFileDialog, QMessageBox, QAbstractItemView
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

# Reporting repo
from ...database.repositories.reporting_repo import ReportingRepo
from .csv_export import safe_csv_row
from .date_range import validate_date_range
from .large_results import maybe_resize_columns


# ------------------------------ Data Models -----------------------------------
from PySide6.QtCore import QAbstractTableModel, QModelIndex

class _BasePaymentsTableModel(QAbstractTableModel):
    """Base model for payment data tables"""
    
    def __init__(
        self,
        headers: Optional[List[str]] = None,
        field_map: Optional[List[str]] = None,
        rows: Optional[List[Dict]] = None,
        money_fields: Optional[List[str]] = None,
        right_fields: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._rows: List[Dict] = rows or []
        self._headers: List[str] = headers or []
        self._field_map: List[str] = field_map or []
        self._money_fields = set(money_fields or [])
        self._right_fields = set(right_fields or [])
        
    def set_rows(self, rows: List[Dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()
        
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)
        
    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers) if self._headers else 0
        
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and section < len(self._headers):
            return self._headers[section]
        return None
        
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._rows) or c >= len(self._headers):
            return None
            
        row_data = self._rows[r]
        field = self._field_map[c] if c < len(self._field_map) else self._headers[c]
        value = row_data.get(field)
        
        if role == Qt.DisplayRole:
            if field in self._money_fields:
                return fmt_money(value)
            return str(value) if value is not None else ""
        elif role == Qt.TextAlignmentRole:
            if field in self._money_fields or field in self._right_fields:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None


class _PaymentSummaryTableModel(_BasePaymentsTableModel):
    """Model for payment summary by status"""
    def __init__(self, rows: Optional[List[Dict]] = None, parent=None):
        super().__init__(
            headers=["Status", "Payment Type", "Count", "Cash Amount"],
            field_map=["status", "type", "count", "total_amount"],
            rows=rows,
            money_fields=["total_amount"],
            right_fields=["count"],
            parent=parent,
        )
        
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if role == Qt.BackgroundRole and index.column() == 0 and index.isValid():  # Status column
            row = index.row()
            status = self._rows[row].get("status", "").lower()
            from PySide6.QtGui import QColor
            if status == "cleared":
                return QColor(144, 238, 144)  # Light green
            elif status == "bounced":
                return QColor(255, 182, 193)  # Light red
            elif status == "pending":
                return QColor(255, 255, 224)  # Light yellow
            elif status == "posted":
                return QColor(211, 211, 211)  # Light gray
        return super().data(index, role)


class _DetailedPaymentsTableModel(_BasePaymentsTableModel):
    """Model for detailed payment listings"""
    def __init__(self, rows: Optional[List[Dict]] = None, parent=None):
        super().__init__(
            headers=["Date", "Type", "Cash Amount", "Method", "Status", "Document ID", "Notes"],
            field_map=["date", "type", "amount", "method", "status", "doc_id", "notes"],
            rows=rows,
            money_fields=["amount"],
            parent=parent,
        )


# ------------------------------ Logic Layer -----------------------------------
class ComprehensivePaymentReports:
    """Logic layer for comprehensive payment reports"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)

    @staticmethod
    def _date_basis_label(date_basis: str) -> str:
        return "Cash date" if date_basis == "cash" else "Posting date"

    @staticmethod
    def _date_expr(alias: str, date_basis: str) -> str:
        if date_basis == "cash":
            return (
                f"CASE WHEN {alias}.clearing_state = 'cleared' "
                f"AND {alias}.cleared_date IS NOT NULL AND {alias}.cleared_date != '' "
                f"THEN {alias}.cleared_date ELSE {alias}.date END"
            )
        return f"{alias}.date"

    @staticmethod
    def _cash_direction_totals(rows: List[Dict[str, Any]]) -> tuple[float, float, float, float]:
        inflow = 0.0
        outflow = 0.0
        refunds = 0.0
        for row in rows:
            amount = float(row.get("amount") or row.get("total_amount") or 0.0)
            kind = str(row.get("type") or "").strip().lower()
            if kind == "disbursement":
                outflow += amount
            elif kind == "vendor refund":
                refunds += amount
                inflow += amount
            else:
                inflow += amount
        net = inflow - outflow
        return inflow, outflow, refunds, net
    
    def payments_summary_by_status(
        self, 
        date_from: str, 
        date_to: str, 
        payment_type: Optional[str] = None,  # 'collection' or 'disbursement' or None for both
        date_basis: str = "posting",
    ) -> List[Dict]:
        """Get payment summary grouped by status"""
        date_expr = self._date_expr("p", date_basis)
        where_clause = f"WHERE {date_expr} >= ? AND {date_expr} <= ?"
        params = [date_from, date_to]
        
        query = f"""
        SELECT 
            p.clearing_state AS status,
            'Collection' AS type,
            COUNT(*) AS count,
            COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
        FROM sale_payments p
        {where_clause}
        GROUP BY p.clearing_state
        
        UNION ALL
        
        SELECT 
            p.clearing_state AS status,
            'Disbursement' AS type,
            COUNT(*) AS count,
            COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
        FROM purchase_payments p
        {where_clause}
        GROUP BY p.clearing_state

        UNION ALL

        SELECT 
            p.clearing_state AS status,
            'Vendor Refund' AS type,
            COUNT(*) AS count,
            COALESCE(SUM(CAST(p.amount AS REAL)), 0.0) AS total_amount
        FROM purchase_refunds p
        {where_clause}
        GROUP BY p.clearing_state

        ORDER BY status, type
        """
        
        rows = list(self.conn.execute(query, params * 3))
        result = []
        for r in rows:
            result.append({
                "status": str(r["status"]),
                "type": str(r["type"]),
                "count": int(r["count"]),
                "total_amount": float(r["total_amount"])
            })
        return result
    
    def unprocessed_payments(
        self, 
        date_from: str, 
        date_to: str, 
        payment_type: Optional[str] = None,
        date_basis: str = "posting",
    ) -> List[Dict]:
        """Get payments that are not cleared (posted/pending)"""
        date_expr = self._date_expr("p", date_basis)
        where_clause = (
            f"WHERE {date_expr} >= ? AND {date_expr} <= ? "
            "AND p.clearing_state IN ('posted', 'pending')"
        )
        params = [date_from, date_to]
        
        query = f"""
        SELECT 
            {date_expr} AS date,
            'Collection' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.sale_id AS doc_id,
            p.notes
        FROM sale_payments p
        {where_clause}
        
        UNION ALL
        
        SELECT 
            {date_expr} AS date,
            'Disbursement' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_payments p
        {where_clause}

        UNION ALL

        SELECT 
            {date_expr} AS date,
            'Vendor Refund' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_refunds p
        {where_clause}
        ORDER BY date DESC
        """.format(date_expr=date_expr)
        
        rows = list(self.conn.execute(query, params * 3))
        result = []
        for r in rows:
            result.append({
                "date": str(r["date"]),
                "type": str(r["type"]),
                "amount": float(r["amount"]),
                "method": str(r["method"]),
                "status": str(r["status"]),
                "doc_id": str(r["doc_id"]),
                "notes": str(r["notes"]) if r["notes"] else ""
            })
        return result
    
    def all_payments_detailed(
        self, 
        date_from: str, 
        date_to: str, 
        payment_type: Optional[str] = None,
        date_basis: str = "posting",
    ) -> List[Dict]:
        """Get all payments with full details"""
        date_expr = self._date_expr("p", date_basis)
        where_clause = f"WHERE {date_expr} >= ? AND {date_expr} <= ?"
        params = [date_from, date_to]
        
        query = f"""
        SELECT 
            {date_expr} AS date,
            'Collection' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.sale_id AS doc_id,
            p.notes
        FROM sale_payments p
        {where_clause}
        
        UNION ALL
        
        SELECT 
            {date_expr} AS date,
            'Disbursement' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_payments p
        {where_clause}

        UNION ALL

        SELECT 
            {date_expr} AS date,
            'Vendor Refund' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_refunds p
        {where_clause}
        ORDER BY date DESC, type
        """.format(date_expr=date_expr)
        
        rows = list(self.conn.execute(query, params * 3))
        result = []
        for r in rows:
            result.append({
                "date": str(r["date"]),
                "type": str(r["type"]),
                "amount": float(r["amount"]),
                "method": str(r["method"]),
                "status": str(r["status"]),
                "doc_id": str(r["doc_id"]),
                "notes": str(r["notes"]) if r["notes"] else ""
            })
        return result


# ------------------------------ UI Tab ----------------------------------------
class ComprehensivePaymentReportsTab(QWidget):
    MAX_ROWS = 1000

    """Comprehensive Payment Reports UI"""
    
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.logic = ComprehensivePaymentReports(conn)
        
        # Data storage
        self._rows_summary: List[Dict] = []
        self._rows_unprocessed: List[Dict] = []
        self._rows_detailed: List[Dict] = []
        
        self._build_ui()
        self._wire_signals()
        self.refresh()
    
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        
        # Filter bar
        filter_layout = QHBoxLayout()
        
        filter_layout.addWidget(QLabel("From:"))
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        today = QDate.currentDate()
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        filter_layout.addWidget(self.dt_from)
        
        filter_layout.addWidget(QLabel("To:"))
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setDate(today)
        filter_layout.addWidget(self.dt_to)

        filter_layout.addWidget(QLabel("Date basis:"))
        self.cmb_date_basis = QComboBox()
        self.cmb_date_basis.addItem("Posting date", userData="posting")
        self.cmb_date_basis.addItem("Cash date", userData="cash")
        filter_layout.addWidget(self.cmb_date_basis)
        
        filter_layout.addStretch(1)
        
        self.btn_refresh = QPushButton("Refresh")
        filter_layout.addWidget(self.btn_refresh)
        
        self.btn_export = QPushButton("Export All")
        filter_layout.addWidget(self.btn_export)
        
        layout.addLayout(filter_layout)
        
        # Tab widget for different reports
        self.tabs = QTabWidget()
        
        # Summary by status tab
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        
        self.tbl_summary = _BaseTableView()
        self.tbl_summary.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_summary.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_summary = _PaymentSummaryTableModel([])
        self.tbl_summary.setModel(self.model_summary)
        
        self.lbl_summary_title = QLabel("<b>Payments Summary by Status</b>")
        summary_layout.addWidget(self.lbl_summary_title)
        summary_layout.addWidget(self.tbl_summary)
        self.tabs.addTab(summary_widget, "By Status")
        
        # Unprocessed payments tab
        unprocessed_widget = QWidget()
        unprocessed_layout = QVBoxLayout(unprocessed_widget)
        
        self.tbl_unprocessed = _BaseTableView()
        self.tbl_unprocessed.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_unprocessed.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_unprocessed = _DetailedPaymentsTableModel([])
        self.tbl_unprocessed.setModel(self.model_unprocessed)
        
        self.lbl_unprocessed_title = QLabel("<b>Unprocessed Payments (Posted/Pending)</b>")
        unprocessed_layout.addWidget(self.lbl_unprocessed_title)
        unprocessed_layout.addWidget(self.tbl_unprocessed)
        self.tabs.addTab(unprocessed_widget, "Unprocessed")
        
        # All payments tab
        all_widget = QWidget()
        all_layout = QVBoxLayout(all_widget)
        
        self.tbl_detailed = _BaseTableView()
        self.tbl_detailed.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_detailed.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_detailed = _DetailedPaymentsTableModel([])
        self.tbl_detailed.setModel(self.model_detailed)
        
        self.lbl_detailed_title = QLabel("<b>All Payments</b>")
        all_layout.addWidget(self.lbl_detailed_title)
        all_layout.addWidget(self.tbl_detailed)
        self.tabs.addTab(all_widget, "All Payments")
        
        layout.addWidget(self.tabs)
        
        # Footer with totals
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        self.lbl_basis = QLabel("Date basis: Posting date")
        self.lbl_inflow_total = QLabel("Inflows: 0.00")
        self.lbl_outflow_total = QLabel("Outflows: 0.00")
        self.lbl_refund_total = QLabel("Refunds: 0.00")
        self.lbl_net_total = QLabel("Net Cash: 0.00")
        footer_layout.addWidget(self.lbl_basis)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(self.lbl_inflow_total)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(self.lbl_outflow_total)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(self.lbl_refund_total)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(self.lbl_net_total)
        layout.addLayout(footer_layout)
    
    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self._export_all)
        self.dt_from.dateChanged.connect(self.refresh)
        self.dt_to.dateChanged.connect(self.refresh)
        self.cmb_date_basis.currentIndexChanged.connect(lambda *_: self.refresh())
    
    @Slot()
    def refresh(self) -> None:
        if not self._validate_date_ranges():
            return
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        date_basis = str(self.cmb_date_basis.currentData() or "posting")
        basis_label = ComprehensivePaymentReports._date_basis_label(date_basis)

        with self.logic.repo.read_snapshot():
            rows_summary = self.logic.payments_summary_by_status(date_from, date_to, date_basis=date_basis)[: self.MAX_ROWS]

            rows_unprocessed = self.logic.unprocessed_payments(date_from, date_to, date_basis=date_basis)[: self.MAX_ROWS]

            rows_detailed = self.logic.all_payments_detailed(date_from, date_to, date_basis=date_basis)[: self.MAX_ROWS]

        self._rows_summary = rows_summary
        self._rows_unprocessed = rows_unprocessed
        self._rows_detailed = rows_detailed

        self.model_summary.set_rows(rows_summary)
        self.model_unprocessed.set_rows(rows_unprocessed)
        self.model_detailed.set_rows(rows_detailed)

        self.lbl_basis.setText(f"Date basis: {basis_label}")
        inflow_total, outflow_total, refund_total, net_total = self._cash_direction_totals(rows_detailed)
        self.lbl_inflow_total.setText(f"Inflows: {fmt_money(inflow_total)}")
        self.lbl_outflow_total.setText(f"Outflows: {fmt_money(outflow_total)}")
        self.lbl_refund_total.setText(f"Refunds: {fmt_money(refund_total)}")
        self.lbl_net_total.setText(f"Net Cash: {fmt_money(net_total)}")
        self.lbl_summary_title.setText(f"<b>Payments Summary by Status</b> — {date_from} to {date_to} ({basis_label})")
        self.lbl_unprocessed_title.setText(f"<b>Unprocessed Payments (Posted/Pending)</b> — {date_from} to {date_to} ({basis_label})")
        self.lbl_detailed_title.setText(f"<b>All Payments</b> — {date_from} to {date_to} ({basis_label})")

        # Resize columns
        self._resize_table(self.tbl_summary)
        self._resize_table(self.tbl_unprocessed)
        self._resize_table(self.tbl_detailed)
    
    def _resize_table(self, table: QTableView) -> None:
        maybe_resize_columns(table)
    
    def _export_all(self) -> None:
        """Export all payment data to CSV"""
        if not self._validate_date_ranges():
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export All Payment Reports", "comprehensive_payments.csv", "CSV Files (*.csv)"
        )
        if not fn:
            return
        
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                
                writer.writerow(["Report", "Comprehensive Payments"])
                writer.writerow(safe_csv_row(["Date basis", self.lbl_basis.text().replace("Date basis: ", "")]))
                writer.writerow(safe_csv_row(["Period", f"{self.dt_from.date().toString('yyyy-MM-dd')} to {self.dt_to.date().toString('yyyy-MM-dd')}"]))
                writer.writerow([])
                
                # Write summary data
                writer.writerow(["PAYMENT SUMMARY BY STATUS"])
                writer.writerow(["Status", "Type", "Count", "Cash Amount"])
                for row in self._rows_summary:
                    writer.writerow(safe_csv_row([
                        row.get("status", ""),
                        row.get("type", ""),
                        row.get("count", 0),
                        f"{row.get('total_amount', 0.0):.2f}"
                    ]))
                
                writer.writerow([])  # Empty row

                inflow_total, outflow_total, refund_total, net_total = self._cash_direction_totals(self._rows_detailed)
                writer.writerow(["CASH DIRECTION TOTALS"])
                writer.writerow(["Inflows", f"{inflow_total:.2f}"])
                writer.writerow(["Outflows", f"{outflow_total:.2f}"])
                writer.writerow(["Refunds", f"{refund_total:.2f}"])
                writer.writerow(["Net Cash", f"{net_total:.2f}"])
                writer.writerow([])
                
                # Write unprocessed payments
                writer.writerow(["UNPROCESSED PAYMENTS"])
                writer.writerow(["Date", "Type", "Cash Amount", "Method", "Status", "Document ID", "Notes"])
                for row in self._rows_unprocessed:
                    writer.writerow(safe_csv_row([
                        row.get("date", ""),
                        row.get("type", ""),
                        f"{row.get('amount', 0.0):.2f}",
                        row.get("method", ""),
                        row.get("status", ""),
                        row.get("doc_id", ""),
                        row.get("notes", "")
                    ]))
                
                writer.writerow([])  # Empty row
                
                # Write all payments
                writer.writerow(["ALL PAYMENTS"])
                writer.writerow(["Date", "Type", "Cash Amount", "Method", "Status", "Document ID", "Notes"])
                for row in self._rows_detailed:
                    writer.writerow(safe_csv_row([
                        row.get("date", ""),
                        row.get("type", ""),
                        f"{row.get('amount', 0.0):.2f}",
                        row.get("method", ""),
                        row.get("status", ""),
                        row.get("doc_id", ""),
                        row.get("notes", "")
                    ]))
            
            QMessageBox.information(self, "Export Complete", f"Data exported to {fn}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", f"Could not export data:\n{e}")

    def _validate_date_ranges(self) -> bool:
        return validate_date_range(self, self.dt_from.date(), self.dt_to.date(), "Payment period")
