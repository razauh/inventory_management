from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QLineEdit, QVBoxLayout, QLabel
from ...utils.validators import is_positive_number

class PurchasePaymentDialog(QDialog):
    def __init__(self, parent=None, current_paid: float = 0.0, total: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle("Record Payment")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Amount")
        self.lab_info = QLabel(f"Paid so far: {current_paid:g} / Total: {total:g}")

        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Amount*", self.amount)
        lay.addLayout(form)
        lay.addWidget(self.lab_info)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._value = None

    def value(self) -> float | None:
        t = self.amount.text().strip()
        if not is_positive_number(t): return None
        return float(t)

    def accept(self):
        v = self.value()
        if v is None: return
        self._value = v
        super().accept()

    def payload(self): return self._value
