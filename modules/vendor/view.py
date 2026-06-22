# ⚠️ VENDOR MODULE ONLY: Adds read-only Account Details box under the accounts table. Do not modify other modules.
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QFrame, QFormLayout,
    QSizePolicy
)
from PySide6.QtCore import Qt
from widgets.table_view import TableView
from .details import VendorDetails


class VendorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # actions + search
        top = QHBoxLayout()
        self.btn_add = QPushButton("Add Vendor")
        self.btn_import = QPushButton("Import Vendors")
        self.btn_edit = QPushButton("Edit Vendor")
        # self.btn_del = QPushButton("Delete")

        # New: record advance action (creates vendor credit)
        self.btn_apply_advance = QPushButton("Record Advance…")
        # New: unified history view (similar to customer History)
        self.btn_history = QPushButton("Vendor History")

        top.addWidget(self.btn_add)
        top.addWidget(self.btn_import)
        top.addWidget(self.btn_edit)
        # top.addWidget(self.btn_del)
        top.addWidget(self.btn_apply_advance)
        top.addWidget(self.btn_history)
        top.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search vendors (name, id, contact, address)…")
        self.search.setClearButtonEnabled(True)
        top.addWidget(QLabel("Search vendors:"))
        top.addWidget(self.search, 2)
        root.addLayout(top)

        status_row = QHBoxLayout()
        self.list_status = QLabel("")
        self.list_status.setStyleSheet("color: #666;")
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

        # table + right side split (details + bank accounts)
        split = QSplitter(Qt.Horizontal)

        # Left: vendors table
        self.table = TableView()
        split.addWidget(self.table)

        # Right: vertical split with details (top) and accounts (bottom)
        right = QSplitter(Qt.Vertical)
        right.setMinimumWidth(0)
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        # Top-right: vendor details (keep compact)
        self.details = VendorDetails()
        self.details.setMaximumHeight(180)
        self.details.setMinimumWidth(0)
        right.addWidget(self.details)

        # Bottom-right: bank accounts panel
        accounts_panel = QFrame()
        accounts_panel.setMinimumWidth(0)
        accounts_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        accounts_layout = QVBoxLayout(accounts_panel)
        accounts_header = QHBoxLayout()

        lbl_accounts = QLabel("Bank Accounts")
        lbl_accounts.setStyleSheet("font-weight: 600;")
        accounts_header.addWidget(lbl_accounts)
        accounts_header.addStretch(1)

        # Bank account actions
        self.btn_acc_add = QPushButton("Add Account")
        self.btn_acc_edit = QPushButton("Edit Account")
        self.btn_acc_deactivate = QPushButton("Deactivate Account")
        self.btn_acc_activate = QPushButton("Activate Account")
        self.btn_acc_set_primary = QPushButton("Set Primary")
        for btn in (
            self.btn_acc_add,
            self.btn_acc_edit,
            self.btn_acc_deactivate,
            self.btn_acc_activate,
            self.btn_acc_set_primary,
        ):
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        accounts_header.addWidget(self.btn_acc_add)
        accounts_header.addWidget(self.btn_acc_edit)
        accounts_header.addWidget(self.btn_acc_deactivate)
        accounts_header.addWidget(self.btn_acc_activate)
        accounts_header.addWidget(self.btn_acc_set_primary)

        accounts_layout.addLayout(accounts_header)

        # Accounts table
        self.accounts_table = TableView()
        self.accounts_table.setMinimumWidth(0)
        self.accounts_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        accounts_layout.addWidget(self.accounts_table, 1)

        # Create a fixed-height frame under the table
        self.account_details_box = QFrame(self)
        self.account_details_box.setObjectName("account_details_box")
        self.account_details_box.setFrameShape(QFrame.StyledPanel)
        self.account_details_box.setFrameShadow(QFrame.Sunken)
        self.account_details_box.setMinimumHeight(120)
        self.account_details_box.setMaximumHeight(160)
        self.account_details_box.setMinimumWidth(0)
        self.account_details_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

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
        self.lblAccLabel    = QLabel("No account selected", self.account_details_box)
        self.lblAccLabel.setObjectName("lblAccLabel")
        self.lblAccLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lblAccLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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

        # Sizing: keep details shorter than accounts
        right.setStretchFactor(0, 1)  # details
        right.setStretchFactor(1, 3)  # accounts

        split.addWidget(right)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 3)  # vendor list
        split.setStretchFactor(1, 1)  # right panel
        split.setSizes([900, 300])

        root.addWidget(split, 1)
