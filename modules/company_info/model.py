from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class CompanyBankAccountsTableModel(QAbstractTableModel):
    HEADERS = ["Title", "Bank", "Account No", "IBAN", "Primary", "Active"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return [
                row.get("label") or "",
                row.get("bank_name") or "",
                row.get("account_no") or "",
                row.get("iban") or "",
                "Yes" if row.get("is_primary") else "No",
                "Active" if row.get("is_active") else "Inactive",
            ][index.column()]
        if role == Qt.UserRole:
            return row.get("account_id")
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def row_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def replace(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()


class CompanyProprietorsTableModel(QAbstractTableModel):
    HEADERS = ["Name", "Phone", "Order", "Active"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return [
                row.get("name") or "",
                row.get("phone") or "",
                row.get("sort_order") or 0,
                "Active" if row.get("is_active") else "Inactive",
            ][index.column()]
        if role == Qt.UserRole:
            return row.get("proprietor_id")
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def row_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def replace(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()
