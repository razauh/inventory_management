from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .manager import manager


def notify_success(
    parent: QWidget | None,
    title: str,
    text: str,
    duration_ms: int = 3500,
    close_button: bool = True,
):
    return manager.show(
        parent,
        level="success",
        title=title,
        text=text,
        duration_ms=duration_ms,
        close_button=close_button,
    )


def notify_info(
    parent: QWidget | None,
    title: str,
    text: str,
    duration_ms: int = 4000,
    close_button: bool = True,
):
    return manager.show(
        parent,
        level="info",
        title=title,
        text=text,
        duration_ms=duration_ms,
        close_button=close_button,
    )


def notify_warning(
    parent: QWidget | None,
    title: str,
    text: str,
    duration_ms: int = 5000,
    close_button: bool = True,
):
    return manager.show(
        parent,
        level="warning",
        title=title,
        text=text,
        duration_ms=duration_ms,
        close_button=close_button,
    )


def notify_error(
    parent: QWidget | None,
    title: str,
    text: str,
    duration_ms: int = 0,
    close_button: bool = True,
):
    return manager.show(
        parent,
        level="error",
        title=title,
        text=text,
        duration_ms=duration_ms,
        close_button=close_button,
    )
