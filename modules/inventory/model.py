from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex

class TransactionsTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Type", "Product", "Qty", "UoM", "Notes"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()): return len(self._rows)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        r = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            mapping = [
                r["transaction_id"], r["date"], r["transaction_type"],
                r["product"], f'{float(r["quantity"]):g}', r["unit_name"], r.get("notes","") or ""
            ]
            return mapping[c]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def replace(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
