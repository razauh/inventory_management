from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter
from PySide6.QtCore import Qt
from ...widgets.table_view import TableView
from .details import PurchaseDetails
from .items import PurchaseItemsView

class PurchaseView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # actions + search
        row = QHBoxLayout()
        self.btn_add = QPushButton("New")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")
        self.btn_return = QPushButton("Return")
        self.btn_pay = QPushButton("Payment")
        row.addWidget(self.btn_add); row.addWidget(self.btn_edit)#; row.addWidget(self.btn_del)
        row.addWidget(self.btn_return); row.addWidget(self.btn_pay)
        row.addStretch(1)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search purchases (id, vendor, status)")
        row.addWidget(QLabel("Search:")); row.addWidget(self.search, 2)
        root.addLayout(row)

        split = QSplitter(Qt.Horizontal)
        left = QWidget(); from PySide6.QtWidgets import QVBoxLayout as V; l = V(left)
        self.tbl = TableView(); l.addWidget(self.tbl, 3)
        self.items = PurchaseItemsView(); l.addWidget(self.items, 2)
        split.addWidget(left)
        self.details = PurchaseDetails()
        split.addWidget(self.details)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
