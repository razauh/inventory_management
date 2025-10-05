from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QGroupBox, QCheckBox, QComboBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)
from PySide6.QtCore import Qt
from ...utils.validators import non_empty, is_positive_number, try_parse_float
from ...utils.ui_helpers import info  # optional: to show a friendly message

class UomPicker(QComboBox):
    """
    Editable combo with DB suggestions + inline create.
    Works even when you click 'Add Alternate' (no need to press Enter).
    """
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.repo = repo
        self._names = set()
        self._reload()
        # Set uniform width for all UoM pickers
        self.setMaximumWidth(200)
        
    def _reload(self, keep_text: str | None = None):
        txt = keep_text if keep_text is not None else self.currentText()
        self.blockSignals(True)
        self.clear()
        self._names.clear()
        for u in self.repo.list_uoms():
            self.addItem(u["unit_name"], u["uom_id"])
            self._names.add(u["unit_name"].lower())
        if txt:
            self.setEditText(txt)
        self.blockSignals(False)
        
    def _ensure_current_exists(self):
        """
        If the typed text doesn't match the selected item, create/select it.
        """
        typed = (self.currentText() or "").strip()
        if not typed:
            return
        if typed.lower() in self._names:
            # make sure the combo selection matches the typed text
            i = self.findText(typed, Qt.MatchFixedString)
            if i >= 0:
                self.setCurrentIndex(i)
            return
        # create new and select it
        new_id = self.repo.add_uom(typed)
        self._reload(keep_text=typed)
        i = self.findText(typed, Qt.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)
            
    def current_uom_id(self) -> int | None:
        # Make sure the typed entry is materialized
        self._ensure_current_exists()
        data = self.currentData()
        return int(data) if data is not None else None

