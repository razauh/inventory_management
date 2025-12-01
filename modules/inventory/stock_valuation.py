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

Update:
- Accept either an InventoryRepo or a raw sqlite3.Connection (repo_or_conn).
- Product loading uses the repo’s connection directly and keeps "(Select…)" first.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
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

from ...utils import ui_helpers as ui
from ...database.repositories.inventory_repo import InventoryRepo  # type: ignore


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
        # Avoid querying on every keystroke; refresh when user confirms
        # via Enter.
        self.txt_product.returnPressed.connect(self._refresh_clicked)
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

        Works whether `self.repo` is an InventoryRepo (has `.conn`) or a raw
        sqlite3.Connection.
        """
        # Build name→ids map and attach a completer to the line edit.
        # Some databases may contain products with duplicate names; we keep
        # all matching IDs so callers can disambiguate if needed.
        self._name_to_id: dict[str, list[int]] = {}
        self.txt_product.blockSignals(True)
        try:
            # Use the repo's connection directly; add real product_id as userData
            conn = getattr(self.repo, "conn", None) or self.repo
            rows = conn.execute(
                "SELECT product_id, name FROM products ORDER BY name"
            ).fetchall()
            display_names: list[str] = []
            # First pass: build name->ids map
            for r in rows:
                # tolerate Row or tuple
                if hasattr(r, "keys"):
                    pid = int(r["product_id"])
                    name = r["name"]
                else:
                    pid = int(r[0])
                    name = r[1]
                display = str(name)
                key = display.lower()
                ids = self._name_to_id.setdefault(key, [])
                ids.append(pid)

            # Build display labels, appending ID when duplicates exist for a name
            for r in rows:
                if hasattr(r, "keys"):
                    pid = int(r["product_id"])
                    name = r["name"]
                else:
                    pid = int(r[0])
                    name = r[1]
                display = str(name)
                key = display.lower()
                ids = self._name_to_id.get(key, [])
                if len(ids) > 1:
                    label = f"{display} (ID: {pid})"
                else:
                    label = display
                display_names.append(label)

            # Detect case-insensitive names mapped to multiple product IDs.
            # Strip a trailing " (ID:...)" only when it appears at the end so
            # product names that legitimately contain that substring are preserved.
            dup_keys = [k for k, ids in self._name_to_id.items() if len(ids) > 1]
            dup_labels = set()
            for name in display_names:
                base, sep, _rest = name.rpartition(" (ID:")
                key = (base if sep else name).lower()
                if key in dup_keys:
                    dup_labels.add(name)
            dup_labels = sorted(dup_labels)
            if dup_labels:
                try:
                    ui.info(
                        self,
                        "Duplicate product names",
                        "Multiple products share the following names:\n"
                        + ", ".join(dup_labels),
                    )
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "Failed to show duplicate product names info dialog: %s", e, exc_info=True
                    )

            # Deduplicate display labels while preserving original ordering
            seen_names: set[str] = set()
            unique_display_names: list[str] = []
            for nm in display_names:
                if nm not in seen_names:
                    seen_names.add(nm)
                    unique_display_names.append(nm)

            completer = QCompleter(unique_display_names, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.txt_product.setCompleter(completer)
        except Exception as e:
            ui.info(self, "Error", f"Failed to load products: {e}")
        finally:
            self.txt_product.blockSignals(False)

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
        name_raw = (self.txt_product.text() or "").strip()
        pid = self._selected_product_id()
        if pid is None:
            if name_raw:
                try:
                    ui.info(self, "Not found", f"Product '{name_raw}' was not found.")
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "Failed to show 'Product not found' dialog for %r: %s",
                        name_raw,
                        e,
                        exc_info=True,
                    )
                return
            self._clear_card()
            return
        self._load_product_snapshot(pid)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _selected_product_id(self) -> Optional[int]:
        raw = (self.txt_product.text() or "").strip()
        if not raw:
            return None

        # Prefer explicit "Name (ID: N)" format when present
        if raw.endswith(")") and "(ID:" in raw:
            try:
                start = raw.rfind("(ID:") + len("(ID:")
                end = raw.rfind(")")
                id_str = raw[start:end].strip()
                return int(id_str)
            except Exception:
                # Fall back to name-based lookup below
                pass

        # Strip a trailing " (ID: ...)" suffix, if present, before name-based lookup
        base, sep, _rest = raw.rpartition(" (ID:")
        lookup_name = base if sep and raw.endswith(")") else raw

        name = lookup_name.lower()
        ids = self._name_to_id.get(name) or []
        if not ids:
            return None
        # If multiple IDs share the same name, use the first one by default.
        try:
            return int(ids[0])
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
            # Normalize to InventoryRepo for method access
            repo = self.repo if isinstance(self.repo, InventoryRepo) else InventoryRepo(self.repo)
            rec = repo.stock_on_hand(product_id)
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
