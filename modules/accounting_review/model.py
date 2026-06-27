from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from modules.accounting.audit.dto import AuditEventRow


class AccountingReviewTableModel(QAbstractTableModel):
    HEADERS = (
        "Created",
        "Business Date",
        "Rule",
        "Event",
        "Source",
        "Party",
        "Amount",
        "Summary",
        "Status",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[AuditEventRow] = []

    def set_rows(self, rows: tuple[AuditEventRow, ...]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> AuditEventRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = (
            row.created_at,
            row.business_date,
            f"{row.rule_id} {row.rule_name}",
            row.event_type,
            f"{row.source_type}:{row.source_id or ''}",
            row.party_name or row.party_id or "",
            "" if row.amount is None else str(row.amount),
            row.human_summary,
            row.review_status,
        )
        return values[index.column()]
