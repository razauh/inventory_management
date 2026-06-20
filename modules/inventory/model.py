from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex


class TransactionsTableModel(QAbstractTableModel):
    """
    Table model for inventory transactions.

    The model now tolerates TWO possible row schemas (for safety):

    Preferred keys (from updated InventoryRepo):
      - transaction_id
      - date
      - transaction_type
      - product
      - quantity
      - unit_name
      - notes

    Also accepted (legacy/old):
      - id
      - date
      - type
      - product
      - qty
      - uom
      - notes
    """
    HEADERS: List[str] = ["ID", "Date", "Type", "Product", "Qty", "UoM", "Notes"]
    TYPE_LABELS = {
        "purchase": "Purchase",
        "sale": "Sale",
        "purchase_return": "Purchase Return",
        "sale_return": "Sale Return",
        "adjustment": "Adjustment",
    }

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__()
        self._rows: List[Dict[str, Any]] = list(rows or [])

    # ---------- Qt model basics ----------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        r = self._rows[index.row()]
        col = index.column()

        def _get(*keys, default=""):
            for k in keys:
                if k in r and r[k] is not None:
                    return r[k]
            return default

        # Display / Edit text
        if role in (Qt.DisplayRole, Qt.EditRole):
            try:
                if col == 0:  # ID
                    return _get("transaction_id", "id")
                elif col == 1:  # Date
                    return _get("date")
                elif col == 2:  # Type
                    return self._format_type(_get("transaction_type", "type"))
                elif col == 3:  # Product
                    return _get("product")
                elif col == 4:  # Qty
                    q = _get("quantity", "qty", default=0)
                    try:
                        return f"{float(q):g}"
                    except Exception:
                        return str(q) if q is not None else ""
                elif col == 5:  # UoM
                    return _get("unit_name", "uom")
                elif col == 6:  # Notes
                    return _get("notes", default="")
            except Exception:
                return ""

        # Align numeric-ish columns (ID and Qty) to right for readability
        if role == Qt.TextAlignmentRole:
            if col in (0, 4):
                return int(Qt.AlignRight | Qt.AlignVCenter)

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        reverse = order == Qt.DescendingOrder

        def _sort_key(row: Dict[str, Any]):
            def _get(*keys, default=""):
                for k in keys:
                    if k in row and row[k] is not None:
                        return row[k]
                return default

            if column == 0:
                try:
                    return int(_get("transaction_id", "id", default=0) or 0)
                except Exception:
                    return 0
            if column == 1:
                raw = str(_get("date", default=""))
                try:
                    return (0, datetime.strptime(raw, "%Y-%m-%d"))
                except Exception:
                    return (1, raw)
            if column == 2:
                return self._format_type(_get("transaction_type", "type")).casefold()
            if column == 3:
                return str(_get("product", default="")).casefold()
            if column == 4:
                try:
                    return float(_get("quantity", "qty", default=0) or 0.0)
                except Exception:
                    return 0.0
            if column == 5:
                return str(_get("unit_name", "uom", default="")).casefold()
            if column == 6:
                return str(_get("notes", default="")).casefold()
            return 0

        self.beginResetModel()
        self._rows.sort(key=_sort_key, reverse=reverse)
        self.endResetModel()

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            try:
                return self.HEADERS[section]
            except IndexError:
                return ""
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            if section in (0, 4):  # ID, Qty
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return super().headerData(section, orientation, role)

    # ---------- Convenience helpers (non-breaking) ----------

    def replace(self, rows: List[Dict[str, Any]]) -> None:
        """Replace all rows at once (keeps column schema unchanged)."""
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def row_dict(self, row: int) -> Dict[str, Any]:
        """Return the raw dict for a given row (useful in tests/controllers)."""
        return self._rows[row]

    def rows(self) -> List[Dict[str, Any]]:
        """Return a shallow copy of all rows."""
        return list(self._rows)

    @classmethod
    def _format_type(cls, raw: Any) -> str:
        if raw is None:
            return ""
        text = str(raw).strip()
        if not text:
            return ""
        return cls.TYPE_LABELS.get(text, text.replace("_", " ").title())

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(self.HEADERS)


class LowInventoryTableModel(QAbstractTableModel):
    HEADERS: List[str] = ["ID", "Product", "Available", "Min Stock", "UoM"]

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__()
        self._rows: List[Dict[str, Any]] = list(rows or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == 0:
                return row.get("product_id", "")
            if col == 1:
                return row.get("product", "")
            if col == 2:
                return f"{float(row.get('available_qty') or 0.0):g}"
            if col == 3:
                return f"{float(row.get('min_stock_level') or 0.0):g}"
            if col == 4:
                return row.get("unit_name", "")
        if role == Qt.TextAlignmentRole and col in (0, 2, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            try:
                return self.HEADERS[section]
            except IndexError:
                return ""
        return super().headerData(section, orientation, role)

    def replace(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()
