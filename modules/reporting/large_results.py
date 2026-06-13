from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHeaderView, QTableView


def should_auto_resize(model: Any, *, max_rows: int = 500, max_cols: int = 16) -> bool:
    if model is None:
        return False
    try:
        rows = int(model.rowCount())
        cols = int(model.columnCount())
    except Exception:
        return False
    return rows <= max_rows and cols <= max_cols


def maybe_resize_columns(tv: QTableView, *, max_rows: int = 500, max_cols: int = 16) -> None:
    model = tv.model()
    if should_auto_resize(model, max_rows=max_rows, max_cols=max_cols):
        tv.resizeColumnsToContents()
        tv.horizontalHeader().setStretchLastSection(True)
        return

    header = tv.horizontalHeader()
    header.setStretchLastSection(False)
    for col in range(model.columnCount() if model else 0):
        header.setSectionResizeMode(col, QHeaderView.Interactive)
