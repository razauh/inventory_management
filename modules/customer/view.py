from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QSplitter,
    QCheckBox,
    QTabWidget,
)
from PySide6.QtCore import Qt

from ...widgets.table_view import TableView
from .details import CustomerDetails


class CustomerView(QWidget):
    """
    Customers view:
      - Toolbar: Add, Edit, Receive Payment, Record Advance, Apply Advance, Payment History
      - Search box + 'Show inactive' toggle
      - Split: table (left) + tabs (right) -> Details / History
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # ---- Toolbar: actions + search -----------------------------------
        bar = QHBoxLayout()

        # CRUD
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_edit)
        # bar.addWidget(self.btn_del)

        # Payments / Credits
        self.btn_receive_payment = QPushButton("Receive Payment")
        self.btn_record_advance = QPushButton("Record Advance")
        self.btn_apply_advance = QPushButton("Apply Advance")
        self.btn_payment_history = QPushButton("Payment History")

        bar.addWidget(self.btn_receive_payment)
        bar.addWidget(self.btn_record_advance)
        bar.addWidget(self.btn_apply_advance)
        bar.addWidget(self.btn_payment_history)

        bar.addStretch(1)

        # Search + Show inactive
        bar.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search customers (name, id, contact, address)…")
        bar.addWidget(self.search, 2)

        self.chk_show_inactive = QCheckBox("Show inactive")
        bar.addWidget(self.chk_show_inactive)

        root.addLayout(bar)

        # ---- Main split: table (left) + tabs (right) ----------------------
        split = QSplitter(Qt.Horizontal)

        # Left: customers table
        self.table = TableView()
        split.addWidget(self.table)

        # Right: tabs -> Details / History
        self.tabs = QTabWidget()
        # Details tab (keep attribute name for controller compatibility)
        self.details = CustomerDetails()
        self.tabs.addTab(self.details, "Details")

        # History tab (compact, optional use)
        self.history_panel = QWidget()
        v_hist = QVBoxLayout(self.history_panel)
        self.history_hint = QLabel(
            "History shows receipts and advances for the selected customer.\n"
            "Tip: Use the toolbar’s ‘Payment History’ to open the full view."
        )
        self.history_hint.setWordWrap(True)
        v_hist.addWidget(self.history_hint)

        # Optional compact table (controller may populate later)
        self.history_table = TableView()
        v_hist.addWidget(self.history_table)
        self.tabs.addTab(self.history_panel, "History")

        split.addWidget(self.tabs)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
