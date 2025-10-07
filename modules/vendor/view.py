# ⚠️ VENDOR MODULE ONLY: Adds read-only Account Details box under the accounts table. Do not modify other modules.
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QFrame, QFormLayout
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

        # Create a fixed-height frame under the table
        self.account_details_box = QFrame(self)
        self.account_details_box.setObjectName("account_details_box")
        self.account_details_box.setFrameShape(QFrame.StyledPanel)
        self.account_details_box.setFrameShadow(QFrame.Sunken)
        self.account_details_box.setMinimumHeight(120)
        self.account_details_box.setMaximumHeight(160)

        # Form layout for labels
        self.account_details_form = QFormLayout(self.account_details_box)
        self.account_details_form.setContentsMargins(8, 6, 8, 6)
        self.account_details_form.setSpacing(6)

        # Helper to create a right-aligned, selectable QLabel
        def _ro_label(name):
            lbl = QLabel("-", self.account_details_box)
            lbl.setObjectName(name)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        # Create read-only value labels and keep as attributes for controller updates
        self.lblAccLabel    = _ro_label("lblAccLabel")
        self.lblAccBank     = _ro_label("lblAccBank")
        self.lblAccNumber   = _ro_label("lblAccNumber")
        self.lblAccIBAN     = _ro_label("lblAccIBAN")
        self.lblAccRouting  = _ro_label("lblAccRouting")
        self.lblAccPrimary  = _ro_label("lblAccPrimary")
        self.lblAccActive   = _ro_label("lblAccActive")

        # Add rows to form (keys/labels exactly as specified)
        self.account_details_form.addRow("Label",       self.lblAccLabel)
        self.account_details_form.addRow("Bank",        self.lblAccBank)
        self.account_details_form.addRow("Account #",   self.lblAccNumber)
        self.account_details_form.addRow("IBAN",        self.lblAccIBAN)
        self.account_details_form.addRow("Routing #",   self.lblAccRouting)
        self.account_details_form.addRow("Primary",     self.lblAccPrimary)
        self.account_details_form.addRow("Active",      self.lblAccActive)

        # Add the frame below the accounts table without altering existing splitters
        accounts_layout.addWidget(self.account_details_box)

        right.addWidget(accounts_panel)

        # Sizing
        right.setStretchFactor(0, 1)  # details
        right.setStretchFactor(1, 1)  # accounts

        split.addWidget(right)
        split.setStretchFactor(0, 3)  # vendor list
        split.setStretchFactor(1, 2)  # right panel

        root.addWidget(split, 1)
