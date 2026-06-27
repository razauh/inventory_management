from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QDate

from modules.accounting.audit.repository import AccountingAuditRepository
from modules.base_module import BaseModule

from .model import AccountingReviewTableModel
from .view import AccountingReviewView


class AccountingReviewController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None = None):
        super().__init__()
        self.conn = conn
        self.current_user = current_user or {}
        self.view = AccountingReviewView()
        self.model = AccountingReviewTableModel()
        self.view.table.setModel(self.model)
        today = date.today()
        self.view.date_from.setDate(QDate(today.year, today.month, today.day).addDays(-1))
        self.view.date_to.setDate(QDate(today.year, today.month, today.day))
        self.view.refresh_requested.connect(self.refresh)
        self.view.export_requested.connect(self.export_csv)
        self.view.review_saved.connect(self.save_review)
        self.view.table.selectionModel().currentRowChanged.connect(self._show_selected)

    def get_widget(self):
        return self.view

    def refresh(self) -> None:
        self.model.set_rows(AccountingAuditRepository(self.conn).list_events(self._filters()))
        self.view.table.resizeColumnsToContents()

    def export_csv(self, path: str) -> None:
        AccountingAuditRepository(self.conn).export_csv(path, self._filters())

    def save_review(
        self,
        status: str,
        notes: str,
        expected_behavior: str,
        linked_issue: str,
    ) -> None:
        row = self._selected_row()
        if row is None:
            return
        AccountingAuditRepository(self.conn).upsert_review(
            row.audit_event_id,
            status=status,
            notes=notes,
            expected_behavior=expected_behavior,
            linked_issue=linked_issue,
            reviewed_by=self.current_user.get("user_id"),
        )
        self.conn.commit()
        self.refresh()

    def _filters(self) -> dict:
        filters = self.view.filters()
        for key in ("amount_min", "amount_max"):
            if key in filters:
                try:
                    filters[key] = float(filters[key])
                except ValueError:
                    filters.pop(key, None)
        return filters

    def _selected_row(self):
        index = self.view.table.currentIndex()
        return self.model.row_at(index.row()) if index.isValid() else None

    def _show_selected(self, current, previous) -> None:
        self.view.set_details(self.model.row_at(current.row()))
