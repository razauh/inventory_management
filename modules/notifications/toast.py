from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .styles import style_for


class Toast(QFrame):
    closed = Signal(object)

    def __init__(
        self,
        parent,
        *,
        level: str,
        title: str,
        text: str,
        duration_ms: int,
        close_button: bool,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("notificationToast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(style_for(level))

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 8, 10)
        root.setSpacing(8)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("notificationToastTitle")
        self.title_label.setStyleSheet("font-weight: 600;")
        text_box.addWidget(self.title_label)

        self.message_label = QLabel(text)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_box.addWidget(self.message_label)
        root.addLayout(text_box, 1)

        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        self.close_button.setVisible(close_button)
        root.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self.setFixedWidth(360)
        self.adjustSize()

        if duration_ms > 0:
            QTimer.singleShot(duration_ms, self.close)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(event)
