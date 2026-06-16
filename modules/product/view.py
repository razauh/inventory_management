from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...widgets.table_view import TableView
from .components import ProductDetailsPanel, ProductSummaryBar, ProductToolbar


class ProductView(QWidget):
    selection_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.toolbar = ProductToolbar()
        self.btn_add = self.toolbar.btn_add
        self.btn_import = self.toolbar.btn_import
        self.btn_edit = self.toolbar.btn_edit
        self.btn_delete = self.toolbar.btn_delete
        self.btn_price = self.toolbar.btn_price

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search products by id, name, category, description, or UoM")
        self.toolbar.wire(self.search)
        root.addWidget(self.toolbar)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        search_row.addWidget(self.search, 1)
        root.addLayout(search_row)

        self.summary = ProductSummaryBar()
        root.addWidget(self.summary)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        self.table = TableView()
        body.addWidget(self.table)

        self.details = ProductDetailsPanel()
        self.details.setMinimumWidth(240)
        body.addWidget(self.details)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 1)
        body.setSizes([840, 240])

        root.addWidget(body, 1)

        pager = QHBoxLayout()
        pager.addStretch(1)
        self.btn_prev_page = QPushButton("Prev Page")
        self.lbl_page = QLabel("Page 1 / 1")
        self.lbl_page.setMinimumWidth(120)
        self.lbl_page.setAlignment(Qt.AlignCenter)
        self.btn_next_page = QPushButton("Next Page")
        pager.addWidget(self.btn_prev_page)
        pager.addWidget(self.lbl_page)
        pager.addWidget(self.btn_next_page)
        root.addLayout(pager)
