from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QRadioButton, QButtonGroup
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
        
        # Search controls
        search_row = QHBoxLayout()
        search_row.addStretch(1)  # This will push the search to the right
        search_row.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Enter search term")
        self.search.setMaximumWidth(200)  # Make the search bar smaller
        search_row.addWidget(self.search)
        
        # Search type radio buttons
        self.search_group = QButtonGroup(self)  # Create a button group for mutual exclusivity
        self.rb_all = QRadioButton("All")
        self.rb_id = QRadioButton("PO ID")
        self.rb_vendor = QRadioButton("Vendor")
        self.rb_status = QRadioButton("Status")
        self.rb_all.setChecked(True)  # Default to search all fields
        
        # Add radio buttons to the group
        self.search_group.addButton(self.rb_all)
        self.search_group.addButton(self.rb_id)
        self.search_group.addButton(self.rb_vendor)
        self.search_group.addButton(self.rb_status)
        
        search_row.addWidget(QLabel("Search in:"))  # Label for radio buttons
        search_row.addWidget(self.rb_all)
        search_row.addWidget(self.rb_id)
        search_row.addWidget(self.rb_vendor)
        search_row.addWidget(self.rb_status)
        
        root.addLayout(row)
        root.addLayout(search_row)

        split = QSplitter(Qt.Horizontal)
        left = QWidget(); from PySide6.QtWidgets import QVBoxLayout as V; l = V(left)
        self.tbl = TableView(); l.addWidget(self.tbl, 3)
        self.items = PurchaseItemsView(); l.addWidget(self.items, 2)
        split.addWidget(left)
        self.details = PurchaseDetails()
        split.addWidget(self.details)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
