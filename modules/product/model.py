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
        c = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return [
                p.product_id,
                p.name,
                p.category or "",
                f"{p.min_stock_level:g}",
                p.description or "",
                p.base_uom_name or "",
                p.alt_uom_names or "",
            ][c]
        if role == Qt.UserRole:
            return [
                p.product_id,
                (p.name or "").lower(),
                (p.category or "").lower(),
                float(p.min_stock_level or 0.0),
                (p.description or "").lower(),
                (p.base_uom_name or "").lower(),
                (p.alt_uom_names or "").lower(),
            ][c]
        return None
        
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)
        
    def at(self, row: int) -> Product:
        return self._rows[row]

    def rows(self) -> list[Product]:
        return list(self._rows)
        
    def replace(self, rows: list[Product]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def product_ids(self) -> list[int]:
        return [int(p.product_id) for p in self._rows if p.product_id is not None]

    def apply_metrics(self, metrics_by_id: dict[int, dict]):
        if not metrics_by_id:
            return
        changed = False
        for p in self._rows:
            if p.product_id is None:
                continue
            metrics = metrics_by_id.get(int(p.product_id))
            if not metrics:
                continue
            p.base_uom_name = metrics.get("base_uom_name")
            p.alt_uom_names = metrics.get("alt_uom_names")
            p.on_hand_base = metrics.get("on_hand_base")
            p.cost_price_base = metrics.get("cost_price_base")
            p.sale_price_base = metrics.get("sale_price_base")
            p.latest_price_date = metrics.get("latest_price_date")
            changed = True
        if changed and self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.UserRole])
        
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
