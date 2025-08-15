from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLineEdit, QLabel
from ...widgets.table_view import TableView

class InventoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # Adjustment controls
        row = QHBoxLayout()
        self.cmb_product = QComboBox()
        self.cmb_uom = QComboBox()
        self.txt_qty = QLineEdit()
        self.txt_qty.setPlaceholderText("e.g., +5 or -3")
        self.txt_date = QLineEdit()
        self.txt_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_notes = QLineEdit()
        self.btn_record = QPushButton("Record Adjustment")
        row.addWidget(QLabel("Product"))
        row.addWidget(self.cmb_product, 2)
        row.addWidget(QLabel("UoM"))
        row.addWidget(self.cmb_uom, 1)
        row.addWidget(QLabel("Qty"))
        row.addWidget(self.txt_qty, 1)
        row.addWidget(QLabel("Date"))
        row.addWidget(self.txt_date, 1)
        row.addWidget(QLabel("Notes"))
        row.addWidget(self.txt_notes, 2)
        row.addWidget(self.btn_record)
        root.addLayout(row)

        # Recent transactions
        self.tbl_recent = TableView()
        root.addWidget(self.tbl_recent, 1)
