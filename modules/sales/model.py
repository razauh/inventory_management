from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...utils.helpers import fmt_money

class SalesTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Customer", "Total", "Paid", "Status"]

    def __init__(self, rows: list):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()): 
        return len(self._rows)
        
    def columnCount(self, parent=QModelIndex()): 
        return len(self.HEADERS)
        
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): 
            return None
        r = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            # Simplified version that mimics PurchasesTableModel
            mapping = [
                r["sale_id"], 
                r["date"], 
                r["customer_name"],
                fmt_money(r["total_amount"]), 
                fmt_money(r["paid_amount"]),
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
        
    def replace(self, rows: list):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class SaleItemsModel(QAbstractTableModel):
    HEADERS = ["#", "Product", "Qty", "Unit Price", "Discount", "Line Total"]
    
    def __init__(self, rows: list): 
        super().__init__()
        self._rows = rows
        
    def rowCount(self, parent=QModelIndex()): 
        return len(self._rows)
        
    def columnCount(self, parent=QModelIndex()): 
        return len(self.HEADERS)
        
    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid(): 
            return None
        r = self._rows[idx.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            lt = float(r["quantity"]) * (float(r["unit_price"]) - float(r["item_discount"]))
            m = [r["item_id"], r["product_name"], f'{float(r["quantity"]):g}',
                 fmt_money(r["unit_price"]), fmt_money(r["item_discount"]), fmt_money(lt)]
            return m[idx.column()]
        return None
        
    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.HEADERS[s] if o==Qt.Horizontal and role==Qt.DisplayRole else super().headerData(s,o,role)
        
    def replace(self, rows: list): 
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()