from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter
from PySide6.QtCore import Qt
from ...widgets.table_view import TableView
from .details import CustomerDetails

class CustomerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # actions + search
        bar = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")
        bar.addWidget(self.btn_add); bar.addWidget(self.btn_edit) #; bar.addWidget(self.btn_del)
        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search customers (name, id, contact, address)…")
        bar.addWidget(QLabel("Search:"))
        bar.addWidget(self.search, 2)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.table = TableView()
        self.details = CustomerDetails()
        split.addWidget(self.table)
        split.addWidget(self.details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
