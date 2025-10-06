from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel
from ...widgets.table_view import TableView

class ProductView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # Top row: actions + search
        row = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Delete Product")
        # self.btn_del = QPushButton("Delete")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_edit)
        # row.addWidget(self.btn_del)
        row.addStretch(1)
        
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search products (name, category, id, description)…")
        row.addWidget(QLabel("Search:"))
        row.addWidget(self.search, 2)
        
        layout.addLayout(row)
        self.table = TableView()
        layout.addWidget(self.table, 1)