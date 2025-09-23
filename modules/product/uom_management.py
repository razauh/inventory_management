from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox
)
from PySide6.QtCore import Qt
from ...database.repositories.products_repo import ProductsRepo
from ...utils.ui_helpers import info, error

# Prefer strict validator (> 0). Fallback to legacy if the project hasn't been updated yet.
try:  # new API
    from ...utils.validators import is_strictly_positive_number as _is_pos
except Exception:  # legacy API
    try:
        from ...utils.validators import is_positive_number as _is_pos  # type: ignore
    except Exception:  # very defensive fallback
        def _is_pos(x) -> bool:
            try:
                return float(x) > 0
            except Exception:
                return False


class UomManagerDialog(QDialog):
    def __init__(self, repo: ProductsRepo, product_id: int, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"UoM Management — {product_name}")
        self.repo = repo
        self.product_id = product_id

        root = QVBoxLayout(self)

        # Current mappings table
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["UoM", "Base?", "Factor→Base", "Map ID"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.setEditTriggers(self.tbl.NoEditTriggers)
        self.tbl.setSelectionBehavior(self.tbl.SelectRows)
        self.tbl.setSelectionMode(self.tbl.SingleSelection)
        self.tbl.setColumnHidden(3, True)
        root.addWidget(QLabel("Current UoMs for this product"))
        root.addWidget(self.tbl, 1)

        # Actions
        btns = QHBoxLayout()
        self.btn_set_base = QPushButton("Set Selected as Base")
        self.btn_remove = QPushButton("Remove Selected (Alt)")
        btns.addWidget(self.btn_set_base)
        btns.addWidget(self.btn_remove)
        btns.addStretch(1)
        root.addLayout(btns)

        # Add new mapping
        root.addWidget(QLabel("Add Alternate UoM"))
        form = QFormLayout()
        self.cmb_all_uoms = QComboBox()
        self.txt_factor = QLineEdit()
        self.txt_factor.setPlaceholderText("Factor to Base (must be > 0, e.g., 0.5 or 12)")
        form.addRow("UoM", self.cmb_all_uoms)
        form.addRow("Factor to Base", self.txt_factor)
        root.addLayout(form)

        add_row = QHBoxLayout()
        self.btn_add_alt = QPushButton("Add / Update Alternate")
        add_row.addWidget(self.btn_add_alt)
        add_row.addStretch(1)
        root.addLayout(add_row)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        root.addWidget(self.buttons)

        # Wiring
        self.btn_set_base.clicked.connect(self._set_base)
        self.btn_remove.clicked.connect(self._remove_alt)
        self.btn_add_alt.clicked.connect(self._add_alt)

        self._reload()

    def _reload(self):
        # fill current mappings
        rows = self.repo.product_uoms(self.product_id)
        self.tbl.setRowCount(len(rows))
        for r, d in enumerate(rows):
            self.tbl.setItem(r, 0, QTableWidgetItem(d["unit_name"]))
            self.tbl.setItem(r, 1, QTableWidgetItem("Yes" if d["is_base"] else "No"))
            self.tbl.setItem(r, 2, QTableWidgetItem(f'{d["factor_to_base"]:.6g}'))
            self.tbl.setItem(r, 3, QTableWidgetItem(str(d["product_uom_id"])))

        # fill all uoms combo
        self.cmb_all_uoms.clear
        self.cmb_all_uoms.clear()
        for u in self.repo.list_uoms():
            self.cmb_all_uoms.addItem(u["unit_name"], u["uom_id"])

    def _selected_map_id_and_uom(self):
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return None, None
        row = idxs[0].row()
        map_id = int(self.tbl.item(row, 3).text())
        uom_name = self.tbl.item(row, 0).text()
        return map_id, uom_name

    def _set_base(self):
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            info(self, "Select", "Select a UoM row to set as base.")
            return
        row = idxs[0].row()
        uom_name = self.tbl.item(row, 0).text()
        # find uom_id by name
        uom_id = None
        for i in range(self.cmb_all_uoms.count()):
            if self.cmb_all_uoms.itemText(i) == uom_name:
                uom_id = self.cmb_all_uoms.itemData(i)
                break
        if uom_id is None:
            error(self, "Error", "Could not find UoM ID.")
            return
        self.repo.set_base_uom(self.product_id, int(uom_id))
        info(self, "Saved", f"Base UoM set to {uom_name}.")
        self._reload()

    def _remove_alt(self):
        map_id, uom_name = self._selected_map_id_and_uom()
        if map_id is None:
            info(self, "Select", "Select a non-base UoM row to remove.")
            return
        # only allow remove if not base
        if self.tbl.item(self.tbl.currentRow(), 1).text().lower().startswith("yes"):
            info(self, "Blocked", "Cannot remove base UoM. Set another base first.")
            return
        self.repo.remove_alt_uom(map_id)
        info(self, "Removed", f"Removed alternate UoM {uom_name}.")
        self._reload()

    def _add_alt(self):
        uom_id = self.cmb_all_uoms.currentData()
        factor_txt = self.txt_factor.text().strip()

        # Strict validation: must be a valid number and strictly > 0
        if not _is_pos(factor_txt):
            error(self, "Invalid", "Factor must be a number greater than 0.")
            return

        try:
            f = float(factor_txt)
        except Exception:
            error(self, "Invalid", "Factor must be a number greater than 0.")
            return
        if not (f > 0):
            error(self, "Invalid", "Factor must be greater than 0.")
            return

        # Prevent adding an alternate mapping for the current base UoM
        current = self.repo.product_uoms(self.product_id)
        for row in current:
            if int(row["uom_id"]) == int(uom_id):
                if row["is_base"]:
                    info(
                        self,
                        "Blocked",
                        "Selected UoM is the current base. Its factor is fixed at 1.0.\n"
                        "Choose a different UoM or change the base first.",
                    )
                    return
                # If mapping already exists with same factor, no-op to avoid churn
                try:
                    existing = float(row.get("factor_to_base") or 0.0)
                except Exception:
                    existing = None
                if existing is not None and abs(existing - f) < 1e-12:
                    info(self, "No changes", "This alternate mapping already has the same factor.")
                    return
                break  # same UoM exists as alternate; will be updated below

        # This will create/update alternate (DB enforces >0; base is always factor=1)
        self.repo.add_alt_uom(self.product_id, int(uom_id), f)
        info(self, "Saved", "Alternate UoM saved.")
        self._reload()
