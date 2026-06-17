from __future__ import annotations

import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QWidget, QTabWidget, QVBoxLayout, QComboBox, QCompleter

from ..base_module import BaseModule

from ...database.repositories.inventory_repo import InventoryRepo
from ...utils.product_lookup import DEFAULT_PRODUCT_LOOKUP_LIMIT, product_ids_by_exact_name, search_products
from .model import TransactionsTableModel
from .view import InventoryView
from .transactions import TransactionsView
from .stock_valuation import StockValuationWidget


class InventoryController(BaseModule):
    """
    Single controller for the Inventory module.

    Tabs:
      1) Stock Valuation       (per-product on-hand snapshot)
      2) Transactions          (recent list with adjustable LIMIT)
      3) Adjustments           (legacy entry flow wired into the live shell)
    """

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        super().__init__()
        self.conn = conn
        self.user = current_user
        self._repo = InventoryRepo(conn)
        self._adjustment_lookup_timer = QTimer()
        self._adjustment_lookup_timer.setSingleShot(True)
        self._adjustment_lookup_timer.setInterval(150)
        self._adjustment_lookup_timer.timeout.connect(self._refresh_adjustment_product_lookup)

        # Root container (tabbed)
        self._root = QWidget()
        layout = QVBoxLayout(self._root)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # --- Tab 1: Stock Valuation (per-product snapshot) ---
        self._valuation_view = StockValuationWidget(conn)
        self.tabs.addTab(self._valuation_view, "Stock Valuation")

        # --- Tab 2: Transactions (read-only recent list with LIMIT) ---
        self._transactions_view = TransactionsView(conn)
        self.tabs.addTab(self._transactions_view, "Transactions")

        # --- Tab 3: Adjustments (legacy entry flow) ---
        self._adjustment_view = InventoryView()
        self.tabs.addTab(self._adjustment_view, "Adjustments")
        self._wire_adjustment_view()
        self._reload_adjustment_products()
        self._reload_adjustment_recent()

    def get_widget(self) -> QWidget:
        return self._root

    def select_tab(self, name: str) -> bool:
        index = {"valuation": 0, "transactions": 1, "adjustments": 2}.get(name)
        if index is None:
            return False
        self.tabs.setCurrentIndex(index)
        return True

    # ------------------------------------------------------------------
    # Adjustment wiring
    # ------------------------------------------------------------------
    def _wire_adjustment_view(self) -> None:
        self._adjustment_view.cmb_product.setEditable(True)
        self._adjustment_view.cmb_product.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._configure_adjustment_product_completer()
        self._adjustment_view.cmb_product.currentIndexChanged.connect(
            lambda _=None: self._on_adjustment_product_changed()
        )
        self._adjustment_view.cmb_product.lineEdit().textEdited.connect(
            lambda _=None: self._schedule_adjustment_product_lookup()
        )
        self._adjustment_view.btn_record.clicked.connect(self._record_adjustment)

    def _reload_adjustment_products(self, search_text: str = "") -> None:
        view = self._adjustment_view
        search_text = (search_text or "").strip()
        view.cmb_product.blockSignals(True)
        try:
            view.cmb_product.clear()
            view.cmb_product.addItem("Select product...", userData=None)
            for item in search_products(self.conn, search_text, limit=DEFAULT_PRODUCT_LOOKUP_LIMIT):
                view.cmb_product.addItem(item.label, userData=item.product_id)
            if search_text:
                view.cmb_product.setEditText(search_text)
                view.cmb_product.lineEdit().setCursorPosition(len(search_text))
            else:
                view.cmb_product.setCurrentIndex(0)
            self._configure_adjustment_product_completer()
            if search_text and view.cmb_product.lineEdit().hasFocus():
                view.cmb_product.showPopup()
        finally:
            view.cmb_product.blockSignals(False)
        self._on_adjustment_product_changed()

    def _configure_adjustment_product_completer(self) -> None:
        completer = self._adjustment_view.cmb_product.completer()
        if completer is None:
            completer = QCompleter(
                self._adjustment_view.cmb_product.model(),
                self._adjustment_view.cmb_product,
            )
            self._adjustment_view.cmb_product.setCompleter(completer)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)

    def _schedule_adjustment_product_lookup(self) -> None:
        self._adjustment_lookup_timer.start()

    def _refresh_adjustment_product_lookup(self) -> None:
        self._reload_adjustment_products(self._adjustment_view.cmb_product.currentText())

    def _selected_adjustment_product_id(self) -> int | None:
        current = self._adjustment_view.cmb_product.currentData()
        current_index = self._adjustment_view.cmb_product.currentIndex()
        text = (self._adjustment_view.cmb_product.currentText() or "").strip()
        if (
            current is not None
            and current_index >= 0
            and text == (self._adjustment_view.cmb_product.itemText(current_index) or "").strip()
        ):
            return int(current)
        if not text or text == "Select product...":
            return None
        if text.endswith(")") and "(ID:" in text:
            try:
                start = text.rfind("(ID:") + len("(ID:")
                end = text.rfind(")")
                return int(text[start:end].strip())
            except Exception:
                pass
        ids = product_ids_by_exact_name(self.conn, text)
        return ids[0] if len(ids) == 1 else None

    def _reload_adjustment_uoms(self, product_id: int) -> None:
        view = self._adjustment_view
        view.cmb_uom.blockSignals(True)
        try:
            view.cmb_uom.clear()
            view.cmb_uom.addItem("Select UoM...", userData=None)
            rows = self.conn.execute(
                """
                SELECT
                    u.uom_id,
                    u.unit_name,
                    pu.is_base,
                    CAST(pu.factor_to_base AS REAL) AS factor_to_base
                FROM product_uoms pu
                JOIN uoms u ON u.uom_id = pu.uom_id
                WHERE pu.product_id = ?
                ORDER BY pu.is_base DESC, u.unit_name
                """,
                (int(product_id),),
            ).fetchall()
            for row in rows:
                if hasattr(row, "keys"):
                    uom_id = int(row["uom_id"])
                    unit_name = str(row["unit_name"])
                    is_base = int(row["is_base"] or 0)
                    factor = float(row["factor_to_base"] or 1.0)
                else:
                    uom_id = int(row[0])
                    unit_name = str(row[1])
                    is_base = int(row[2] or 0)
                    factor = float(row[3] or 1.0)
                label = f"{unit_name} (base)" if is_base else f"{unit_name} (x{factor:g})"
                view.cmb_uom.addItem(label, userData=uom_id)
            if view.cmb_uom.count() > 1:
                view.cmb_uom.setCurrentIndex(1)
        finally:
            view.cmb_uom.blockSignals(False)

    def _on_adjustment_product_changed(self) -> None:
        product_id = self._selected_adjustment_product_id()
        if product_id is None:
            self._adjustment_view.cmb_uom.blockSignals(True)
            try:
                self._adjustment_view.cmb_uom.clear()
                self._adjustment_view.cmb_uom.addItem("Select UoM...", userData=None)
            finally:
                self._adjustment_view.cmb_uom.blockSignals(False)
            return
        self._reload_adjustment_uoms(int(product_id))

    def _reload_adjustment_recent(self) -> None:
        rows = self._repo.recent_transactions(limit=50)
        self._adjustment_view.tbl_recent.setModel(TransactionsTableModel(rows))

    def _record_adjustment(self) -> None:
        product_id = self._selected_adjustment_product_id()
        uom_id = self._adjustment_view.selected_uom_id
        qty_text = self._adjustment_view.quantity_text
        date_text = self._adjustment_view.date_text
        notes = self._adjustment_view.notes_text

        if product_id is None:
            QMessageBox.warning(self._root, "Record Adjustment", "Pick a product first.")
            return
        if uom_id is None:
            QMessageBox.warning(self._root, "Record Adjustment", "Pick a UoM first.")
            return
        if not qty_text:
            QMessageBox.warning(self._root, "Record Adjustment", "Enter an adjustment quantity.")
            return

        try:
            quantity = float(qty_text)
        except Exception:
            QMessageBox.warning(self._root, "Record Adjustment", "Quantity must be numeric.")
            return

        if not date_text:
            QMessageBox.warning(self._root, "Record Adjustment", "Enter a date.")
            return

        try:
            tx_id = self._repo.add_adjustment(
                product_id=int(product_id),
                uom_id=int(uom_id),
                quantity=quantity,
                date=date_text,
                notes=notes,
                created_by=self.user.get("user_id") if isinstance(self.user, dict) else None,
            )
        except Exception as e:
            QMessageBox.warning(self._root, "Record Adjustment", f"Failed to record adjustment:\n{e}")
            return

        self._reload_adjustment_recent()
        self._adjustment_view.reset_inputs()
        QMessageBox.information(
            self._root,
            "Record Adjustment",
            f"Adjustment recorded. Transaction ID: {tx_id}.",
        )
