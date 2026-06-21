from __future__ import annotations

import shiboken6
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from .toast import Toast


class NotificationManager:
    def __init__(self) -> None:
        self._toasts: list[Toast] = []

    def show(
        self,
        parent: QWidget | None,
        *,
        level: str,
        title: str,
        text: str,
        duration_ms: int,
        close_button: bool,
    ) -> Toast:
        host = self._host(parent)
        toast = Toast(
            host,
            level=level,
            title=title,
            text=text,
            duration_ms=duration_ms,
            close_button=close_button,
        )
        toast.closed.connect(self._remove)
        toast.destroyed.connect(lambda _obj=None, item=toast: self._remove(item))
        self._toasts.append(toast)
        self._reposition(host)
        toast.show()
        return toast

    def _host(self, parent: QWidget | None) -> QWidget | None:
        if parent is not None:
            window = parent.window()
            if isinstance(window, QWidget):
                return window
        app = QApplication.instance()
        if app is None:
            return None
        active = app.activeWindow()
        return active if isinstance(active, QWidget) else None

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        if not shiboken6.isValid(toast):
            return
        host = toast.parentWidget()
        self._reposition(host)

    def _reposition(self, host: QWidget | None) -> None:
        margin = 16
        y = margin
        for toast in list(self._toasts):
            if not shiboken6.isValid(toast):
                self._toasts.remove(toast)
                continue
            if toast.parentWidget() is not host:
                continue
            toast.adjustSize()
            if host is None:
                pos = QPoint(margin, y)
            else:
                pos = QPoint(max(margin, host.width() - toast.width() - margin), y)
            toast.move(pos)
            y += toast.height() + 8


manager = NotificationManager()
