from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView, QDialogButtonBox, QLineEdit, QFormLayout
from PySide6.QtCore import Qt
from ...utils.helpers import today_str

class PurchaseReturnForm(QDialog):
    def __init__(self, parent=None, items: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Purchase Return")
        self.setModal(True)
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["ItemID", "Product", "UoM", "Qty Purchased", "Qty Return", "Notes"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.AllEditTriggers)

        self.date = QLineEdit(today_str())
        self.notes = QLineEdit()

        f = QFormLayout()
        f.addRow("Date", self.date)
        f.addRow("Notes", self.notes)

        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(self.tbl, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._payload = None
        if items:
            self.set_items(items)

    def set_items(self, items: list[dict]):
        # items rows have: item_id, product_name, unit_name, quantity
        self.tbl.setRowCount(len(items))
        for r, it in enumerate(items):
            self.tbl.setItem(r, 0, QTableWidgetItem(str(it["item_id"])))
            self.tbl.setItem(r, 1, QTableWidgetItem(it["product_name"]))
            self.tbl.setItem(r, 2, QTableWidgetItem(it["unit_name"]))
            self.tbl.setItem(r, 3, QTableWidgetItem(f'{float(it["quantity"]):g}'))
            self.tbl.setItem(r, 4, QTableWidgetItem("0"))  # Qty Return (editable)
            self.tbl.setItem(r, 5, QTableWidgetItem(""))

    def get_payload(self):
        lines = []
        for r in range(self.tbl.rowCount()):
            qty_ret = float(self.tbl.item(r, 4).text() or 0)
            if qty_ret <= 0:
                continue
            lines.append({
                "item_id": int(self.tbl.item(r, 0).text()),
                "qty_return": qty_ret,
            })
        if not lines:
            return None
        return {
            "date": self.date.text().strip() or today_str(),
            "notes": self.notes.text().strip() or None,
            "lines": lines
        }

    def accept(self):
        p = self.get_payload()
        if p is None: return
        self._payload = p
        super().accept()

    def payload(self): return self._payload
