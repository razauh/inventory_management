from PySide6.QtWidgets import QWidget

class BaseModule:
    def get_widget(self) -> QWidget:
        raise NotImplementedError
