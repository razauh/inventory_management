"""
Controller for the expense module.

Wires ExpensesRepo <-> models <-> ExpenseView and connects Add/Edit/Delete
to ExpenseForm. Adds:
- Manage Categories dialog
- Totals-by-category summary refresh
- Print support for the current expense list and totals
- Advanced filters (date range, amount range)
- Selection-aware UX (double-click, Enter, Delete, Ctrl+N/Ctrl+E)

The view exposes:
  search_text, selected_date, selected_category_id,
  date_from_str, date_to_str, amount_min_val, amount_max_val
"""

from __future__ import annotations

from typing import Optional, List, Dict
import sqlite3  # for error mapping of DB exceptions
import html
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QMessageBox, QDialog
from PySide6.QtGui import (
    QKeySequence,
    QShortcut,
    QStandardItemModel,
    QStandardItem,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

from ..base_module import BaseModule
from .view import ExpenseView
from .form import ExpenseForm
from .model import ExpensesTableModel
from .category_dialog import CategoryDialog  # new dialog
from ...utils import ui_helpers as ui
from ...database.repositories.expenses_repo import ExpensesRepo, DomainError


class ExpenseController(BaseModule):
    """UI controller for viewing and managing expenses."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.repo = ExpensesRepo(conn)

        # Root view
        self.view = ExpenseView()
        self.view.setWindowTitle("Expenses")

        # Wire signals (list/reload)
        self.view.txt_search.textChanged.connect(lambda _=None: self._reload())
        self.view.date_filter.dateChanged.connect(lambda _=None: self._reload())
        self.view.cmb_category.currentIndexChanged.connect(lambda _=None: self._reload())

        # Advanced filters
        self.view.date_from.dateChanged.connect(lambda _=None: self._reload())
        self.view.date_to.dateChanged.connect(lambda _=None: self._reload())
        self.view.amount_min.valueChanged.connect(lambda _=None: self._reload())
        self.view.amount_max.valueChanged.connect(lambda _=None: self._reload())

        # Buttons
        self.view.btn_add.clicked.connect(self._on_add)
        self.view.btn_edit.clicked.connect(self._on_edit)
        self.view.btn_delete.clicked.connect(self._on_delete)
        self.view.btn_manage_categories.clicked.connect(self._on_manage_categories)
        self.view.btn_print.clicked.connect(self._on_print)

        # Table shortcuts / interactions
        self._wire_table_shortcuts()

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
        """Reload the expenses table based on current filters and refresh totals."""
        query = self.view.search_text
        date = self.view.selected_date
        cat_id = self.view.selected_category_id

        # If any advanced filter is set, use the advanced search; else use legacy.
        use_adv = any([
            self.view.date_from_str,
            self.view.date_to_str,
            self.view.amount_min_val is not None,
            self.view.amount_max_val is not None,
        ])

        if use_adv:
            rows = self.repo.search_expenses_adv(
                query=query,
                date_from=self.view.date_from_str,
                date_to=self.view.date_to_str,
                category_id=cat_id,
                amount_min=self.view.amount_min_val,
                amount_max=self.view.amount_max_val,
            )
        else:
            rows = self.repo.search_expenses(
                query=query,
                date=date,
                category_id=cat_id,
            )

        model = ExpensesTableModel(rows)
        self.view.tbl_expenses.setModel(model)
        self.view.tbl_expenses.resizeColumnsToContents()

        # Refresh totals summary (currently overall totals by category)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        """Populate the totals table (totals by category)."""
        try:
            totals: List[Dict] = self.repo.total_by_category()
        except Exception as e:
            # Fail gracefully; keep UI usable even if aggregate query fails
            totals = []
            ui.info(self.view, "Totals", f"Could not load totals: {e}")

        m = QStandardItemModel()
        m.setHorizontalHeaderLabels(["Category", "Total"])

        for r in totals:
            # Expected keys: category_name, total_amount (fallback to name/amount variants)
            name = r.get("category_name") or r.get("name") or "(Uncategorized)"
            amt = r.get("total_amount") or r.get("total") or 0.0
            row_items = [
                QStandardItem(str(name)),
                QStandardItem(f"{float(amt):.2f}"),
            ]
            for it in row_items:
                it.setEditable(False)
            m.appendRow(row_items)

        self.view.tbl_totals.setModel(m)
        self.view.tbl_totals.resizeColumnsToContents()

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
        if dlg.exec() != QDialog.Accepted:   # use QDialog.Accepted to avoid enum issues
            return None
        return dlg.payload()

    def _wire_table_shortcuts(self) -> None:
        """Double-click and keyboard shortcuts on the table."""
        tv = self.view.tbl_expenses
        tv.doubleClicked.connect(lambda _=None: self._on_edit())

        # Parent to the whole view so shortcuts work even if focus is on a child
        self._sc_add    = QShortcut(QKeySequence("Ctrl+N"), self.view)
        self._sc_edit_r = QShortcut(QKeySequence("Return"), self.view)
        self._sc_edit_e = QShortcut(QKeySequence("Enter"),  self.view)
        self._sc_del    = QShortcut(QKeySequence("Delete"), self.view)
        self._sc_edit_c = QShortcut(QKeySequence("Ctrl+E"), self.view)

        # Make shortcuts active within the view and all its children
        for sc in (self._sc_add, self._sc_edit_r, self._sc_edit_e, self._sc_del, self._sc_edit_c):
            sc.setContext(Qt.WidgetWithChildrenShortcut)

        self._sc_add.activated.connect(self._on_add)
        self._sc_edit_r.activated.connect(self._on_edit)
        self._sc_edit_e.activated.connect(self._on_edit)
        self._sc_del.activated.connect(self._on_delete)
        self._sc_edit_c.activated.connect(self._on_edit)

    # ------------------------------------------------------------------
    # Error mapping helpers (standardize UX messages)
    # ------------------------------------------------------------------
    def _handle_error(self, context: str, err: Exception) -> None:
        """Map low-level exceptions to consistent user-facing messages."""
        title, msg = self._map_error(context, err)
        ui.info(self.view, title, msg)

    @staticmethod
    def _map_error(context: str, err: Exception) -> tuple[str, str]:
        """
        Convert exceptions (DomainError/sqlite3.IntegrityError/others) to (title, message).
        Keeps messages generic & consistent across controllers.
        """
        # Domain-level validation failures
        if isinstance(err, DomainError):
            return "Invalid data", str(err)

        # Database constraints & FKs
        if isinstance(err, sqlite3.IntegrityError):
            raw = str(err).lower()
            if "foreign key" in raw or "constraint failed" in raw or "constraint" in raw:
                return (
                    "Not allowed",
                    "This action violates a data rule (it may be referenced by other records).",
                )
            if "unique" in raw:
                return ("Already exists", "A record with the same value already exists.")
            return ("Database constraint", "Operation failed due to a database rule. Please check your inputs.")

        # File-related issues (export)
        if isinstance(err, FileNotFoundError):
            return ("File not found", "Please choose a valid location and try again.")

        # Fallback
        return ("Error", f"{context}: {err}")

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
        except Exception as e:  # map DomainError / sqlite3.IntegrityError / others
            self._handle_error("Failed to add expense", e)

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
        except Exception as e:
            self._handle_error("Failed to update expense", e)

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
            self._handle_error("Failed to delete expense", e)

    def _on_manage_categories(self) -> None:
        """Open the category manager dialog and refresh combos & data afterwards."""
        try:
            dlg = CategoryDialog(self.view, self.repo)
            dlg.exec()
            self._load_categories()  # refresh filter combo
            self._reload()           # refresh table & totals
        except Exception as e:
            self._handle_error("Failed to open category manager", e)

    def _on_print(self) -> None:
        """
        Print the current expense list (and optional totals) using the system
        print dialog.  This replaces the older CSV export.
        """
        model = self.view.tbl_expenses.model()
        # Guard against missing or empty models; nothing to print in that case.
        if model is None or getattr(model, "rowCount", lambda: 0)() == 0:
            ui.info(self.view, "Print", "Nothing to print.")
            return

        try:
            html_chunks: List[str] = []

            # Heading and active filters summary
            html_chunks.append("<h2>Expenses</h2>")

            filters: List[str] = []
            if self.view.search_text:
                filters.append(f"Search: {html.escape(self.view.search_text)}")
            if self.view.selected_date:
                filters.append(f"Date: {html.escape(self.view.selected_date)}")
            if self.view.selected_category_id is not None:
                # show category text instead of id
                filters.append(f"Category: {html.escape(self.view.cmb_category.currentText())}")

            # Advanced filters (only if user actually set them)
            if self.view.date_from_str or self.view.date_to_str:
                filters.append(
                    f"Date range: {html.escape(self.view.date_from_str or '…')} → {html.escape(self.view.date_to_str or '…')}"
                )
            if self.view.amount_min_val is not None or self.view.amount_max_val is not None:
                filters.append(
                    f"Amount range: "
                    f"{self.view.amount_min_val if self.view.amount_min_val is not None else '…'}"
                    f" → "
                    f"{self.view.amount_max_val if self.view.amount_max_val is not None else '…'}"
                )

            if filters:
                html_chunks.append("<p>" + "<br>".join(filters) + "</p>")

            # Build HTML table from the current model
            cols = model.columnCount()
            rows = model.rowCount()

            html_chunks.append(
                "<table border='1' cellspacing='0' cellpadding='4' "
                "style='border-collapse:collapse; width:100%; font-size:10px;'>"
            )
            # headers
            html_chunks.append("<thead><tr>")
            for c in range(cols):
                hdr = model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
                text_hdr = "" if hdr is None else html.escape(str(hdr))
                html_chunks.append(f"<th>{text_hdr}</th>")
            html_chunks.append("</tr></thead><tbody>")

            # body
            for r in range(rows):
                html_chunks.append("<tr>")
                for c in range(cols):
                    idx = model.index(r, c)
                    val = model.data(idx, Qt.DisplayRole)
                    text = "" if val is None else html.escape(str(val))
                    hdr = model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
                    hdr_key = (str(hdr or "").strip().lower())
                    if hdr_key in {"amount", "total", "price"}:
                        html_chunks.append(
                            f"<td style='text-align:right;'>{text}</td>"
                        )
                    else:
                        html_chunks.append(f"<td>{text}</td>")
                html_chunks.append("</tr>")
            html_chunks.append("</tbody></table>")

            # Optional grand total (best-effort, computed from the last column)
            total_amount = None
            logger = logging.getLogger(__name__)
            skipped = 0
            skipped_vals: List[str] = []
            try:
                total_amount = 0.0
                for r in range(rows):
                    idx = model.index(r, cols - 1)
                    val = model.data(idx, Qt.DisplayRole)
                    try:
                        total_amount += float(val or 0.0)
                    except (ValueError, TypeError):
                        skipped += 1
                        try:
                            skipped_vals.append(str(val))
                        except Exception:
                            skipped_vals.append("<unrepr>")
                        continue
            except Exception:
                total_amount = None

            if total_amount is not None:
                html_chunks.append(
                    "<p style='margin-top:8px; text-align:right;'>"
                    f"<b>Total amount:</b> {total_amount:.2f}"
                    "</p>"
                )
                if skipped > 0:
                    logger.warning(
                        "Expense print: skipped %d rows with invalid amounts when computing total: %s",
                        skipped,
                        skipped_vals,
                    )
                    html_chunks.append(
                        f"<p style='margin-top:4px; font-size:8px; color:#666;'>"
                        f"Note: {skipped} row(s) were skipped due to invalid amounts."
                        f"</p>"
                    )

            html_content = "".join(html_chunks)

            doc = QTextDocument()
            doc.setHtml(html_content)

            printer = QPrinter(QPrinter.HighResolution)
            printer.setDocName("Expenses")

            dlg = QPrintDialog(printer, self.view)
            if dlg.exec() != QDialog.Accepted:
                return

            # Support both Qt6's print_ and older print
            if hasattr(doc, "print_"):
                doc.print_(printer)
            else:  # pragma: no cover - fallback path
                doc.print(printer)  # type: ignore[attr-defined]

        except Exception as e:
            self._handle_error("Failed to print expenses", e)
