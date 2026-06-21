from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt
try:
    from ..modules.notifications import notify_error, notify_info, notify_success, notify_warning
except ImportError:
    from modules.notifications import notify_error, notify_info, notify_success, notify_warning

def wrap_center(w: QWidget) -> QWidget:
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addStretch(1)
    lay.addWidget(w, 0, Qt.AlignCenter)
    lay.addStretch(1)
    return host

_SUCCESS_TITLES = {
    "Added",
    "Activated",
    "Deactivated",
    "Deleted",
    "Export Complete",
    "Exported",
    "Import complete",
    "Recorded",
    "Saved",
    "Success",
    "Updated",
}
_TOAST_WARNING_TITLES = {
    "Ambiguous product",
    "Duplicate product names",
    "History unavailable",
    "Invalid date range",
    "Not available",
    "Not found",
    "No selection",
    "Nothing to export",
    "Nothing to pay",
    "Print",
    "Select",
    "Unavailable",
}
_TOAST_INFO_TITLES = {"Info"}
_TOAST_ERROR_TITLES = {"Error"}


def info(parent: QWidget, title: str, text: str):
    if title in _SUCCESS_TITLES:
        return notify_success(parent, title, text)
    if title in _TOAST_WARNING_TITLES:
        return notify_warning(parent, title, text)
    if title in _TOAST_INFO_TITLES:
        return notify_info(parent, title, text)
    if title in _TOAST_ERROR_TITLES:
        return notify_error(parent, title, text)
    return QMessageBox.information(parent, title, text)

def error(parent: QWidget, title: str, text: str):
    QMessageBox.critical(parent, title, text)
