from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
from PySide6.QtWidgets import QWidget
import sqlite3
from ..base_module import BaseModule
from .view import ProductView
from .form import ProductForm
from .model import ProductsTableModel
from ...database.repositories.products_repo import ProductsRepo, DomainError
from ...utils.ui_helpers import info, error


class ProductController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = ProductsRepo(conn)
        self.view = ProductView()
        self._wired = False  # ensure signals are connected only once
        self._connect_signals()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _connect_signals(self):
        # Guard against double-connecting when controller/view is re-created
        if self._wired:
            return
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._delete)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.search.textChanged.connect(self._apply_filter)
        self._wired = True

    def _build_model(self):
        rows = self.repo.list_products()
        self.base_model = ProductsTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base_model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        self.view.table.resizeColumnsToContents()

    def _reload(self):
        self._build_model()

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_id(self) -> int | None:
        idxs = self.view.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src_index = self.proxy.mapToSource(idxs[0])
        return self.base_model.at(src_index.row()).product_id

    def _add(self):
        dlg = ProductForm(self.view, repo=self.repo)
        if not dlg.exec():
            return
        pdata = dlg.payload()
        if not pdata:
            return
        pid = self.repo.create(**pdata["product"])
        # Always set base UoM
        base_id = pdata["uoms"]["base_uom_id"]
        self.repo.set_base_uom(pid, base_id)
        # Alternates + roles if enabled
        roles = {base_id: (True, True)}
        all_alts = {}
        if pdata["uoms"]["enabled_sales"]:
            for a in pdata["uoms"]["sales_alts"]:
                all_alts[a["uom_id"]] = a
                prev = roles.get(a["uom_id"], (False, False))
                roles[a["uom_id"]] = (True, prev[1])
        for a in all_alts.values():
            self.repo.add_alt_uom(pid, a["uom_id"], a["factor_to_base"])
        if len(roles) > 1:  # only persist roles if there were alternates
            self.repo.upsert_roles(pid, roles)
        info(self.view, "Saved", f"Product #{pid} created.")
        self._reload()

    def _edit(self):
        pid = self._selected_id()
        if not pid:
            info(self.view, "Select", "Please select a product to edit.")
            return
        current = self.repo.get(pid)
        maps = self.repo.product_uoms(pid)
        roles = self.repo.roles_map(pid)
        dlg = ProductForm(
            self.view,
            repo=self.repo,
            initial_product=current,
            initial_uoms=maps,
            initial_roles=roles,
        )
        if not dlg.exec():
            return
        pdata = dlg.payload()
        if not pdata:
            return
        self.repo.update(pid, **pdata["product"])
        base_id = pdata["uoms"]["base_uom_id"]
        self.repo.set_base_uom(pid, base_id)
        roles_map = {base_id: (True, True)}
        all_alts = {}
        if pdata["uoms"]["enabled_sales"]:
            for a in pdata["uoms"]["sales_alts"]:
                all_alts[a["uom_id"]] = a
                prev = roles_map.get(a["uom_id"], (False, False))
                roles_map[a["uom_id"]] = (True, prev[1])
        for a in all_alts.values():
            self.repo.add_alt_uom(pid, a["uom_id"], a["factor_to_base"])
        if len(roles_map) > 1:
            self.repo.upsert_roles(pid, roles_map)
        info(self.view, "Saved", f"Product #{pid} updated.")
        self._reload()

    def _delete(self):
        """
        Delete the selected product if and only if it is not referenced by any transactions or UoM mappings.
        Shows an error dialog (DomainError message) if deletion is blocked.
        """
        pid = self._selected_id()
        if not pid:
            info(self.view, "Select", "Please select a product to delete.")
            return
        try:
            # products_repo.delete() already blocks deletion when referenced (transactions/mappings)
            self.repo.delete(pid)
        except DomainError as de:
            # Exact domain message, e.g. "Cannot delete product: it is referenced by transactions or mappings..."
            error(self.view, "Blocked", str(de))
            return
        info(self.view, "Deleted", f"Product #{pid} deleted.")
        self._reload()
