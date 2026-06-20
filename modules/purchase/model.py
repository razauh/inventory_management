from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QColor
from ...utils.helpers import fmt_money


PAID_BG = QColor("#d8f5df")
PARTIAL_BG = QColor("#fff2bf")
UNPAID_BG = QColor("#ffd9d9")
RETURNED_BG = QColor("#ece6ff")


def _value(row, key, default=None):
    try:
        return row.get(key, default)
    except AttributeError:
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default


def _payment_bg(row) -> QColor | None:
    status = str(_value(row, "payment_status", "") or "").lower()
    if status == "paid":
        return PAID_BG
    if status == "partial":
        return PARTIAL_BG
    if status == "unpaid":
        return UNPAID_BG
    return None


def _fully_returned(row) -> bool:
    try:
        returned = float(_value(row, "returned_value", 0.0) or 0.0)
        net_total = float(_value(row, "calculated_total_amount", _value(row, "total_amount", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return False
    return returned > 1e-9 and net_total <= 1e-9


class PurchasesTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Vendor", "Gross Total", "Returned", "Net Total", "Paid", "Due", "Status"]
    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows
    def rowCount(self, parent=QModelIndex()): return len(self._rows)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        r = self._rows[index.row()]
        if role == Qt.BackgroundRole and _fully_returned(r):
            return RETURNED_BG
        if role == Qt.BackgroundRole and index.column() in (7, 8):
            return _payment_bg(r)
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            keys = r.keys() if hasattr(r, "keys") else r
            paid_total = float(r["paid_amount"] or 0.0) + float(r["advance_payment_applied"] or 0.0)
            returned_value = r["returned_value"] if "returned_value" in keys else 0.0
            net_total = r["calculated_total_amount"] if "calculated_total_amount" in keys else r["total_amount"]
            remaining_due = r["remaining_due"] if "remaining_due" in keys else 0.0
            mapping = [
                r["purchase_id"], r["date"], r["vendor_name"],
                fmt_money(r["total_amount"]),
                fmt_money(returned_value),
                fmt_money(net_total),
                fmt_money(paid_total),
                fmt_money(remaining_due),
                r["payment_status"]
            ]
            return mapping[c]
        return None
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)
    def at(self, row: int) -> dict:
        return self._rows[row]
    def replace(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
    def get_rows(self) -> list[dict]:
        """Return all rows in the model."""
        return self._rows.copy()

class PurchaseItemsModel(QAbstractTableModel):
    HEADERS = ["#", "Product", "Qty", "UoM", "Buy Price", "Sale Price", "Discount", "Line Total"]
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
            # Per-unit discount: line_total = qty * (purchase_price - item_discount)
            line_total = float(r["quantity"]) * (float(r["purchase_price"]) - float(r["item_discount"]))
            mapping = [
                r["item_id"], r["product_name"], f'{float(r["quantity"]):g}', r["unit_name"],
                fmt_money(r["purchase_price"]), fmt_money(r["sale_price"]),
                fmt_money(r["item_discount"]), fmt_money(line_total)
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
