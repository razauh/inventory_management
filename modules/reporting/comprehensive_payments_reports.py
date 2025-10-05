# inventory_management/modules/reporting/comprehensive_payments_reports.py
from __future__ import annotations

import sqlite3
from typing import List, Optional, Dict, Any

from PySide6.QtCore import Qt, QDate, QModelIndex, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QComboBox, 
    QPushButton, QSplitter, QTabWidget, QTableView, QFrame, QHeaderView,
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


# ------------------------------ Data Models -----------------------------------
from PySide6.QtCore import QAbstractTableModel, QModelIndex

class _BasePaymentsTableModel(QAbstractTableModel):
    """Base model for payment data tables"""
    
    def __init__(self, rows: Optional[List[Dict]] = None, parent=None):
        super().__init__(parent)
        self._rows: List[Dict] = rows or []
        self._headers: List[str] = []
        
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
        header = self._headers[c]
        value = row_data.get(header)
        
        if role == Qt.DisplayRole:
            if header in ['amount', 'total_amount']:
                return fmt_money(value)
            return str(value) if value is not None else ""
        elif role == Qt.TextAlignmentRole:
            if header in ['amount', 'total_amount']:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None


class _PaymentSummaryTableModel(_BasePaymentsTableModel):
    """Model for payment summary by status"""
    def __init__(self, rows: Optional[List[Dict]] = None, parent=None):
        super().__init__(rows, parent)
        self._headers = ["Status", "Payment Type", "Count", "Total Amount"]
        
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
        super().__init__(rows, parent)
        self._headers = ["Date", "Type", "Amount", "Method", "Status", "Document ID", "Notes"]


# ------------------------------ Logic Layer -----------------------------------
class ComprehensivePaymentReports:
    """Logic layer for comprehensive payment reports"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.repo = ReportingRepo(conn)
    
    def payments_summary_by_status(
        self, 
        date_from: str, 
        date_to: str, 
        payment_type: Optional[str] = None  # 'collection' or 'disbursement' or None for both
    ) -> List[Dict]:
        """Get payment summary grouped by status"""
        where_clause = "WHERE p.date >= ? AND p.date <= ?"
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
        ORDER BY status, type
        """
        
        rows = list(self.conn.execute(query, params + params))
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
        payment_type: Optional[str] = None
    ) -> List[Dict]:
        """Get payments that are not cleared (posted/pending)"""
        where_clause = "WHERE p.date >= ? AND p.date <= ? AND p.clearing_state IN ('posted', 'pending')"
        params = [date_from, date_to]
        
        query = f"""
        SELECT 
            p.date,
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
            p.date,
            'Disbursement' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_payments p
        {where_clause}
        ORDER BY date DESC
        """
        
        rows = list(self.conn.execute(query, params + params))
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
        payment_type: Optional[str] = None
    ) -> List[Dict]:
        """Get all payments with full details"""
        where_clause = "WHERE p.date >= ? AND p.date <= ?"
        params = [date_from, date_to]
        
        query = f"""
        SELECT 
            p.date,
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
            p.date,
            'Disbursement' AS type,
            p.amount,
            p.method,
            p.clearing_state AS status,
            p.purchase_id AS doc_id,
            p.notes
        FROM purchase_payments p
        {where_clause}
        ORDER BY date DESC, type
        """
        
        rows = list(self.conn.execute(query, params + params))
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
        
        summary_layout.addWidget(QLabel("<b>Payments Summary by Status</b>"))
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
        
        unprocessed_layout.addWidget(QLabel("<b>Unprocessed Payments (Posted/Pending)</b>"))
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
        
        all_layout.addWidget(QLabel("<b>All Payments</b>"))
        all_layout.addWidget(self.tbl_detailed)
        self.tabs.addTab(all_widget, "All Payments")
        
        layout.addWidget(self.tabs)
        
        # Footer with totals
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        self.lbl_summary_total = QLabel("Summary Total: 0.00")
        self.lbl_unprocessed_total = QLabel("Unprocessed Total: 0.00")
        footer_layout.addWidget(self.lbl_summary_total)
        footer_layout.addWidget(self.lbl_unprocessed_total)
        layout.addLayout(footer_layout)
    
    def _wire_signals(self) -> None:
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self._export_all)
        self.dt_from.dateChanged.connect(self.refresh)
        self.dt_to.dateChanged.connect(self.refresh)
    
    @Slot()
    def refresh(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        
        # Load summary by status
        self._rows_summary = self.logic.payments_summary_by_status(date_from, date_to)
        self.model_summary.set_rows(self._rows_summary)
        summary_total = sum(r.get("total_amount", 0.0) for r in self._rows_summary)
        self.lbl_summary_total.setText(f"Summary Total: {fmt_money(summary_total)}")
        
        # Load unprocessed payments
        self._rows_unprocessed = self.logic.unprocessed_payments(date_from, date_to)
        self.model_unprocessed.set_rows(self._rows_unprocessed)
        unprocessed_total = sum(r.get("amount", 0.0) for r in self._rows_unprocessed)
        self.lbl_unprocessed_total.setText(f"Unprocessed Total: {fmt_money(unprocessed_total)}")
        
        # Load all payments
        self._rows_detailed = self.logic.all_payments_detailed(date_from, date_to)
        self.model_detailed.set_rows(self._rows_detailed)
        
        # Resize columns
        self._resize_table(self.tbl_summary)
        self._resize_table(self.tbl_unprocessed)
        self._resize_table(self.tbl_detailed)
    
    def _resize_table(self, table: QTableView) -> None:
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
    
    def _export_all(self) -> None:
        """Export all payment data to CSV"""
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export All Payment Reports", "comprehensive_payments.csv", "CSV Files (*.csv)"
        )
        if not fn:
            return
        
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                
                # Write summary data
                writer.writerow(["PAYMENT SUMMARY BY STATUS"])
                writer.writerow(["Status", "Type", "Count", "Total Amount"])
                for row in self._rows_summary:
                    writer.writerow([
                        row.get("status", ""),
                        row.get("type", ""),
                        row.get("count", 0),
                        f"{row.get('total_amount', 0.0):.2f}"
                    ])
                
                writer.writerow([])  # Empty row
                
                # Write unprocessed payments
                writer.writerow(["UNPROCESSED PAYMENTS"])
                writer.writerow(["Date", "Type", "Amount", "Method", "Status", "Document ID", "Notes"])
                for row in self._rows_unprocessed:
                    writer.writerow([
                        row.get("date", ""),
                        row.get("type", ""),
                        f"{row.get('amount', 0.0):.2f}",
                        row.get("method", ""),
                        row.get("status", ""),
                        row.get("doc_id", ""),
                        row.get("notes", "")
                    ])
                
                writer.writerow([])  # Empty row
                
                # Write all payments
                writer.writerow(["ALL PAYMENTS"])
                writer.writerow(["Date", "Type", "Amount", "Method", "Status", "Document ID", "Notes"])
                for row in self._rows_detailed:
                    writer.writerow([
                        row.get("date", ""),
                        row.get("type", ""),
                        f"{row.get('amount', 0.0):.2f}",
                        row.get("method", ""),
                        row.get("status", ""),
                        row.get("doc_id", ""),
                        row.get("notes", "")
                    ])
            
            QMessageBox.information(self, "Export Complete", f"Data exported to {fn}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", f"Could not export data:\n{e}")

