from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox

class LoginForm(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        lay = QFormLayout(self)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        lay.addRow("Username", self.username)
        lay.addRow("Password", self.password)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addRow(self.buttons)

    def get_values(self) -> tuple[str, str]:
        return self.username.text().strip(), self.password.text()
