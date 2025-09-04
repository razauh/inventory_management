"""
Table models for the expense module.

This module defines two simple Qt table models for listing expense
categories and individual expenses.  They follow the conventions used
elsewhere in the application (e.g. the sales and vendor modules) by
exposing `rowCount`, `columnCount`, and `data` methods and
defining a `HEADERS` list for column names.  Monetary values are
formatted with `fmt_money` from ``inventory_management.utils.helpers``.

Models are intended to be fed with lists of dictionaries returned from
``ExpensesRepo.list_categories`` and ``ExpensesRepo.list_expenses``.
They do not perform any data manipulation on their own; that is
responsibility of the repository layer and controller.
"""

from __future__ import annotations

from typing import List, Dict, Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...utils.helpers import fmt_money


class ExpenseCategoriesModel(QAbstractTableModel):
    """Table model for listing expense categories."""

    #: Column headers for the categories table.
    HEADERS: List[str] = ["ID", "Name"]

    def __init__(self, rows: List[Dict[str, Any]]):
        super().__init__()
        self._rows = rows or []

    # Required overrides ---------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            col = index.column()
            if col == 0:
                return row.get("category_id")
            if col == 1:
                return row.get("name")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)


class ExpensesTableModel(QAbstractTableModel):
    """Table model for listing individual expenses."""

    #: Column headers for the expenses table.
    HEADERS: List[str] = ["ID", "Date", "Category", "Description", "Amount"]

    def __init__(self, rows: List[Dict[str, Any]]):
        super().__init__()
        self._rows = rows or []

    # Required overrides ---------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            col = index.column()
            if col == 0:
                return row.get("expense_id")
            if col == 1:
                return row.get("date")
            if col == 2:
                # category_name may be None if not assigned
                return row.get("category_name") or ""
            if col == 3:
                return row.get("description")
            if col == 4:
                # Format amount using helper
                return fmt_money(row.get("amount", 0.0))
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)
