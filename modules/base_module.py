from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

class BaseModule(QObject):
    def get_widget(self) -> QWidget:
        raise NotImplementedError
