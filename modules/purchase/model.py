from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...utils.helpers import fmt_money

class PurchasesTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Vendor", "Total", "Paid", "Status"]  # removed Notes
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
                r["purchase_id"], r["date"], r["vendor_name"],
                fmt_money(r["total_amount"]), fmt_money(r["paid_amount"]),
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
