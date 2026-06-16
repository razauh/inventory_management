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


def _mask_value(value, *, keep_last: int = 4) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if len(text) <= keep_last:
        return text
    return f"{'•' * max(4, len(text) - keep_last)}{text[-keep_last:]}"


def _format_currency(value) -> str:
    try:
        if value in (None, ""):
            return ""
        return f"{float(value):,.2f}"
    except Exception:
        return "" if value is None else str(value)


def _to_mapping(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    if hasattr(obj, "keys"):
        try:
            return {key: obj[key] for key in obj.keys()}
        except Exception:
            return None
    return None


class VendorsTableModel(QAbstractTableModel):
    HEADERS = ["Vendor ID", "Name", "Contact", "Address"]

    def __init__(self, rows):
        super().__init__()
        self._rows = list(rows or [])
        self._row_by_id = self._build_row_index()

    def _build_row_index(self):
        out = {}
        for idx, row in enumerate(self._rows):
            vendor_id = _get(row, "vendor_id")
            if vendor_id is not None:
                out[int(vendor_id)] = idx
        return out

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

    def row_at(self, row: int):
        return _to_mapping(self._rows[row]) if 0 <= row < len(self._rows) else None

    def row_for_id(self, vendor_id: int | None):
        if vendor_id is None:
            return None
        return self._row_by_id.get(int(vendor_id))

    def vendor_ids(self):
        ids = []
        for row in self._rows:
            vendor_id = _get(row, "vendor_id")
            if vendor_id is not None:
                ids.append(int(vendor_id))
        return ids

    def apply_balances(self, balances_by_id):
        if not balances_by_id:
            return
        changed = False
        for row in self._rows:
            vendor_id = _get(row, "vendor_id")
            if vendor_id is None:
                continue
            balance = balances_by_id.get(int(vendor_id))
            if balance is None:
                continue
            if isinstance(row, dict):
                row["balance"] = balance
            else:
                try:
                    row.balance = balance
                except Exception:
                    continue
            changed = True
        if changed and self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, self.columnCount() - 1),
                [Qt.DisplayRole, Qt.EditRole],
            )

    def replace(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self._row_by_id = self._build_row_index()
        self.endResetModel()


class VendorBankAccountsTableModel(QAbstractTableModel):
    HEADERS = [
        "Account ID", "Label", "Bank", "Account #", "IBAN", "Routing #", "Primary", "Active"
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
            if key_map[col] == "account_no":
                return _mask_value(val)
            if key_map[col] == "iban":
                return _mask_value(val, keep_last=6)
            if key_map[col] == "routing_no":
                return _mask_value(val, keep_last=4)
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
