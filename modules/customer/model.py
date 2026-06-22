from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from database.repositories.customers_repo import Customer


class CustomersTableModel(QAbstractTableModel):
    """
    Table model for customers.
    """

    # Columns shown in the table
    HEADERS = ["ID", "Name", "Contact", "Address"]

    def __init__(self, rows: list[Customer]):
        super().__init__()
        self._rows = rows
        self._row_by_id = self._build_row_index(rows)

    @staticmethod
    def _build_row_index(rows: list[Customer]) -> dict[int, int]:
        return {
            int(row.customer_id): idx
            for idx, row in enumerate(rows)
            if row.customer_id is not None
        }

    # --- Qt model basics ----------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        r = self._rows[index.row()]
        c = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            values = [
                r.customer_id,
                r.name,
                r.contact_info,
                (r.address or ""),
            ]
            return values[c]

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    # --- helpers ------------------------------------------------------------

    def at(self, row: int) -> Customer:
        return self._rows[row]

    def row_for_id(self, customer_id: int | None) -> int | None:
        if customer_id is None:
            return None
        return self._row_by_id.get(int(customer_id))

    def replace(self, rows: list[Customer]):
        self.beginResetModel()
        self._rows = rows
        self._row_by_id = self._build_row_index(rows)
        self.endResetModel()
