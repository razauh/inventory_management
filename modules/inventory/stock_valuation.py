# inventory_management/modules/inventory/stock_valuation.py
"""
Per-product stock valuation snapshot.

UI:
- Top row:  Product combobox (with "(Select…)" default) + Refresh button
- Card:     On Hand (qty + uom), Unit Value, Total Value
- Footer:   Small note ("from v_stock_on_hand") for context

Behavior:
- On product change or Refresh -> query InventoryRepo.stock_on_hand(product_id)
- If no product selected -> clear card
- If repo returns nothing -> show N/A/0.00 gracefully
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QGroupBox,
    QGridLayout,
)

from ...utils import ui_helpers as ui
from ...database.repositories.inventory_repo import InventoryRepo


def _fmt_float(val: Optional[float], places: int = 2) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{places}f}"
    except Exception:
        return "N/A"


class StockValuationWidget(QWidget):
    """Compact, read-only per-product valuation card."""

    def __init__(self, repo: InventoryRepo, parent: QWidget | None = None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("Inventory — Stock Valuation")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ------------------------------------------------------------------
        # Top row: Product + Refresh
        # ------------------------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(6)

        lbl_prod = QLabel("Product:")
        lbl_prod.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(lbl_prod)

        self.cmb_product = QComboBox(self)
        self.cmb_product.setMinimumWidth(240)
        row.addWidget(self.cmb_product, 1)

        self.btn_refresh = QPushButton("Refresh")
        row.addWidget(self.btn_refresh)

        root.addLayout(row)

        # ------------------------------------------------------------------
        # Card (group) with snapshot fields
        # ------------------------------------------------------------------
        self.grp_card = QGroupBox("Valuation Snapshot")
        grid = QGridLayout(self.grp_card)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        # On Hand
        self.lbl_on_hand_title = QLabel("On Hand:")
        self.lbl_on_hand_title.setStyleSheet("font-weight:600;")
        self.val_on_hand = QLabel("—")
        grid.addWidget(self.lbl_on_hand_title, 0, 0, Qt.AlignRight)
        grid.addWidget(self.val_on_hand,       0, 1, Qt.AlignLeft)

        # Unit Value
        self.lbl_unit_value_title = QLabel("Unit Value:")
        self.lbl_unit_value_title.setStyleSheet("font-weight:600;")
        self.val_unit_value = QLabel("—")
        grid.addWidget(self.lbl_unit_value_title, 1, 0, Qt.AlignRight)
        grid.addWidget(self.val_unit_value,       1, 1, Qt.AlignLeft)

        # Total Value
        self.lbl_total_value_title = QLabel("Total Value:")
        self.lbl_total_value_title.setStyleSheet("font-weight:600;")
        self.val_total_value = QLabel("—")
        grid.addWidget(self.lbl_total_value_title, 2, 0, Qt.AlignRight)
        grid.addWidget(self.val_total_value,       2, 1, Qt.AlignLeft)

        # Optional note / source
        self.lbl_note = QLabel("Source: v_stock_on_hand")
        self.lbl_note.setStyleSheet("color:#666; font-size:11px;")
        grid.addWidget(self.lbl_note, 3, 0, 1, 2, Qt.AlignLeft)

        root.addWidget(self.grp_card, 0)

        # ------------------------------------------------------------------
        # Signals
        # ------------------------------------------------------------------
        self.cmb_product.currentIndexChanged.connect(lambda _=None: self._on_filters_changed())
        self.btn_refresh.clicked.connect(self._refresh_clicked)

        # ------------------------------------------------------------------
        # Init
        # ------------------------------------------------------------------
        self._load_products()
        self._clear_card()

    # ----------------------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------------------
    def _load_products(self) -> None:
        """
        Populate the product combo:
          0: "(Select…)" -> userData=None
          n: product name -> userData=product_id
        """
        self.cmb_product.blockSignals(True)
        try:
            self.cmb_product.clear()
            self.cmb_product.addItem("(Select…)", userData=None)

            rows = self.repo.conn.execute(
                "SELECT product_id AS id, name AS name FROM products ORDER BY name"
            ).fetchall()
            for r in rows:
                self.cmb_product.addItem(r["name"], r["id"])
        except Exception as e:
            ui.info(self, "Error", f"Failed to load products: {e}")
        finally:
            self.cmb_product.blockSignals(False)

    # ----------------------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------------------
    def _on_filters_changed(self) -> None:
        """React to product change: load snapshot or clear if none selected."""
        pid = self._selected_product_id()
        if pid is None:
            self._clear_card()
            return
        self._load_product_snapshot(pid)

    def _refresh_clicked(self) -> None:
        pid = self._selected_product_id()
        if pid is None:
            self._clear_card()
            return
        self._load_product_snapshot(pid)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _selected_product_id(self) -> Optional[int]:
        data = self.cmb_product.currentData()
        try:
            return int(data) if data is not None else None
        except Exception:
            return None

    def _clear_card(self) -> None:
        self.val_on_hand.setText("—")
        self.val_unit_value.setText("—")
        self.val_total_value.setText("—")

    def _load_product_snapshot(self, product_id: int) -> None:
        """
        Query repo for a single product snapshot and update the card.
        Handles None / missing fields gracefully.
        """
        try:
            rec = self.repo.stock_on_hand(product_id)
        except Exception as e:
            ui.info(self, "Error", f"Failed to load stock snapshot: {e}")
            self._clear_card()
            return

        if not rec:
            # No row for the product in the view
            self._clear_card()
            return

        qty = rec.get("on_hand_qty")
        uom = rec.get("uom_name")
        unit = rec.get("unit_value")
        total = rec.get("total_value")

        # Fallback: if total is missing but qty+unit exist, compute here
        if total is None and qty is not None and unit is not None:
            try:
                total = float(qty) * float(unit)
            except Exception:
                total = None

        # On Hand: "X uom" or "0.00 uom"/"N/A" when unknown
        qty_str = _fmt_float(qty)
        if qty_str == "N/A":
            on_hand_str = "N/A"
        else:
            on_hand_str = f"{qty_str} {uom or ''}".strip()

        self.val_on_hand.setText(on_hand_str)
        self.val_unit_value.setText(_fmt_float(unit))
        self.val_total_value.setText(_fmt_float(total))
