from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from widgets.table_view import TableView


class CompanyInfoView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        company_buttons = QHBoxLayout()
        self.btn_edit_company = QPushButton("Add / Edit Company")
        self.btn_delete_company = QPushButton("Delete Company")
        company_buttons.addWidget(self.btn_edit_company)
        company_buttons.addWidget(self.btn_delete_company)
        company_buttons.addStretch(1)
        root.addLayout(company_buttons)

        body = QSplitter(Qt.Vertical)
        body.setChildrenCollapsible(False)

        company_box = QGroupBox("Company Profile")
        company_layout = QVBoxLayout(company_box)
        self.company_details = QTextEdit()
        self.company_details.setReadOnly(True)
        company_layout.addWidget(self.company_details)
        body.addWidget(company_box)

        bank_box = QGroupBox("Company Bank Accounts")
        bank_layout = QVBoxLayout(bank_box)
        bank_buttons = QHBoxLayout()
        self.btn_add_bank = QPushButton("Add Account")
        self.btn_edit_bank = QPushButton("Edit Account")
        self.btn_delete_bank = QPushButton("Delete / Deactivate")
        self.btn_primary_bank = QPushButton("Set Primary")
        bank_buttons.addWidget(self.btn_add_bank)
        bank_buttons.addWidget(self.btn_edit_bank)
        bank_buttons.addWidget(self.btn_delete_bank)
        bank_buttons.addWidget(self.btn_primary_bank)
        bank_buttons.addStretch(1)
        bank_layout.addLayout(bank_buttons)

        self.bank_table = TableView()
        self.bank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bank_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.bank_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        bank_layout.addWidget(self.bank_table, 1)
        self.bank_status = QLabel("")
        bank_layout.addWidget(self.bank_status)
        body.addWidget(bank_box)

        proprietor_box = QGroupBox("Proprietors")
        proprietor_layout = QVBoxLayout(proprietor_box)
        proprietor_buttons = QHBoxLayout()
        self.btn_add_proprietor = QPushButton("Add Proprietor")
        self.btn_edit_proprietor = QPushButton("Edit Proprietor")
        self.btn_delete_proprietor = QPushButton("Delete Proprietor")
        proprietor_buttons.addWidget(self.btn_add_proprietor)
        proprietor_buttons.addWidget(self.btn_edit_proprietor)
        proprietor_buttons.addWidget(self.btn_delete_proprietor)
        proprietor_buttons.addStretch(1)
        proprietor_layout.addLayout(proprietor_buttons)

        self.proprietor_table = TableView()
        self.proprietor_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.proprietor_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.proprietor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        proprietor_layout.addWidget(self.proprietor_table, 1)
        self.proprietor_status = QLabel("")
        proprietor_layout.addWidget(self.proprietor_status)
        body.addWidget(proprietor_box)

        body.setSizes([240, 300, 220])
        root.addWidget(body, 1)
