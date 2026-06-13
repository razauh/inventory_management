from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QMessageBox, QWidget


def validate_date_range(parent: QWidget, date_from: QDate, date_to: QDate, label: str = "Period") -> bool:
    if date_from <= date_to:
        return True
    QMessageBox.warning(parent, "Invalid date range", f"{label} start must be on or before end.")
    return False


def date_range_strings(date_from: QDate, date_to: QDate) -> Tuple[str, str]:
    return date_from.toString("yyyy-MM-dd"), date_to.toString("yyyy-MM-dd")
