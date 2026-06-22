from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QSplitter,
    QTabWidget,
)
from PySide6.QtCore import Qt

from widgets.table_view import TableView
from .details import CustomerDetails


class CustomerView(QWidget):
    """
    Customers view:
      - Toolbar: Add, Edit, Record Credit, Apply Credit, History, Print Statement
      - Search box
      - Split: table (left) + tabs (right) -> Details
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # ---- Toolbar: actions + search -----------------------------------
        bar = QHBoxLayout()

        # CRUD
        self.btn_add = QPushButton("Add Customer")
        self.btn_edit = QPushButton("Edit Customer")
        # self.btn_del = QPushButton("Delete")
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_edit)
        # bar.addWidget(self.btn_del)

        # Payments / Credits
        self.btn_record_advance = QPushButton("Record Customer Credit")
        self.btn_apply_advance = QPushButton("Apply Customer Credit")
        self.btn_history = QPushButton("Customer History")
        self.btn_print_history = QPushButton("Print Statement")

        bar.addWidget(self.btn_record_advance)
        bar.addWidget(self.btn_apply_advance)
        bar.addWidget(self.btn_history)
        bar.addWidget(self.btn_print_history)

        bar.addStretch(1)

        # Search
        bar.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search customers (name, id, contact, address)…")
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.search, 2)

        root.addLayout(bar)

        self.list_status = QLabel("")
        self.list_status.setStyleSheet("color: #666;")
        status_row = QHBoxLayout()
        status_row.addWidget(self.list_status, 1)
        self.btn_prev_page = QPushButton("Prev Page")
        self.lbl_page = QLabel("Page 1 / 1")
        self.lbl_page.setMinimumWidth(120)
        self.lbl_page.setAlignment(Qt.AlignCenter)
        self.btn_next_page = QPushButton("Next Page")
        status_row.addWidget(self.btn_prev_page)
        status_row.addWidget(self.lbl_page)
        status_row.addWidget(self.btn_next_page)
        root.addLayout(status_row)

        # ---- Main split: table (left) + tabs (right) ----------------------
        split = QSplitter(Qt.Horizontal)

        # Left: customers table
        self.table = TableView()
        split.addWidget(self.table)

        # Right: single Details panel (no History tab)
        self.tabs = QTabWidget()
        self.details = CustomerDetails()
        self.tabs.addTab(self.details, "Details")

        split.addWidget(self.tabs)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
