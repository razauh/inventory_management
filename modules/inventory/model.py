from __future__ import annotations

from typing import List, Dict, Any, Optional
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex


class TransactionsTableModel(QAbstractTableModel):
    """
    Table model for inventory transactions.

    Expected row keys (as returned by InventoryRepo.recent_transactions):
      - transaction_id : int
      - date           : str (YYYY-MM-DD)
      - transaction_type : str (e.g., 'adjustment')
      - product        : str (human-readable name)
      - quantity       : float | int
      - unit_name      : str
      - notes          : str | None
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

        # Display / Edit text
        if role in (Qt.DisplayRole, Qt.EditRole):
            # Map row dict -> columns, with defensive fallbacks
            try:
                if col == 0:
                    return r.get("transaction_id", "")
                elif col == 1:
                    return r.get("date", "")
                elif col == 2:
                    return r.get("transaction_type", "")
                elif col == 3:
                    return r.get("product", "")
                elif col == 4:
                    # quantity: display compact numeric (e.g., 5, 5.5, -3)
                    q = r.get("quantity", 0)
                    try:
                        return f"{float(q):g}"
                    except Exception:
                        return str(q)
                elif col == 5:
                    return r.get("unit_name", "")
                elif col == 6:
                    return (r.get("notes") or "")
            except Exception:
                # If a row is malformed, never crash the view
                return ""

        # Align numeric-ish columns (ID and Qty) to center/right for readability
        if role == Qt.TextAlignmentRole:
            if col in (0, 4):  # ID, Qty
                return int(Qt.AlignRight | Qt.AlignVCenter)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            try:
                return self.HEADERS[section]
            except IndexError:
                return ""
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            # Mirror cell alignment for numeric headers
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
