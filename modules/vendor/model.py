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
    """
    Mirrors rows returned by VendorBankAccountsRepo.list(vendor_id, active_only=True).

    Expected fields per row:
      vendor_bank_account_id, bank_name, branch, account_number, ifsc_swift,
      account_type, is_primary, is_active
    """
    HEADERS = ["ID", "Bank", "Branch", "Account #", "IFSC/SWIFT", "Type", "Primary", "Active"]

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
        r = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            is_primary = _get(r, "is_primary", 0)
            is_active = _get(r, "is_active", 1)
            values = [
                _get(r, "vendor_bank_account_id", ""),
                _get(r, "bank_name", ""),
                _get(r, "branch", ""),
                _get(r, "account_number", ""),
                _get(r, "ifsc_swift", ""),
                _get(r, "account_type", ""),
                "Yes" if int(is_primary or 0) == 1 else "No",
                "Yes" if int(is_active or 0) == 1 else "No",
            ]
            return values[c]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def at(self, row: int) -> dict:
        """Return the underlying row dict/sqlite3.Row for the given index."""
        return self._rows[row]

    def replace(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()
