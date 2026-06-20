from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSplitter, QRadioButton, QButtonGroup, QGroupBox, QTabWidget
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from ...widgets.table_view import TableView
from .details import PurchaseDetails
from .items import PurchaseItemsView


class PurchasePaymentsTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Method", "Amount", "State", "Ref #", "Company Bank", "Vendor Bank", "Notes"]

    def __init__(self, rows: list[dict] | None = None):
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        row = self._rows[index.row()]

        def g(key, default=""):
            try:
                return row.get(key, default) if isinstance(row, dict) else row[key]
            except Exception:
                return default

        amount = g("amount", 0.0)
        try:
            amount_text = f"{float(amount or 0.0):.2f}"
        except (TypeError, ValueError):
            amount_text = "0.00"
        ref = g("ref_no") or g("instrument_no") or ""
        cols = [
            str(g("payment_id")),
            str(g("date")),
            str(g("method")),
            amount_text,
            str(g("clearing_state")),
            str(ref),
            str(g("bank_account_label") or g("bank_account_id") or ""),
            str(g("vendor_bank_account_label") or g("vendor_bank_account_id") or ""),
            str(g("notes")),
        ]
        return cols[index.column()]

    def replace(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()


class PurchasePaymentsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Payments")
        layout = QVBoxLayout(box)
        self.table = TableView()
        self.model = PurchasePaymentsTableModel([])
        self.table.setModel(self.model)
        layout.addWidget(self.table, 1)

        root = QVBoxLayout(self)
        root.addWidget(box, 1)

    def set_rows(self, rows: list[dict]):
        self.model.replace(rows)
        self.table.resizeColumnsToContents()


class PurchaseView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # actions + search
        row = QHBoxLayout()
        self.btn_add = QPushButton("New")
        self.btn_edit = QPushButton("Edit")
        self.btn_return = QPushButton("Return")
        self.btn_return_all = QPushButton("Return Whole Order")
        self.btn_pay = QPushButton("Payment")
        row.addWidget(self.btn_add); row.addWidget(self.btn_edit)
        row.addWidget(self.btn_return); row.addWidget(self.btn_return_all); row.addWidget(self.btn_pay)
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

        self.tabs = QTabWidget()

        orders_tab = QWidget()
        orders_layout = QVBoxLayout(orders_tab)
        split = QSplitter(Qt.Horizontal)
        left = QWidget(); from PySide6.QtWidgets import QVBoxLayout as V; l = V(left)
        self.tbl = TableView(); l.addWidget(self.tbl, 3)
        self.items = PurchaseItemsView(); l.addWidget(self.items, 2)
        split.addWidget(left)
        self.details = PurchaseDetails()
        split.addWidget(self.details)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 1)
        split.setSizes([900, 300])
        orders_layout.addWidget(split, 1)
        self.tabs.addTab(orders_tab, "Orders")

        payments_tab = QWidget()
        payments_layout = QVBoxLayout(payments_tab)
        payment_split = QSplitter(Qt.Horizontal)
        self.payments_tbl = TableView()
        payment_split.addWidget(self.payments_tbl)
        self.payments = PurchasePaymentsView()
        payment_split.addWidget(self.payments)
        payment_split.setStretchFactor(0, 3)
        payment_split.setStretchFactor(1, 2)
        payments_layout.addWidget(payment_split, 1)
        self.tabs.addTab(payments_tab, "Payments")

        root.addWidget(self.tabs, 1)
