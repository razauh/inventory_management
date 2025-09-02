from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...database.repositories.customers_repo import Customer


class CustomersTableModel(QAbstractTableModel):
    """
    Table model for customers with an extra 'Active' column.

    - Backward compatible: if a Customer row lacks `is_active`, we assume active (1).
    - Exposes a custom role (IS_ACTIVE_ROLE) to help external views delegate styling/filtering.
    """

    # Columns shown in the table
    HEADERS = ["ID", "Name", "Contact", "Address", "Active"]

    # Custom role to query active flag (int: 1 or 0)
    IS_ACTIVE_ROLE = Qt.UserRole + 1

    def __init__(self, rows: list[Customer]):
        super().__init__()
        self._rows = rows

    # --- Qt model basics ----------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def _active_text(self, row_obj: Customer) -> str:
        """
        Produce human-friendly Active/Inactive text.
        Falls back to 'Active' when the attribute is missing (old dataclass).
        """
        val = getattr(row_obj, "is_active", 1)
        try:
            is_active = bool(int(val))  # handles 1/0/'1'/'0'
        except Exception:
            is_active = bool(val)       # handles True/False
        return "Active" if is_active else "Inactive"

    def _active_flag(self, row_obj: Customer) -> int:
        """Return 1 or 0 for active flag."""
        val = getattr(row_obj, "is_active", 1)
        try:
            return 1 if int(val) != 0 else 0
        except Exception:
            return 1 if bool(val) else 0

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
                self._active_text(r),
            ]
            return values[c]

        # Expose raw active flag via a custom role for easy filtering/styling
        if role == self.IS_ACTIVE_ROLE:
            return self._active_flag(r)

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    # --- helpers ------------------------------------------------------------

    def at(self, row: int) -> Customer:
        return self._rows[row]

    def replace(self, rows: list[Customer]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
