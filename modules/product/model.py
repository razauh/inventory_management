from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...database.repositories.products_repo import Product

class ProductsTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Name", "Category", "Min Stock", "Description", "Base UOM", "Alt UOM"]
    
    def __init__(self, rows: list[Product]):
        super().__init__()
        self._rows = rows
        
    # Qt model basics
    def rowCount(self, parent=QModelIndex()): 
        return len(self._rows)
        
    def columnCount(self, parent=QModelIndex()): 
        return len(self.HEADERS)
        
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): 
            return None
        p = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            return [
                p.product_id,
                p.name,
                p.category or "",
                f"{p.min_stock_level:g}",
                p.description or "",
                p.base_uom_name or "",
                p.alt_uom_names or "",
            ][c]
        return None
        
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)
        
    def at(self, row: int) -> Product:
        return self._rows[row]
        
    def replace(self, rows: list[Product]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        
    # helper for proxy filtering
    def row_as_text(self, row: int) -> str:
        p = self._rows[row]
        return f"{p.product_id} {p.name or ''} {p.category or ''} {p.description or ''} {p.base_uom_name or ''} {p.alt_uom_names or ''}"

# --- Add a custom proxy that searches across columns ---
from PySide6.QtCore import QSortFilterProxyModel

class ProductFilterProxy(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filterRegularExpression().pattern():
            return True
        model = self.sourceModel()
        try:
            text = model.row_as_text(source_row)
        except AttributeError:
            return True
        return self.filterRegularExpression().match(text).hasMatch()