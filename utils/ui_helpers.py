from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt

def wrap_center(w: QWidget) -> QWidget:
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addStretch(1)
    lay.addWidget(w, 0, Qt.AlignCenter)
    lay.addStretch(1)
    return host

def info(parent: QWidget, title: str, text: str):
    QMessageBox.information(parent, title, text)

def error(parent: QWidget, title: str, text: str):
    QMessageBox.critical(parent, title, text)
