from PySide6.QtWidgets import QWidget
from ..base_module import BaseModule
import sqlite3
from .view import InventoryView
from .model import TransactionsTableModel
from ...database.repositories.inventory_repo import InventoryRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.ui_helpers import info, error
from ...utils.validators import is_positive_number
from ...utils.helpers import today_str

class InventoryController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        self.conn = conn
        self.user = current_user
        self.view = InventoryView()
        self.inv = InventoryRepo(conn)
        self.prod = ProductsRepo(conn)
        self._wire()
        self._load_products()
        self._reload_recent()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_record.clicked.connect(self._record)
        # default date
        self.view.txt_date.setText(today_str())

    def _load_products(self):
        self.view.cmb_product.clear()
        for p in self.prod.list_products():
            self.view.cmb_product.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self._load_uoms_for_selected()
        self.view.cmb_product.currentIndexChanged.connect(self._load_uoms_for_selected)

    def _load_uoms_for_selected(self):
        self.view.cmb_uom.clear()
        pid = self.view.cmb_product.currentData()
        if not pid:
            return
        # list product-specific UOMs if any, else all UOMs
        puoms = self.prod.product_uoms(pid)
        if puoms:
            for m in puoms:
                self.view.cmb_uom.addItem(m["unit_name"], m["uom_id"])
        else:
            for u in self.prod.list_uoms():
                self.view.cmb_uom.addItem(u["unit_name"], u["uom_id"])

    def _reload_recent(self):
        rows = self.inv.recent_transactions()
        model = TransactionsTableModel(rows)
        self.view.tbl_recent.setModel(model)
        self.view.tbl_recent.resizeColumnsToContents()
        self.model = model

    def _record(self):
        pid = self.view.cmb_product.currentData()
        uom_id = self.view.cmb_uom.currentData()
        qty_text = self.view.txt_qty.text().strip()
        date = self.view.txt_date.text().strip() or today_str()
        notes = self.view.txt_notes.text().strip() or None

        # qty can be positive or negative for 'adjustment'; must be numeric
        try:
            qty = float(qty_text)
        except Exception:
            error(self.view, "Invalid", "Quantity must be a number (e.g., 5 or -3).")
            return

        self.inv.add_adjustment(
            product_id=int(pid), uom_id=int(uom_id), quantity=qty,
            date=date, notes=notes, created_by=(self.user["user_id"] if self.user else None)
        )
        info(self.view, "Saved", "Adjustment recorded.")
        self._reload_recent()
