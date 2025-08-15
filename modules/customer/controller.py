from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
import sqlite3

from ..base_module import BaseModule
from .view import CustomerView
from .form import CustomerForm
from .model import CustomersTableModel
from ...database.repositories.customers_repo import CustomersRepo
from ...utils.ui_helpers import info

class CustomerController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = CustomersRepo(conn)
        self.view = CustomerView()
        self._wire()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.search.textChanged.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_customers()
        self.base = CustomersTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        self.view.table.resizeColumnsToContents()

        # selection model is NEW after setModel → connect every time (no disconnects)
        sel = self.view.table.selectionModel()
        sel.selectionChanged.connect(self._update_details)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.table.selectRow(0)
        # ensure right pane updates even if no selection event fired yet
        self._update_details()

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_id(self) -> int | None:
        idxs = self.view.table.selectionModel().selectedRows()
        if not idxs: return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row()).customer_id

    def _current_row(self) -> dict | None:
        cid = self._selected_id()
        cust = self.repo.get(cid) if cid else None
        return cust.__dict__ if cust else None

    def _update_details(self, *args):
        self.view.details.set_data(self._current_row())

    # --- CRUD ---
    def _add(self):
        dlg = CustomerForm(self.view)
        if not dlg.exec(): return
        p = dlg.payload()
        if not p: return
        cid = self.repo.create(**p)
        info(self.view, "Saved", f"Customer #{cid} created.")
        self._reload()

    def _edit(self):
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer to edit.")
            return
        current = self.repo.get(cid)
        dlg = CustomerForm(self.view, initial=current.__dict__)
        if not dlg.exec(): return
        p = dlg.payload()
        if not p: return
        self.repo.update(cid, **p)
        info(self.view, "Saved", f"Customer #{cid} updated.")
        self._reload()

    def _delete(self):
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer to delete.")
            return
        self.repo.delete(cid)
        info(self.view, "Deleted", f"Customer #{cid} removed.")
        self._reload()
