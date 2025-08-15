from PySide6.QtWidgets import QWidget, QVBoxLayout
from ...widgets.table_view import TableView
from .model import PurchaseItemsModel

class PurchaseItemsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = TableView()
        lay = QVBoxLayout(self)
        lay.addWidget(self.table, 1)
        self.model = PurchaseItemsModel([])
        self.table.setModel(self.model)

    def set_rows(self, rows: list[dict]):
        self.model.replace(rows)
        self.table.resizeColumnsToContents()
