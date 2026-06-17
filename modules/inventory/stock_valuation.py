# inventory_management/modules/inventory/stock_valuation.py
"""
Per-product stock valuation snapshot.

UI:
- Top row:  Product combobox (with "(Select…)" default) + Refresh button
- Card:     On Hand (qty + uom), Unit Value, Total Value
- Footer:   Status + source note for context

Behavior:
- On product change or Refresh -> query InventoryRepo.stock_on_hand(product_id)
- If no product selected -> clear card with status
- If repo returns nothing -> show "No inventory history"

Update:
- Accept either an InventoryRepo or a raw sqlite3.Connection (repo_or_conn).
- Product loading uses the repo’s connection directly and keeps "(Select…)" first.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QStringListModel
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCompleter,
    QPushButton,
    QGroupBox,
    QGridLayout,
)

from ...utils.helpers import fmt_money
from ...utils import ui_helpers as ui
from ...utils.product_lookup import DEFAULT_PRODUCT_LOOKUP_LIMIT, product_ids_by_exact_name, search_products
from ...database.repositories.inventory_repo import InventoryRepo  # type: ignore


PRODUCT_LOOKUP_DELAY_MS = 150


def _fmt_float(val: Optional[float], places: int = 2) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{places}f}"
    except Exception:
        return "N/A"


class StockValuationWidget(QWidget):
    """Compact, read-only per-product valuation card."""

    def __init__(self, repo_or_conn, parent: QWidget | None = None):
        """
        Accepts either:
          - InventoryRepo instance, or
          - raw sqlite3.Connection (will be used via InventoryRepo where needed)
        """
        super().__init__(parent)
        self.repo = repo_or_conn  # may be InventoryRepo or raw connection
        self._name_to_id: dict[str, list[int]] = {}
        self._product_lookup_timer = QTimer(self)
        self._product_lookup_timer.setSingleShot(True)
        self._product_lookup_timer.setInterval(PRODUCT_LOOKUP_DELAY_MS)
        self._product_lookup_timer.timeout.connect(self._refresh_product_lookup)
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

        self.txt_product = QLineEdit(self)
        self.txt_product.setPlaceholderText("Start typing product name…")
        self.txt_product.setMinimumWidth(240)
        row.addWidget(self.txt_product, 1)

        self._product_completion_model = QStringListModel(self)
        self._product_completer = QCompleter(self._product_completion_model, self)
        self._product_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._product_completer.setFilterMode(Qt.MatchContains)
        self.txt_product.setCompleter(self._product_completer)

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

        self.lbl_status = QLabel("Select a product")
        self.lbl_status.setStyleSheet("color:#666; font-size:11px;")
        grid.addWidget(self.lbl_status, 3, 0, 1, 2, Qt.AlignLeft)

        self.lbl_note = QLabel("Source: current stock snapshot")
        self.lbl_note.setStyleSheet("color:#666; font-size:11px;")
        grid.addWidget(self.lbl_note, 4, 0, 1, 2, Qt.AlignLeft)

        self.lbl_money_note = QLabel("Money values are shown in the app's base currency.")
        self.lbl_money_note.setStyleSheet("color:#666; font-size:11px;")
        grid.addWidget(self.lbl_money_note, 5, 0, 1, 2, Qt.AlignLeft)

        root.addWidget(self.grp_card, 0)

        # ------------------------------------------------------------------
        # Signals
        # ------------------------------------------------------------------
        # Avoid querying on every keystroke; refresh when user confirms
        # via Enter.
        self.txt_product.textEdited.connect(lambda _=None: self._schedule_product_lookup())
        self.txt_product.returnPressed.connect(self._refresh_clicked)
        self.btn_refresh.clicked.connect(self._refresh_clicked)

        # ------------------------------------------------------------------
        # Init
        # ------------------------------------------------------------------
        self._load_products()
        self._clear_card("Select a product")

    # ----------------------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------------------
    def _load_products(self, search_text: str = "") -> None:
        """
        Populate the product completer with a capped lookup result.

        Works whether `self.repo` is an InventoryRepo (has `.conn`) or a raw
        sqlite3.Connection.
        """
        self._name_to_id = {}
        self.txt_product.blockSignals(True)
        try:
            conn = getattr(self.repo, "conn", None) or self.repo
            labels = []
            for item in search_products(conn, search_text, limit=DEFAULT_PRODUCT_LOOKUP_LIMIT):
                self._name_to_id.setdefault(item.name.lower(), []).append(item.product_id)
                labels.append(item.label)
            self._product_completion_model.setStringList(labels)
        except Exception as e:
            ui.info(self, "Error", f"Failed to load products: {e}")
        finally:
            self.txt_product.blockSignals(False)

    # ----------------------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------------------
    def _schedule_product_lookup(self) -> None:
        self._product_lookup_timer.start()

    def _refresh_product_lookup(self) -> None:
        self._load_products(self.txt_product.text())

    def _on_filters_changed(self) -> None:
        """React to product change: load snapshot or clear if none selected."""
        pid, _reason = self._resolve_selected_product()
        if pid is None:
            self._clear_card("Select a product")
            return
        self._load_product_snapshot(pid)

    def _refresh_clicked(self) -> None:
        name_raw = (self.txt_product.text() or "").strip()
        pid, reason = self._resolve_selected_product()
        if pid is None:
            if name_raw:
                try:
                    if reason == "ambiguous":
                        ui.info(
                            self,
                            "Ambiguous product",
                            f"Product '{name_raw}' matches more than one product. Pick one with its ID.",
                        )
                    else:
                        ui.info(self, "Not found", f"Product '{name_raw}' was not found.")
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "Failed to show 'Product not found' dialog for %r: %s",
                        name_raw,
                        e,
                        exc_info=True,
                    )
                self._clear_card("Select a product")
                return
            self._clear_card("Select a product")
            return
        self._load_product_snapshot(pid)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _resolve_selected_product(self) -> tuple[Optional[int], Optional[str]]:
        raw = (self.txt_product.text() or "").strip()
        if not raw:
            return None, None

        # Prefer explicit "Name (ID: N)" format when present
        if raw.endswith(")") and "(ID:" in raw:
            try:
                start = raw.rfind("(ID:") + len("(ID:")
                end = raw.rfind(")")
                id_str = raw[start:end].strip()
                return int(id_str), None
            except Exception:
                # Fall back to name-based lookup below
                pass

        # Strip a trailing " (ID: ...)" suffix, if present, before name-based lookup
        base, sep, _rest = raw.rpartition(" (ID:")
        lookup_name = base if sep and raw.endswith(")") else raw

        name = lookup_name.lower()
        ids = self._name_to_id.get(name) or []
        if not ids:
            conn = getattr(self.repo, "conn", None) or self.repo
            ids = product_ids_by_exact_name(conn, lookup_name)
        if not ids:
            return None, "not_found"
        if len(ids) > 1:
            return None, "ambiguous"
        try:
            return int(ids[0]), None
        except Exception:
            return None, "not_found"

    def _set_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def _clear_card(self, status_text: str) -> None:
        self.val_on_hand.setText("—")
        self.val_unit_value.setText("—")
        self.val_total_value.setText("—")
        self._set_status(status_text)

    def _load_product_snapshot(self, product_id: int) -> None:
        """
        Query repo for a single product snapshot and update the card.
        Handles None / missing fields gracefully.
        """
        try:
            # Normalize to InventoryRepo for method access
            repo = self.repo if isinstance(self.repo, InventoryRepo) else InventoryRepo(self.repo)
            rec = repo.stock_on_hand(product_id)
        except Exception as e:
            ui.info(self, "Error", f"Failed to load stock snapshot: {e}")
            self._clear_card("Snapshot unavailable")
            return

        if not rec:
            # No row for the product in the view
            self._clear_card("No inventory history")
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
        self.val_unit_value.setText(fmt_money(unit))
        self.val_total_value.setText(fmt_money(total))
        self._set_status("Snapshot loaded")
