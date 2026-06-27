from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modules.accounting.audit.repository import REVIEW_STATUSES


class AccountingReviewView(QWidget):
    refresh_requested = Signal()
    export_requested = Signal(str)
    review_saved = Signal(str, str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("accountingReviewView")
        root = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.rule_area = QLineEdit()
        self.rule_area.setPlaceholderText("Rule area")
        self.rule_query = QLineEdit()
        self.rule_query.setPlaceholderText("Rule id/name")
        self.event_type = QLineEdit()
        self.event_type.setPlaceholderText("Event type")
        self.status = QComboBox()
        self.status.addItem("All", "")
        for status in sorted(REVIEW_STATUSES):
            self.status.addItem(status, status)
        self.party = QLineEdit()
        self.party.setPlaceholderText("Party")
        self.source_type = QLineEdit()
        self.source_type.setPlaceholderText("Source type")
        self.amount_min = QLineEdit()
        self.amount_min.setPlaceholderText("Min")
        self.amount_max = QLineEdit()
        self.amount_max.setPlaceholderText("Max")
        self.refresh_button = QPushButton("Refresh")
        self.export_button = QPushButton("Export CSV")
        for widget in (
            self.date_from, self.date_to, self.rule_area, self.rule_query,
            self.event_type, self.status, self.party, self.source_type,
            self.amount_min, self.amount_max, self.refresh_button, self.export_button,
        ):
            filters.addWidget(widget)
        root.addLayout(filters)

        splitter = QSplitter()
        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        splitter.addWidget(self.table)

        details = QWidget()
        form = QFormLayout(details)
        self.source_label = QLabel("")
        self.party_label = QLabel("")
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.snapshots = QPlainTextEdit()
        self.snapshots.setReadOnly(True)
        self.status_edit = QComboBox()
        for status in sorted(REVIEW_STATUSES):
            self.status_edit.addItem(status, status)
        self.notes = QPlainTextEdit()
        self.expected_behavior = QPlainTextEdit()
        self.linked_issue = QLineEdit()
        self.save_button = QPushButton("Save Review")
        form.addRow("Source", self.source_label)
        form.addRow("Party", self.party_label)
        form.addRow("Summary", self.summary)
        form.addRow("Snapshots", self.snapshots)
        form.addRow("Status", self.status_edit)
        form.addRow("Notes", self.notes)
        form.addRow("Expected", self.expected_behavior)
        form.addRow("Linked Issue", self.linked_issue)
        form.addRow("", self.save_button)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.export_button.clicked.connect(self._pick_export_path)
        self.save_button.clicked.connect(self._save_review)

    def filters(self) -> dict:
        out = {
            "date_from": self.date_from.date().toString("yyyy-MM-dd"),
            "date_to": self.date_to.date().toString("yyyy-MM-dd"),
            "rule_area": self.rule_area.text().strip(),
            "rule_query": self.rule_query.text().strip(),
            "event_type": self.event_type.text().strip(),
            "status": self.status.currentData(),
            "party_query": self.party.text().strip(),
            "source_type": self.source_type.text().strip(),
            "amount_min": self.amount_min.text().strip(),
            "amount_max": self.amount_max.text().strip(),
        }
        return {k: v for k, v in out.items() if v not in ("", None)}

    def set_details(self, row) -> None:
        if row is None:
            self.source_label.setText("")
            self.party_label.setText("")
            self.summary.setText("")
            self.snapshots.setPlainText("")
            return
        self.source_label.setText(f"{row.source_type}:{row.source_id or ''}")
        self.party_label.setText(f"{row.party_type or ''}:{row.party_name or row.party_id or ''}")
        self.summary.setText(row.human_summary)
        self.snapshots.setPlainText(
            "Input:\n"
            + str(row.input_snapshot)
            + "\n\nOutput:\n"
            + str(row.output_snapshot)
            + "\n\nSide effects:\n"
            + str(row.side_effects)
            + f"\n\nSource:\n{row.source_module}.{row.source_function}"
        )
        idx = self.status_edit.findData(row.review_status)
        if idx >= 0:
            self.status_edit.setCurrentIndex(idx)
        self.notes.setPlainText(row.review_notes or "")
        self.expected_behavior.setPlainText(row.expected_behavior or "")
        self.linked_issue.setText(row.linked_issue or "")

    def _save_review(self) -> None:
        self.review_saved.emit(
            str(self.status_edit.currentData()),
            self.notes.toPlainText(),
            self.expected_behavior.toPlainText(),
            self.linked_issue.text(),
        )

    def _pick_export_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Accounting Review", "", "CSV Files (*.csv)")
        if path:
            self.export_requested.emit(path)
