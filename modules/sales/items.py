from PySide6.QtWidgets import QWidget, QVBoxLayout
from ...widgets.table_view import TableView
from .model import SaleItemsModel

class SaleItemsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = TableView()
        self.model = SaleItemsModel([])
        self.table.setModel(self.model)
        lay = QVBoxLayout(self); lay.addWidget(self.table, 1)

    def set_rows(self, rows: list[dict]):
        self.model.replace(rows)
        self.table.resizeColumnsToContents()