class ProductForm(QDialog):
    def __init__(self, parent=None, repo=None, initial_product=None, initial_uoms=None, initial_roles=None):
        super().__init__(parent)
        self.setWindowTitle("Product")
        self.setModal(True)
        self.repo = repo
        self.initial_product = initial_product
        self.initial_uoms = initial_uoms or []
        self.initial_roles = initial_roles or {}  # {uom_id: {"for_sales":0/1,"for_purchases":0/1}}
        self._payload = None
        root = QVBoxLayout(self)
        
        # --- Basic fields ---
        self.name = QLineEdit()
        self.category = QLineEdit()
        self.min_stock = QLineEdit()
        self.min_stock.setPlaceholderText("0")
        self.desc = QLineEdit()
        
        # Set uniform width for all text fields
        field_width = 200
        self.name.setMaximumWidth(field_width)
        self.category.setMaximumWidth(field_width)
        self.min_stock.setMaximumWidth(field_width)
        self.desc.setMaximumWidth(field_width)
        
        # Create error labels
        self.name_error = QLabel()
        self.name_error.setStyleSheet("color: red;")
        self.name_error.setMaximumWidth(150)  # Set width for error label
        self.min_stock_error = QLabel()
        self.min_stock_error.setStyleSheet("color: red;")
        self.min_stock_error.setMaximumWidth(150)  # Set width for error label
        
        form = QFormLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(self.name, 1)
        name_row.addWidget(self.name_error)
        form.addRow("Name*", name_row)
        
        form.addRow("Category", self.category)
        
        min_stock_row = QHBoxLayout()
        min_stock_row.addWidget(self.min_stock, 1)
        min_stock_row.addWidget(self.min_stock_error)
        form.addRow("Min Stock*", min_stock_row)
        
        form.addRow("Description", self.desc)
        root.addLayout(form)
        
        # --- UoM section (Base + Sales only) ---
        ubox = QGroupBox("Units of Measure")
        self.uom_layout = QVBoxLayout(ubox)  # Store as instance variable
        self.chk_sales = QCheckBox("Enable different UoMs for Sales")
        flagrow = QHBoxLayout()
        flagrow.addWidget(self.chk_sales)
        flagrow.addStretch(1)
        self.uom_layout.addLayout(flagrow)
        
        # Base UoM
        self.base_uom_row = QHBoxLayout()
        self.base_uom_row.addWidget(QLabel("Base UoM:"))
        self.cmb_base = UomPicker(self.repo)
        self.base_uom_row.addWidget(self.cmb_base, 1)
        self.uom_layout.addLayout(self.base_uom_row)
        
        # Create error label for base UoM and add it to the layout
        self.base_uom_error = QLabel()
        self.base_uom_error.setStyleSheet("color: red;")
        self.base_uom_error.setMaximumWidth(150)  # Set width for error label
        self.base_uom_error.hide()  # Initially hidden
        self.uom_layout.addWidget(self.base_uom_error)
        
        # --- Sales UoMs ---
        sales = QGroupBox("Sales Alternates")
        sl = QVBoxLayout(sales)
        srow = QHBoxLayout()
        self.cmb_sales_alt = UomPicker(self.repo)
        self.txt_sales_factor = QLineEdit()
        self.txt_sales_factor.setPlaceholderText("Factor → base (e.g., 12 or 0.5)")
        self.txt_sales_factor.setMaximumWidth(100)  # Smaller width for factor field
        self.btn_sales_add = QPushButton("Add Sales Alternate")
        srow.addWidget(QLabel("Alternate"))
        srow.addWidget(self.cmb_sales_alt, 1)
        srow.addWidget(QLabel("Factor"))
        srow.addWidget(self.txt_sales_factor)
        srow.addWidget(self.btn_sales_add)
        sl.addLayout(srow)
        self.tbl_sales = QTableWidget(0, 2)
        self.tbl_sales.setHorizontalHeaderLabels(["UoM", "Factor→Base"])
        self.tbl_sales.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_sales.setEditTriggers(QTableWidget.NoEditTriggers)
        # ensure row selection UX is correct
        self.tbl_sales.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_sales.setSelectionMode(QAbstractItemView.SingleSelection)
        sl.addWidget(self.tbl_sales)
        
        self.uom_layout.addWidget(sales)
        
        # shared actions for base/alt swapping
        actrow = QHBoxLayout()
        self.btn_set_base = QPushButton("Set Selected as Base")
        self.btn_remove = QPushButton("Remove Selected Alternate")
        actrow.addWidget(self.btn_set_base)
        actrow.addWidget(self.btn_remove)
        actrow.addStretch(1)
        self.uom_layout.addLayout(actrow)
        root.addWidget(ubox, 1)
        
        # Dialog buttons (validate before closing)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        self.buttons.accepted.connect(self.accept)   # overridden accept()
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        
        # State
        self._base_id: int | None = None
        self._sales_alts: list[dict] = []     # {"uom_id": int, "factor_to_base": float}
        
        # Wire
        self.chk_sales.toggled.connect(self._toggle_blocks)
        self.btn_sales_add.clicked.connect(self._add_sales_alt)
        self.btn_remove.clicked.connect(self._remove_selected_alt)
        self.btn_set_base.clicked.connect(self._set_selected_as_base)
        
        # Connect textChanged signals to clear error messages
        self.name.textChanged.connect(lambda: self.name_error.clear())
        self.min_stock.textChanged.connect(lambda: self.min_stock_error.clear())
        self.cmb_base.currentTextChanged.connect(lambda: self.base_uom_error.clear())
        
        # Load initial values
        if initial_product:
            self.name.setText(initial_product.name)
            self.category.setText(initial_product.category or "")
            self.min_stock.setText(str(initial_product.min_stock_level))
            self.desc.setText(initial_product.description or "")
            
        if self.initial_uoms:
            # determine base from DB
            base_row = next((m for m in self.initial_uoms if m["is_base"]), None)
            if base_row:
                i = self.cmb_base.findText(base_row["unit_name"], Qt.MatchFixedString)
                if i >= 0: self.cmb_base.setCurrentIndex(i)
                self._base_id = base_row["uom_id"]
            # split alts by roles (default to sales if no roles saved)
            for m in self.initial_uoms:
                if m["is_base"]: continue
                u = m["uom_id"]; f = float(m["factor_to_base"])
                role = self.initial_roles.get(u, {"for_sales": 1})
                if role.get("for_sales"):  self._append_unique(self._sales_alts, u, f)
            self.chk_sales.setChecked(len(self._sales_alts) > 0)
            
        self._refresh_tables()
        self._toggle_blocks()
        
    # ---------- helpers ----------
    def _toggle_blocks(self):
        on_s = self.chk_sales.isChecked()
        # Base is ALWAYS available (decoupled from toggles)
        self.cmb_base.setEnabled(True)
        self.btn_set_base.setEnabled(True)  # action itself requires a row selection
        # Alternates still depend on toggles
        for w in (self.cmb_sales_alt, self.txt_sales_factor, self.btn_sales_add, self.tbl_sales):
            w.setEnabled(on_s)
            
    def _uom_name(self, uom_id: int) -> str:
        for u in self.repo.list_uoms():
            if u["uom_id"] == uom_id:
                return u["unit_name"]
        return f"UoM#{uom_id}"
        
    def _append_unique(self, lst: list[dict], uom_id: int, factor: float):
        for a in lst:
            if a["uom_id"] == uom_id:
                a["factor_to_base"] = factor
                return
        lst.append({"uom_id": uom_id, "factor_to_base": factor})
        
    def _refresh_tables(self):
        # sales table
        self.tbl_sales.setRowCount(len(self._sales_alts))
        for r, a in enumerate(self._sales_alts):
            self.tbl_sales.setItem(r, 0, QTableWidgetItem(self._uom_name(a["uom_id"])))
            self.tbl_sales.setItem(r, 1, QTableWidgetItem(f'{float(a["factor_to_base"]):g}'))
            
    def _selected_table_and_row(self):
        """Return ('sales', row) based on which table actually has a selection."""
        sels = self.tbl_sales.selectionModel().selectedRows()
        if sels:
            return 'sales', sels[0].row()
        return None, None
            
    # ---------- add/remove/set-base ----------
    def _ensure_base_selected(self):
        if self._base_id is None:
            self._base_id = self.cmb_base.current_uom_id()
        return self._base_id is not None
        
    def _add_sales_alt(self):
        if not self.chk_sales.isChecked(): return
        u = self.cmb_sales_alt.current_uom_id()
        if u is None: return
        t = self.txt_sales_factor.text().strip()
        if not is_positive_number(t): return
        f = float(t)
        if not self._ensure_base_selected(): return
        if u == self._base_id:  # base already 1.0, nothing to add
            self._refresh_tables(); return
        self._append_unique(self._sales_alts, u, f)
        self._refresh_tables()
        
    def _remove_selected_alt(self):
        which, row = self._selected_table_and_row()
        if which is None:
            # optional message; you can omit if you prefer silent no-op
            info(self, "Select", "Please select a Sales alternate to remove.")
            return
        tbl = self.tbl_sales if which == 'sales' else None
        if tbl is None: return
        name = tbl.item(row, 0).text()
        lst = self._sales_alts if which == 'sales' else None
        if lst is None: return
        for i, a in enumerate(lst):
            if self._uom_name(a["uom_id"]) == name:
                del lst[i]
                break
        self._refresh_tables()
        
    def _set_selected_as_base(self):
        which, row = self._selected_table_and_row()
        if which is None:
            info(self, "Select", "Please select a Sales alternate to set as Base.")
            return
        tbl = self.tbl_sales if which == 'sales' else None
        if tbl is None: return
        name = tbl.item(row, 0).text()
        # find the target uom_id from the sales list
        target = None
        for a in self._sales_alts:
            if self._uom_name(a["uom_id"]) == name:
                target = a["uom_id"]
                break
        if target is None:
            return
        old_base = self._base_id
        self._base_id = target
        # ensure old base appears as 1.0 alt in the sales list
        if old_base is not None:
            self._append_unique(self._sales_alts, old_base, 1.0)
        # remove new base from the sales alt list
        self._sales_alts = [a for a in self._sales_alts if a["uom_id"] != self._base_id]
        # reflect in base combo
        i = self.cmb_base.findText(name, Qt.MatchFixedString)
        if i >= 0:
            self.cmb_base.setCurrentIndex(i)
        self._refresh_tables()
        
    # ---------- payload & validation ----------
    def get_product_payload(self) -> dict | None:
        # Clear previous error messages
        self.name_error.clear()
        self.min_stock_error.clear()
        self.base_uom_error.clear()
        
        # Validate name
        if not non_empty(self.name.text()):
            self.name_error.setText("Name is required")
            self.name.setFocus()
            return None
            
        # Validate min stock - allow empty values (treat as 0) or non-negative numbers
        min_stock_text = self.min_stock.text().strip()
        if min_stock_text == "":
            # Empty value is acceptable, will default to 0
            min_stock_value = 0.0
        else:
            # Validate that the entered value is a non-negative number
            ok, parsed_value = try_parse_float(min_stock_text)
            if not (ok and parsed_value is not None and parsed_value >= 0):
                self.min_stock_error.setText("Enter a valid non-negative number")
                self.min_stock.setFocus()
                return None
            min_stock_value = parsed_value
            
        sales_on = self.chk_sales.isChecked()
        # BASE: always required/available
        base_id = self._base_id or self.cmb_base.current_uom_id()
        if base_id is None:
            self.base_uom_error.setText("Base UoM is required")
            self.base_uom_error.show()
            self.cmb_base.setFocus()
            return None
        
        # Alternates only if their toggle is on
        sales = list(self._sales_alts) if sales_on else []
        return {
            "product": {
                "name": self.name.text().strip(),
                "description": self.desc.text().strip() or None,
                "category": self.category.text().strip() or None,
                "min_stock_level": min_stock_value,
            },
            "uoms": {
                # 'enabled' indicates whether alternates are used (base is always present)
                "enabled": sales_on,
                "enabled_sales": sales_on,
                "base_uom_id": base_id,     # always present now
                "sales_alts": sales,
            }
        }
        
    def accept(self):
        payload = self.get_product_payload()
        if payload is None:
            # keep dialog open; controller won't lose user input
            return
        self._payload = payload
        super().accept()
        
    def payload(self):
        return self._payload