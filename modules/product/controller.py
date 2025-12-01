from contextlib import contextmanager
import logging
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
from PySide6.QtWidgets import (
    QWidget,
    QLineEdit,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QDialogButtonBox,
)
import sqlite3
from ..base_module import BaseModule
from .view import ProductView
from .form import ProductForm
from .model import ProductsTableModel
from ...database.repositories.products_repo import ProductsRepo, DomainError
from ...utils.ui_helpers import info, error
from ...utils.validators import try_parse_float


class PriceDialog(QDialog):
    """
    Dialog to set sale prices for:
      - Base (bulk) UoM
      - Retail UoM (one of the alternates)

    It keeps base and retail prices consistent via the factor_to_base.
    """

    def __init__(
        self,
        parent: QWidget | None,
        *,
        product_id: int,
        base_uom_name: str | None,
        cost_base: float,
        sale_base: float,
        alt_uoms: list[dict],
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Set price for product #{product_id}")
        self._alt_uoms = alt_uoms
        self._cost_base = float(cost_base or 0.0)
        self._syncing = False  # avoid recursive updates

        root = QVBoxLayout(self)

        # Base price row
        base_row = QHBoxLayout()
        self.edt_base_price = QLineEdit()
        self.edt_base_price.setPlaceholderText("0.00")
        if sale_base > 0:
            self.edt_base_price.setText(f"{sale_base:.2f}")
        lbl_base_uom = QLabel(base_uom_name or "Base")
        lbl_cost = QLabel(f"Last cost per base: {self._cost_base:.2f}")
        base_row.addWidget(QLabel("Sale price per base unit:"))
        base_row.addWidget(self.edt_base_price)
        base_row.addWidget(lbl_base_uom)
        base_row.addStretch(1)
        # Show the last cost just above the base price row
        root.addWidget(lbl_cost)
        root.addLayout(base_row)

        # Retail (alt) price row
        alt_box = QHBoxLayout()
        self.cmb_alt = QComboBox()
        self.cmb_alt.addItem("Select retail UoM…", None)
        for u in self._alt_uoms:
            try:
                name = str(u.get("unit_name", "")).strip()
                uom_id_raw = u.get("uom_id")
                factor_raw = u.get("factor_to_base")
                if not name:
                    continue
                uom_id = int(uom_id_raw)
                factor = float(factor_raw)
                # Skip invalid/zero/negative factors
                if not (factor > 0.0 and factor < float("inf")):
                    continue
            except Exception:
                # Skip malformed entries
                continue
            self.cmb_alt.addItem(name, (uom_id, factor))
        self.edt_alt_price = QLineEdit()
        self.edt_alt_price.setPlaceholderText("0.00")
        self.lbl_alt_cost = QLabel("")  # updated when UoM changes
        alt_box.addWidget(QLabel("Retail UoM:"))
        alt_box.addWidget(self.cmb_alt)
        alt_box.addWidget(QLabel("Sale price per retail unit:"))
        alt_box.addWidget(self.edt_alt_price)
        alt_box.addWidget(self.lbl_alt_cost)
        alt_box.addStretch(1)
        root.addLayout(alt_box)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Wire sync between base and retail when both are available
        self.cmb_alt.currentIndexChanged.connect(self._on_alt_uom_changed)
        self.edt_base_price.textChanged.connect(self._on_base_price_changed)
        self.edt_alt_price.textChanged.connect(self._on_alt_price_changed)

        # Initialize alt cost/price from current base if possible
        self._on_alt_uom_changed()

    # ---- internal helpers ----
    def _current_factor(self) -> float | None:
        data = self.cmb_alt.currentData()
        if data is None:
            return None
        _, f = data
        return float(f)

    def _on_alt_uom_changed(self):
        f = self._current_factor()
        # Update cost label in retail UoM
        if f is not None and self._cost_base > 0:
            cost_alt = self._cost_base * f
            self.lbl_alt_cost.setText(f"Cost per retail unit: {cost_alt:.2f}")
        else:
            self.lbl_alt_cost.setText("")
        # Toggle base price editability: when a retail UoM is selected,
        # base becomes a derived value only.
        self.edt_base_price.setReadOnly(f is not None)

        # If we have a base sale price, keep retail in sync
        txt = (self.edt_base_price.text() or "").strip()
        ok, base_price = try_parse_float(txt) if txt else (False, None)
        if f is not None and ok and base_price is not None:
            with self._sync():
                self.edt_alt_price.setText(f"{base_price * f:.2f}")

    def _on_base_price_changed(self, _=None):
        if self._syncing:
            return
        f = self._current_factor()
        if f is None:
            return
        txt = (self.edt_base_price.text() or "").strip()
        ok, base_price = try_parse_float(txt) if txt else (False, None)
        if not (ok and base_price is not None):
            return
        with self._sync():
            self.edt_alt_price.setText(f"{base_price * f:.2f}")

    def _on_alt_price_changed(self, _=None):
        if self._syncing:
            return
        f = self._current_factor()
        # Guard against non-positive/near-zero factors to avoid invalid division
        if f is None or f < 1e-9:
            return
        txt = (self.edt_alt_price.text() or "").strip()
        ok, alt_price = try_parse_float(txt) if txt else (False, None)
        if not (ok and alt_price is not None):
            return
        # base = retail / factor_to_base
        base_price = alt_price / f
        with self._sync():
            self.edt_base_price.setText(f"{base_price:.2f}")

    # Simple context manager to guard against recursive updates
    @contextmanager
    def _sync(self):
        self._syncing = True
        try:
            yield
        finally:
            self._syncing = False

    # ---- public API ----
    def result_base_price(self) -> float | None:
        """
        Return the base-unit sale price chosen in the dialog, or None
        if nothing valid was entered.

        Rule:
          - If a retail UoM is selected *and* its price is valid, that price
            is taken as the source of truth and converted back to base.
          - Otherwise, the base price field is used directly.
        """
        # 1) Prefer retail (alt) price when a UoM is selected.
        f = self._current_factor()
        rtxt = (self.edt_alt_price.text() or "").strip()
        ok_alt, alt_price = try_parse_float(rtxt) if rtxt else (False, None)
        if f is not None and f >= 1e-9 and ok_alt and alt_price is not None and alt_price >= 0:
            return float(alt_price) / f

        # 2) Fallback: use base price directly.
        txt = (self.edt_base_price.text() or "").strip()
        ok, base_price = try_parse_float(txt) if txt else (False, None)
        if not (ok and base_price is not None and base_price >= 0):
            return None
        return float(base_price)


class ProductController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
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
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.btn_set_price.clicked.connect(self._set_price)
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

    def _set_price(self):
        """
        Set manual sale price per BASE (bulk) unit and show corresponding
        price for a retail (alternate) unit. Only the base price is stored;
        retail prices are derived from it via the UoM factor.

        Warn (but allow) when the new sale price is below the last purchase cost.
        """
        pid = self._selected_id()
        if not pid:
            info(self.view, "Select", "Please select a product to set price.")
            return

        # Fetch latest cost/sale prices in base units
        try:
            prices = self.repo.latest_prices_base(pid)
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Failed to load latest prices for product %s: %s", pid, exc, exc_info=True
            )
            prices = {"cost": 0.0, "sale": 0.0}

        cost_base = float(prices.get("cost") or 0.0)
        current_sale = float(prices.get("sale") or 0.0)

        # UoM info for this product
        uoms = self.repo.list_product_uoms(pid)
        base = next((u for u in uoms if u.get("is_base")), None)
        alts = [u for u in uoms if not u.get("is_base")]
        base_name = base.get("unit_name", "Base") if base else "Base"

        dlg = PriceDialog(
            self.view,
            product_id=pid,
            base_uom_name=base_name,
            cost_base=cost_base,
            sale_base=current_sale,
            alt_uoms=alts,
        )
        if not dlg.exec():
            return

        price = dlg.result_base_price()
        if price is None:
            error(self.view, "Invalid value", "Enter a valid non-negative sale price.")
            return

        # Warn, but allow, if sale price goes below purchase cost
        if cost_base > 0 and price < cost_base:
            resp = QMessageBox.warning(
                self.view,
                "Price below cost",
                (
                    f"The sale price ({price:.2f}) is below the last purchase "
                    f"cost ({cost_base:.2f}).\n\nDo you want to continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        try:
            self.repo.set_manual_sale_price_base(pid, float(price))
        except Exception as exc:  # pragma: no cover - defensive
            error(self.view, "Error", f"Failed to set sale price: {exc}")
            return

        info(self.view, "Saved", f"Sale price for product #{pid} updated to {price:.2f}.")
        # Refresh product list so any price-dependent columns stay in sync
        self._reload()
