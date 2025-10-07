# ⚠️ VENDOR MODULE ONLY: VendorBankAccountsTableModel header/field mapping + minimal helpers.
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex

# Keep import for typed access when VendorsRepo returns dataclasses
try:
    from ...database.repositories.vendors_repo import Vendor  # type: ignore
except Exception:
    Vendor = object  # fallback typing if not available


def _get(obj, key, default=None):
    """Support both dataclass-like attrs and dict/sqlite3.Row access."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    # sqlite3.Row behaves like a mapping but getattr also works for dataclasses
    try:
        return getattr(obj, key)
    except Exception:
        try:
            return obj[key]
        except Exception:
            return default


class VendorsTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Name", "Contact", "Address"]

    def __init__(self, rows):
        super().__init__()
        self._rows = list(rows or [])

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        v = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            values = [
                _get(v, "vendor_id", ""),
                _get(v, "name", ""),
                _get(v, "contact_info", ""),
                _get(v, "address", "") or "",
            ]
            return values[c]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def at(self, row: int):
        """Return the underlying row object (Vendor dataclass or dict)."""
        return self._rows[row]

    def replace(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()


class VendorBankAccountsTableModel(QAbstractTableModel):
    HEADERS = [
        "ID", "Label", "Bank", "Account #", "IBAN", "Routing #", "Primary", "Active"
    ]

    def __init__(self, rows=None, parent=None):
        super().__init__(parent)
        self._rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            key_map = [
                "vendor_bank_account_id",
                "label",
                "bank_name",
                "account_no",
                "iban",
                "routing_no",
                "is_primary",
                "is_active",
            ]
            val = row.get(key_map[col])
            if key_map[col] in ("is_primary", "is_active"):
                return "Yes" if bool(val) else "No"
            return "" if val is None else str(val)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def row_at(self, row_idx: int):
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None

    def find_row_by_id(self, account_id: int):
        for i, r in enumerate(self._rows):
            if int(r.get("vendor_bank_account_id", -1)) == int(account_id):
                return i
        return None
