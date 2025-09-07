# inventory_management/modules/reporting/model.py
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt  # <-- no QVariant
from PySide6.QtWidgets import QStyle

# Money formatting (reuse app helper if present)
try:
    from ...utils.ui_helpers import fmt_money  # type: ignore
except Exception:  # pragma: no cover
    def fmt_money(x: Optional[float]) -> str:
        try:
            return f"{float(x or 0.0):,.2f}"
        except Exception:
            return "0.00"


# ------------------------------ A) Aging Snapshot ----------------------------

class AgingSnapshotTableModel(QAbstractTableModel):
    HEADERS = ("Name", "Total Due", "0–30", "31–60", "61–90", "91+", "Available Credit")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self.HEADERS)

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
                return row.get("name", "")
            if c == 1:
                return fmt_money(row.get("total_due"))
            if c in (2, 3, 4, 5):
                key = {2: "b_0_30", 3: "b_31_60", 4: "b_61_90", 5: "b_91_plus"}[c]
                return fmt_money(row.get(key))
            if c == 6:
                return fmt_money(row.get("available_credit"))
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c != 0 else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ B) Open Invoices -----------------------------

class OpenInvoicesTableModel(QAbstractTableModel):
    HEADERS = ("Doc No", "Date", "Total", "Paid", "Advance Applied", "Remaining", "Days Outstanding")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self.HEADERS)

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
            if c in (2, 3, 4, 5):
                key = {2: "total", 3: "paid", 4: "advance_applied", 5: "remaining"}[c]
                return fmt_money(row.get(key))
            if c == 6:
                return str(row.get("days_outstanding") or 0)
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c not in (0, 1) else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ C) Expense Summary ---------------------------

class ExpenseSummaryTableModel(QAbstractTableModel):
    HEADERS = ("Category", "Total", "% of Period")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 3

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
                return row.get("category_name", "")
            if c == 1:
                return fmt_money(row.get("total_amount"))
            if c == 2:
                pct = float(row.get("pct_of_period") or 0.0)
                return f"{pct:.1f}%"
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c in (1, 2) else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ D) Expense List ------------------------------

class ExpenseListTableModel(QAbstractTableModel):
    HEADERS = ("ID", "Date", "Category", "Description", "Amount")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 5

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
                return str(row.get("expense_id", ""))
            if c == 1:
                return row.get("date", "")
            if c == 2:
                return row.get("category_name", "")
            if c == 3:
                return row.get("description", "")
            if c == 4:
                return fmt_money(row.get("amount"))
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c == 4 else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ E) Stock on Hand -----------------------------

class InventoryStockOnHandTableModel(QAbstractTableModel):
    HEADERS = ("Product", "Qty (base)", "Unit Value", "Total Value", "Valuation Date")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 5

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
                return row.get("product_name", "")
            if c == 1:
                try:
                    return f"{float(row.get('qty_base') or 0.0):,.3f}".rstrip('0').rstrip('.')
                except Exception:
                    return "0"
            if c == 2:
                return fmt_money(row.get("unit_value"))
            if c == 3:
                return fmt_money(row.get("total_value"))
            if c == 4:
                return row.get("valuation_date", "")
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c in (1, 2, 3) else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ F) Inventory Transactions --------------------

class InventoryTransactionsTableModel(QAbstractTableModel):
    HEADERS = ("Date", "Product", "Type", "Qty (base)", "Ref Table", "Ref ID", "Notes")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else 7

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
                return row.get("product_name", "")
            if c == 2:
                return row.get("type", "")
            if c == 3:
                try:
                    return f"{float(row.get('qty_base') or 0.0):,.3f}".rstrip('0').rstrip('.')
                except Exception:
                    return "0"
            if c == 4:
                return row.get("ref_table", "")
            if c == 5:
                return row.get("ref_id", "")
            if c == 6:
                return row.get("notes", "")
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c in (3,) else (Qt.AlignLeft | Qt.AlignVCenter)
        return None


# ------------------------------ G) Financial Statement -----------------------

class FinancialStatementTableModel(QAbstractTableModel):
    HEADERS = ("Line Item", "Amount")

    def __init__(self, rows: Optional[List[dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = rows or []

    def set_rows(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

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
                return row.get("line_item", "")
            if c == 1:
                amt = row.get("amount", None)
                return "" if amt is None else fmt_money(amt)
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if c == 1 else (Qt.AlignLeft | Qt.AlignVCenter)
        return None
