from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...database.repositories.customers_repo import Customer

class CustomersTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Name", "Contact", "Address"]

    def __init__(self, rows: list[Customer]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()): return len(self._rows)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        c = index.column(); r = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return [r.customer_id, r.name, r.contact_info, r.address or ""][c]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def at(self, row: int) -> Customer:
        return self._rows[row]

    def replace(self, rows: list[Customer]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
