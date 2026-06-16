from contextlib import contextmanager
import logging
from pathlib import Path
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QItemSelectionModel
from PySide6.QtWidgets import (
    QWidget,
    QLineEdit,
    QMessageBox,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QDialogButtonBox,
    QHeaderView,
)
import sqlite3
from ..base_module import BaseModule
from .view import ProductView
from .form import ProductForm
from .model import ProductsTableModel
from .components import ProductSummary
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
        product_label: str | None,
        base_uom_name: str | None,
        cost_base: float,
        sale_base: float,
        alt_uoms: list[dict],
    ):
        super().__init__(parent)
        label = (product_label or "").strip()
        if label:
            self.setWindowTitle(f"Set price for {label} (#{product_id})")
        else:
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
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #a33;")
        self.lbl_error.setWordWrap(True)
        alt_box.addWidget(QLabel("Retail UoM:"))
        alt_box.addWidget(self.cmb_alt)
        alt_box.addWidget(QLabel("Sale price per retail unit:"))
        alt_box.addWidget(self.edt_alt_price)
        alt_box.addWidget(self.lbl_alt_cost)
        alt_box.addStretch(1)
        root.addLayout(alt_box)
        root.addWidget(self.lbl_error)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Wire sync between base and retail when both are available
        self.cmb_alt.currentIndexChanged.connect(self._on_alt_uom_changed)
        self.edt_base_price.textChanged.connect(self._on_base_price_changed)
        self.edt_alt_price.textChanged.connect(self._on_alt_price_changed)
        self.edt_base_price.textChanged.connect(lambda: self.lbl_error.clear())
        self.edt_alt_price.textChanged.connect(lambda: self.lbl_error.clear())

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

    def accept(self):
        price = self.result_base_price()
        if price is None:
            self.lbl_error.setText("Enter a valid non-negative sale price.")
            return
        self.lbl_error.clear()
        super().accept()


