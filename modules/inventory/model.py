from __future__ import annotations

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
                    return _get("transaction_type", "type")
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
