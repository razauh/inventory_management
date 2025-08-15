from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QWidget as W, QVBoxLayout as V
from PySide6.QtCore import Qt
from ...widgets.table_view import TableView
from .details import SaleDetails
from .items import SaleItemsView

class SalesView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_add = QPushButton("New")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")
        self.btn_return = QPushButton("Return")
        bar.addWidget(self.btn_add); bar.addWidget(self.btn_edit); bar.addWidget(self.btn_return) #; bar.addWidget(self.btn_del)
        bar.addStretch(1)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search sales (id, customer, status)…")
        bar.addWidget(QLabel("Search:")); bar.addWidget(self.search, 2)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        left = W(); lv = V(left)
        self.tbl = TableView(); lv.addWidget(self.tbl, 3)
        self.items = SaleItemsView(); lv.addWidget(self.items, 2)
        split.addWidget(left)
        self.details = SaleDetails(); split.addWidget(self.details)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
