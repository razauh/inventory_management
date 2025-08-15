from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QFrame
)
from PySide6.QtCore import Qt
from ...widgets.table_view import TableView
from .details import VendorDetails


class VendorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # actions + search
        top = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")

        # New: apply credit action (from vendor profile to an open purchase)
        self.btn_apply_credit = QPushButton("Apply Credit…")

        top.addWidget(self.btn_add)
        top.addWidget(self.btn_edit)
        # top.addWidget(self.btn_del)
        top.addWidget(self.btn_apply_credit)
        top.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search vendors (name, id, contact, address)…")
        top.addWidget(QLabel("Search:"))
        top.addWidget(self.search, 2)
        root.addLayout(top)

        # table + right side split (details + bank accounts)
        split = QSplitter(Qt.Horizontal)

        # Left: vendors table
        self.table = TableView()
        split.addWidget(self.table)

        # Right: vertical split with details (top) and accounts (bottom)
        right = QSplitter(Qt.Vertical)

        # Top-right: vendor details
        self.details = VendorDetails()
        right.addWidget(self.details)

        # Bottom-right: bank accounts panel
        accounts_panel = QFrame()
        accounts_layout = QVBoxLayout(accounts_panel)
        accounts_header = QHBoxLayout()

        lbl_accounts = QLabel("Bank Accounts")
        lbl_accounts.setStyleSheet("font-weight: 600;")
        accounts_header.addWidget(lbl_accounts)
        accounts_header.addStretch(1)

        # Bank account actions
        self.btn_acc_add = QPushButton("Add Account")
        self.btn_acc_edit = QPushButton("Edit")
        self.btn_acc_deactivate = QPushButton("Deactivate")
        self.btn_acc_set_primary = QPushButton("Set Primary")
        accounts_header.addWidget(self.btn_acc_add)
        accounts_header.addWidget(self.btn_acc_edit)
        accounts_header.addWidget(self.btn_acc_deactivate)
        accounts_header.addWidget(self.btn_acc_set_primary)

        accounts_layout.addLayout(accounts_header)

        # Accounts table
        self.accounts_table = TableView()
        accounts_layout.addWidget(self.accounts_table, 1)

        right.addWidget(accounts_panel)

        # Sizing
        right.setStretchFactor(0, 1)  # details
        right.setStretchFactor(1, 1)  # accounts

        split.addWidget(right)
        split.setStretchFactor(0, 3)  # vendor list
        split.setStretchFactor(1, 2)  # right panel

        root.addWidget(split, 1)
