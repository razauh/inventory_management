"""
Controller for the expense module (feature-complete Add/Edit/Delete).

Wires ExpensesRepo <-> models <-> ExpenseView and connects Add/Edit to
ExpenseForm. Keeps the existing filtering (search, date, category).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QMessageBox

from ..base_module import BaseModule
from .view import ExpenseView
from .form import ExpenseForm
from .model import ExpensesTableModel
from ...utils import ui_helpers as ui
from ...database.repositories.expenses_repo import ExpensesRepo, DomainError


class ExpenseController(BaseModule):
    """UI controller for viewing and managing expenses."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.repo = ExpensesRepo(conn)

        # Root view (reuse the dedicated widget from view.py)
        self.view = ExpenseView()
        self.view.setWindowTitle("Expenses")

        # Wire signals
        self.view.txt_search.textChanged.connect(lambda _=None: self._reload())
        self.view.date_filter.dateChanged.connect(lambda _=None: self._reload())
        self.view.cmb_category.currentIndexChanged.connect(lambda _=None: self._reload())
        self.view.btn_add.clicked.connect(self._on_add)
        self.view.btn_edit.clicked.connect(self._on_edit)
        self.view.btn_delete.clicked.connect(self._on_delete)

        # Init UI data
        self._load_categories()
        self._reload()

    # ------------------------------------------------------------------
    # BaseModule
    # ------------------------------------------------------------------
    def get_widget(self) -> QWidget:
        return self.view

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _load_categories(self) -> None:
        """Populate the category filter combo box."""
        cats = self.repo.list_categories()
        self.view.cmb_category.blockSignals(True)
        self.view.cmb_category.clear()
        self.view.cmb_category.addItem("(All)", userData=None)
        for c in cats:
            self.view.cmb_category.addItem(c.name, userData=c.category_id)
        self.view.cmb_category.blockSignals(False)

    def _reload(self) -> None:
        """Reload the expenses table based on current filters."""
        query = self.view.search_text
        date = self.view.selected_date
        cat_id = self.view.selected_category_id
        rows = self.repo.search_expenses(query=query, date=date, category_id=cat_id)

        model = ExpensesTableModel(rows)
        self.view.tbl_expenses.setModel(model)
        self.view.tbl_expenses.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _selected_expense_id(self) -> Optional[int]:
        """Return the selected expense_id from the table, or None."""
        tv = self.view.tbl_expenses
        sel = tv.selectionModel().selectedRows()
        if not sel:
            return None
        model = tv.model()
        row = sel[0].row()
        exp_id = model.data(model.index(row, 0), Qt.DisplayRole)
        try:
            return int(exp_id)
        except (TypeError, ValueError):
            return None

    def _open_form(self, initial: Optional[dict] = None) -> Optional[dict]:
        """Open the ExpenseForm with the category list and return payload or None."""
        # Build (id, name) pairs for the combo
        cats = [(c.category_id, c.name) for c in self.repo.list_categories()]
        dlg = ExpenseForm(self.view, categories=cats, initial=initial)
        if dlg.exec() != dlg.Accepted:
            return None
        return dlg.payload()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def _on_add(self) -> None:
        payload = self._open_form(initial=None)
        if not payload:
            return
        try:
            self.repo.create_expense(
                description=payload["description"],
                amount=payload["amount"],
                date=payload["date"],
                category_id=payload["category_id"],
            )
            self._reload()
            ui.info(self.view, "Saved", "Expense added successfully.")
        except DomainError as e:
            ui.info(self.view, "Invalid data", str(e))
        except Exception as e:  # defensive
            ui.info(self.view, "Error", f"Failed to add expense: {e}")

    def _on_edit(self) -> None:
        exp_id = self._selected_expense_id()
        if exp_id is None:
            ui.info(self.view, "Select", "Please select an expense to edit.")
            return

        current = self.repo.get_expense(exp_id)
        if not current:
            ui.info(self.view, "Not found", "The selected expense no longer exists.")
            self._reload()
            return

        payload = self._open_form(initial=current)
        if not payload:
            return

        try:
            self.repo.update_expense(
                expense_id=exp_id,
                description=payload["description"],
                amount=payload["amount"],
                date=payload["date"],
                category_id=payload["category_id"],
            )
            self._reload()
            ui.info(self.view, "Saved", "Expense updated successfully.")
        except DomainError as e:
            ui.info(self.view, "Invalid data", str(e))
        except Exception as e:
            ui.info(self.view, "Error", f"Failed to update expense: {e}")

    def _on_delete(self) -> None:
        exp_id = self._selected_expense_id()
        if exp_id is None:
            ui.info(self.view, "Select", "Please select an expense to delete.")
            return

        resp = QMessageBox.question(
            self.view,
            "Delete",
            f"Are you sure you want to delete expense {exp_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            self.repo.delete_expense(exp_id)
            self._reload()
            ui.info(self.view, "Deleted", "Expense deleted.")
        except Exception as e:
            ui.info(self.view, "Error", f"Failed to delete expense: {e}")
