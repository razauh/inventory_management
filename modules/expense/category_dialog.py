from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox, QAbstractItemView
)

class CategoryDialog(QDialog):
    def __init__(self, parent, repo):
        super().__init__(parent)
        self.setWindowTitle("Manage Categories")
        self.repo = repo

        layout = QVBoxLayout(self)

        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels(["ID", "Name"])
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.tbl)

        row = QHBoxLayout()
        self.edt_name = QLineEdit()
        self.edt_name.setPlaceholderText("New / renamed category")
        btn_add = QPushButton("Add")
        btn_rename = QPushButton("Rename")
        btn_delete = QPushButton("Delete")
        row.addWidget(self.edt_name)
        row.addWidget(btn_add)
        row.addWidget(btn_rename)
        row.addWidget(btn_delete)
        layout.addLayout(row)

        btn_add.clicked.connect(self._add)
        btn_rename.clicked.connect(self._rename)
        btn_delete.clicked.connect(self._delete)

        self._reload()

    def _reload(self):
        cats = self.repo.list_categories()  # returns dataclasses with id+name :contentReference[oaicite:4]{index=4}
        self.tbl.setRowCount(len(cats))
        for r, c in enumerate(cats):
            self.tbl.setItem(r, 0, QTableWidgetItem(str(c.category_id)))
            self.tbl.setItem(r, 1, QTableWidgetItem(c.name))
        self.tbl.resizeColumnsToContents()

    def _selected_id(self):
        sel = self.tbl.selectionModel().selectedRows()
        if not sel:
            return None
        return int(self.tbl.item(sel[0].row(), 0).text())

    def _add(self):
        name = self.edt_name.text().strip()
        if not name:
            QMessageBox.information(self, "Name", "Enter a category name.")
            return
        self.repo.create_category(name)  # exists in repo :contentReference[oaicite:5]{index=5}
        self.edt_name.clear()
        self._reload()

    def _rename(self):
        cat_id = self._selected_id()
        if cat_id is None:
            QMessageBox.information(self, "Select", "Pick a category row to rename.")
            return
        name = self.edt_name.text().strip()
        if not name:
            QMessageBox.information(self, "Name", "Enter a new name.")
            return
        self.repo.update_category(cat_id, name)  # exists :contentReference[oaicite:6]{index=6}
        self.edt_name.clear()
        self._reload()

    def _delete(self):
        cat_id = self._selected_id()
        if cat_id is None:
            QMessageBox.information(self, "Select", "Pick a category row to delete.")
            return
        self.repo.delete_category(cat_id)  # exists :contentReference[oaicite:7]{index=7}
        self._reload()