class ProductController(BaseModule):
    _AUTO_SIZE_ROW_LIMIT = 100
    _LARGE_TABLE_WIDTHS = {
        0: 90,
        1: 220,
        2: 160,
        3: 110,
        4: 300,
        5: 120,
        6: 180,
    }

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
        self.view.btn_import.clicked.connect(self._import_products)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.btn_delete.clicked.connect(self._delete)
        self.view.btn_price.clicked.connect(self._set_price)
        self.view.search.textChanged.connect(self._apply_filter)
        self._wired = True

    def _build_model(self, selected_pid: int | None = None):
        rows = self.repo.list_products()
        self.base_model = ProductsTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base_model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setSortRole(Qt.UserRole)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        self._resize_table_columns(len(rows))
        try:
            self.view.table.selectionModel().selectionChanged.connect(self._update_selected_details)
        except Exception:
            pass
        self._apply_filter(self.view.search.text())
        self._restore_selection(selected_pid)
        self._update_summary(rows)
        self._update_selected_details()

    def _reload(self):
        self._build_model(self._selected_id())

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(QRegularExpression.escape(text)))
        self._update_selected_details()

    def _resolve_uom_ref(self, ref: dict) -> int:
        uom_id = ref.get("uom_id")
        if uom_id is not None:
            return int(uom_id)
        name = str(ref.get("unit_name") or ref.get("uom_name") or "").strip()
        if not name:
            raise ValueError("UoM name is required.")
        return int(self.repo.add_uom(name))

    def _set_action_state(self, enabled: bool):
        self.view.btn_edit.setEnabled(enabled)
        self.view.btn_delete.setEnabled(enabled)
        self.view.btn_price.setEnabled(enabled)

    def _restore_selection(self, product_id: int | None):
        if product_id is None:
            self.view.table.clearSelection()
            self._set_action_state(False)
            return
        selection_model = self.view.table.selectionModel()
        if selection_model is None:
            return
        for row in range(self.proxy.rowCount()):
            idx = self.proxy.index(row, 0)
            if str(self.proxy.data(idx, Qt.DisplayRole)) == str(product_id):
                selection_model.select(
                    idx,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
                )
                self.view.table.scrollTo(idx)
                self._set_action_state(True)
                return
        self.view.table.clearSelection()
        self._set_action_state(False)

    def _update_summary(self, rows):
        low_stock = 0
        priced = 0
        with_uoms = 0
        for p in rows:
            min_stock = float(getattr(p, "min_stock_level", 0.0) or 0.0)
            on_hand = float(getattr(p, "on_hand_base", 0.0) or 0.0)
            if min_stock > 0 and on_hand < min_stock:
                low_stock += 1
            sale_price = float(getattr(p, "sale_price_base", 0.0) or 0.0)
            if sale_price > 0:
                priced += 1
            if getattr(p, "base_uom_name", None):
                with_uoms += 1
        self.view.summary.set_summary(
            ProductSummary(
                total=len(rows),
                low_stock=low_stock,
                priced=priced,
                with_uoms=with_uoms,
            )
        )

    def _update_selected_details(self, *_):
        product = self._selected_product()
        if not product or product.product_id is None:
            self._set_action_state(False)
            if self.view.search.text().strip() and self.proxy.rowCount() == 0:
                self.view.details.set_empty(
                    "No products found",
                    "Clear the search to see products again.",
                )
            else:
                self.view.details.clear()
            return
        pid = int(product.product_id)
        self._set_action_state(True)
        try:
            self.view.selection_changed.emit(int(pid))
        except Exception:
            pass
        self.view.details.set_product(
            product_id=pid,
            name=product.name,
            category=product.category,
            min_stock_level=product.min_stock_level,
            base_uom_name=product.base_uom_name,
            alt_uom_names=product.alt_uom_names,
            sale_price=float(product.sale_price_base or 0.0),
            cost_price=float(product.cost_price_base or 0.0),
            description=product.description,
        )

    def _selected_product(self):
        selection_model = self.view.table.selectionModel()
        if selection_model is None:
            return None
        idxs = selection_model.selectedRows()
        if not idxs:
            return None
        src_index = self.proxy.mapToSource(idxs[0])
        if not src_index.isValid():
            return None
        return self.base_model.at(src_index.row())

    def _resize_table_columns(self, row_count: int) -> None:
        header = self.view.table.horizontalHeader()
        if row_count <= self._AUTO_SIZE_ROW_LIMIT:
            self.view.table.resizeColumnsToContents()
            return
        for column, width in self._LARGE_TABLE_WIDTHS.items():
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.view.table.setColumnWidth(column, width)
        header.setStretchLastSection(True)

    def _selected_id(self) -> int | None:
        product = self._selected_product()
        return None if product is None else product.product_id

    def _with_product_savepoint(self, fn):
        self.conn.execute("SAVEPOINT product_mutation")
        try:
            result = fn()
        except Exception:
            try:
                self.conn.execute("ROLLBACK TO product_mutation")
            finally:
                self.conn.execute("RELEASE product_mutation")
            raise
        self.conn.execute("RELEASE product_mutation")
        return result

    def _add(self):
        dlg = ProductForm(self.view, repo=self.repo)
        if not dlg.exec():
            return
        pdata = dlg.payload()
        if not pdata:
            return
        try:
            def save_product():
                pid = self.repo.create(**pdata["product"])
                base_id = self._resolve_uom_ref(pdata["uoms"]["base_uom"])
                self.repo.set_base_uom(pid, base_id)
                roles = {base_id: (True, True)}
                all_alts = {}
                if pdata["uoms"]["enabled_sales"]:
                    for a in pdata["uoms"]["sales_alts"]:
                        alt_id = self._resolve_uom_ref(a)
                        if alt_id == base_id:
                            raise ValueError("Base UoM cannot also be a sales alternate.")
                        all_alts[alt_id] = a
                        prev = roles.get(alt_id, (False, False))
                        roles[alt_id] = (True, prev[1])
                for alt_id, a in all_alts.items():
                    self.repo.add_alt_uom(pid, alt_id, a["factor_to_base"])
                if len(roles) > 1:
                    self.repo.upsert_roles(pid, roles)
                return pid

            pid = self._with_product_savepoint(save_product)
        except (DomainError, sqlite3.IntegrityError, ValueError) as e:
            error(self.view, "Not saved", str(e))
            return
        info(self.view, "Saved", f"Product #{pid} created.")
        self._reload()

    def _import_products(self):
        path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Import Products",
            "",
            "Excel Workbooks (*.xlsx)",
        )
        if not path:
            return
        xlsx_path = Path(path)
        try:
            try:
                from inventory_management.scripts.bulk_import_products import (
                    ImportValidationError,
                    import_products_from_xlsx,
                )
            except ModuleNotFoundError:
                from scripts.bulk_import_products import (  # type: ignore
                    ImportValidationError,
                    import_products_from_xlsx,
                )

            result = import_products_from_xlsx(self.conn, xlsx_path)
        except ImportError as exc:
            error(self.view, "Import failed", f"Import helper could not load.\n\n{exc}")
            return
        except ImportValidationError as exc:
            failed_count = getattr(exc, "failed_count", 0)
            error(
                self.view,
                "Import failed",
                f"Imported products: 0\nSkipped/failed rows: {failed_count}\n\n{exc}",
            )
            return
        except (sqlite3.Error, OSError, ValueError) as exc:
            error(
                self.view,
                "Import failed",
                f"Imported products: 0\nSkipped/failed rows: unknown\n\n{exc}",
            )
            return

        info(
            self.view,
            "Import complete",
            (
                f"Imported products: {result.imported_count}\n"
                f"Skipped/failed rows: {result.failed_count}"
            ),
        )
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
        try:
            def save_product():
                self.repo.update(pid, **pdata["product"])
                base_id = self._resolve_uom_ref(pdata["uoms"]["base_uom"])
                self.repo.set_base_uom(pid, base_id)
                roles_map = {base_id: (True, True)}
                all_alts = {}
                if pdata["uoms"]["enabled_sales"]:
                    for a in pdata["uoms"]["sales_alts"]:
                        alt_id = self._resolve_uom_ref(a)
                        if alt_id == base_id:
                            raise ValueError("Base UoM cannot also be a sales alternate.")
                        all_alts[alt_id] = a
                        prev = roles_map.get(alt_id, (False, False))
                        roles_map[alt_id] = (True, prev[1])
                for alt_id, a in all_alts.items():
                    self.repo.add_alt_uom(pid, alt_id, a["factor_to_base"])
                if len(roles_map) > 1:
                    self.repo.upsert_roles(pid, roles_map)

            self._with_product_savepoint(save_product)
        except (DomainError, sqlite3.IntegrityError, ValueError) as e:
            error(self.view, "Not saved", str(e))
            return
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
        current = self.repo.get(pid)
        label = current.name if current else f"product #{pid}"
        reply = QMessageBox.question(
            self.view,
            "Delete Product",
            f"Delete {label} (#{pid})?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
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
        current_product = self.repo.get(pid)

        dlg = PriceDialog(
            self.view,
            product_id=pid,
            product_label=current_product.name if current_product else None,
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
