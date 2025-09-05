from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLineEdit, QLabel
)

from ...widgets.table_view import TableView


class InventoryView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---------- Adjustment controls row ----------
        row = QHBoxLayout()
        row.setSpacing(6)

        self.cmb_product = QComboBox(objectName="cmb_product")
        self.cmb_product.setMinimumWidth(220)

        self.cmb_uom = QComboBox(objectName="cmb_uom")
        self.cmb_uom.setMinimumWidth(120)

        self.txt_qty = QLineEdit(objectName="txt_qty")
        self.txt_qty.setPlaceholderText("e.g., +5 or -3")
        # Soft numeric guidance (controller still validates)
        dv = QDoubleValidator(self)
        dv.setNotation(QDoubleValidator.StandardNotation)
        self.txt_qty.setValidator(dv)
        self.txt_qty.setMinimumWidth(90)

        self.txt_date = QLineEdit(objectName="txt_date")
        self.txt_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_date.setMinimumWidth(120)

        self.txt_notes = QLineEdit(objectName="txt_notes")
        self.txt_notes.setPlaceholderText("Optional notes")

        self.btn_record = QPushButton("Record Adjustment", objectName="btn_record")

        row.addWidget(QLabel("Product"), 0, Qt.AlignVCenter)
        row.addWidget(self.cmb_product, 2)
        row.addWidget(QLabel("UoM"), 0, Qt.AlignVCenter)
        row.addWidget(self.cmb_uom, 1)
        row.addWidget(QLabel("Qty"), 0, Qt.AlignVCenter)
        row.addWidget(self.txt_qty, 1)
        row.addWidget(QLabel("Date"), 0, Qt.AlignVCenter)
        row.addWidget(self.txt_date, 1)
        row.addWidget(QLabel("Notes"), 0, Qt.AlignVCenter)
        row.addWidget(self.txt_notes, 2)
        row.addWidget(self.btn_record, 0, Qt.AlignVCenter)

        root.addLayout(row)

        # ---------- Recent transactions table ----------
        self.tbl_recent = TableView(objectName="tbl_recent")
        # Friendly defaults for read-only browsing
        self.tbl_recent.setAlternatingRowColors(True)
        self.tbl_recent.setSelectionBehavior(self.tbl_recent.SelectionBehavior.SelectRows)
        self.tbl_recent.setSelectionMode(self.tbl_recent.SelectionMode.SingleSelection)
        self.tbl_recent.setEditTriggers(self.tbl_recent.EditTrigger.NoEditTriggers)
        self.tbl_recent.horizontalHeader().setStretchLastSection(True)

        root.addWidget(self.tbl_recent, 1)

        # Keyboard focus: start at quantity to speed up entry
        self.txt_qty.setFocus()

    # ---------- Convenience accessors (optional) ----------

    @property
    def selected_product_id(self) -> int | None:
        return self.cmb_product.currentData()

    @property
    def selected_uom_id(self) -> int | None:
        return self.cmb_uom.currentData()

    @property
    def quantity_text(self) -> str:
        return (self.txt_qty.text() or "").strip()

    @property
    def date_text(self) -> str:
        return (self.txt_date.text() or "").strip()

    @property
    def notes_text(self) -> str | None:
        txt = (self.txt_notes.text() or "").strip()
        return txt or None

    def reset_inputs(self) -> None:
        """Call after a successful save if you want to clear just the entry bits."""
        self.txt_qty.clear()
        self.txt_notes.clear()
        self.txt_qty.setFocus()
