from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QSplitter, QWidget as W, QVBoxLayout as V, QGroupBox, QButtonGroup
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from ...widgets.table_view import TableView
from .details import SaleDetails
from .items import SaleItemsView
from ...utils.helpers import fmt_money


class PaymentsTableModel(QAbstractTableModel):
    """
    Read-only, compact payments table:
    Columns: Date, Method, Amount ±, State, Ref #, Bank
    Accepts rows as sqlite3.Row or dict with keys similar to sale_payments schema.
    """
    HEADERS = ["Date", "Method", "Amount", "State", "Ref #", "Bank"]

    def __init__(self, rows: list[dict] | None = None):
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None

        r = self._rows[index.row()]

        # tolerant getters for sqlite3.Row or dict
        def g(key, default=None):
            try:
                if isinstance(r, dict):
                    return r.get(key, default)
                return r[key] if key in r.keys() else default
            except Exception:
                return default

        date = g("date", "")
        method = g("method", "")
        amount = g("amount", 0.0)
        state = g("clearing_state", g("state", ""))
        ref_no = g("ref_no", None) or g("instrument_no", "")

        bank_display = ""
        bank_name = g("bank_name", None)
        account_no = g("account_no", None)
        if bank_name or account_no:
            if bank_name and account_no:
                bank_display = f"{bank_name} ({account_no})"
            else:
                bank_display = bank_name or account_no or ""
        else:
            bank_id = g("bank_account_id", None)
            if bank_id is not None:
                bank_display = f"#{bank_id}"

        cols = [
            str(date or ""),
            str(method or ""),
            fmt_money(float(amount or 0.0)),
            str(state or ""),
            str(ref_no or ""),
            bank_display,
        ]
        return cols[index.column()]

    def replace(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()


class PaymentsView(QWidget):
    """
    Small wrapper: a titled group box with a TableView and read-only model.
    Use .set_rows(rows) to populate.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        box = QGroupBox("Payments")
        v = QVBoxLayout(box)
        self.table = TableView()
        self.model = PaymentsTableModel([])
        self.table.setModel(self.model)
        v.addWidget(self.table, 1)

        root = QVBoxLayout(self)
        root.addWidget(box, 1)

    def set_rows(self, rows: list[dict]):
        self.model.replace(rows)
        self.table.resizeColumnsToContents()


class SalesView(QWidget):
    # Emit 'sale' or 'quotation' when user toggles the mode.
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # --- Mode toggle (Sales | Quotations) ---
        modebar = QHBoxLayout()
        modebar.addWidget(QLabel("Mode:"))
        self.btn_mode_sales = QPushButton("Sales")
        self.btn_mode_quotes = QPushButton("Quotations")
        for b in (self.btn_mode_sales, self.btn_mode_quotes):
            b.setCheckable(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_mode_sales)
        self._mode_group.addButton(self.btn_mode_quotes)
        self.btn_mode_sales.setChecked(True)  # default
        modebar.addWidget(self.btn_mode_sales)
        modebar.addWidget(self.btn_mode_quotes)
        modebar.addStretch(1)
        root.addLayout(modebar)

        # --- Top toolbar ---
        bar = QHBoxLayout()
        self.btn_add = QPushButton("New")
        self.btn_edit = QPushButton("Edit")
        # self.btn_del = QPushButton("Delete")
        self.btn_return = QPushButton("Return")

        # Record Payment, Apply Credit & Print (Apply Credit is new)
        self.btn_record_payment = QPushButton("Record Payment…")
        self.btn_apply_credit = QPushButton("Apply Credit…")
        self.btn_print = QPushButton("Print")

        # Shown only in Quotation mode
        self.btn_convert = QPushButton("Convert to Sale")

        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_edit)
        bar.addWidget(self.btn_return)
        bar.addWidget(self.btn_record_payment)
        bar.addWidget(self.btn_apply_credit)  # NEW button in toolbar
        bar.addWidget(self.btn_print)
        bar.addWidget(self.btn_convert)

        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sales (id, customer, status)…")
        bar.addWidget(QLabel("Search:"))
        bar.addWidget(self.search, 2)
        root.addLayout(bar)

        # --- Main split: left (list + items + payments), right (details) ---
        split = QSplitter(Qt.Horizontal)

        left = W()
        lv = V(left)
        self.tbl = TableView()
        lv.addWidget(self.tbl, 3)

        self.items = SaleItemsView()
        lv.addWidget(self.items, 2)

        split.addWidget(left)

        self.details = SaleDetails()
        split.addWidget(self.details)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        # initial state for mode-dependent controls
        self._doc_type = "sale"
        self._apply_mode_visibility()

        # wiring for mode change
        self.btn_mode_sales.toggled.connect(self._on_mode_toggle)
        self.btn_mode_quotes.toggled.connect(self._on_mode_toggle)

    # --- Public helpers ----------------------------------------------------

    def current_doc_type(self) -> str:
        """Return the current mode as 'sale' or 'quotation'."""
        return self._doc_type

    def set_mode(self, doc_type: str):
        """Programmatically set the mode and update UI."""
        doc_type = (doc_type or "sale").lower()
        if doc_type not in ("sale", "quotation"):
            doc_type = "sale"
        self._doc_type = doc_type
        # Update toggle buttons to reflect state
        if doc_type == "sale":
            self.btn_mode_sales.setChecked(True)
        else:
            self.btn_mode_quotes.setChecked(True)
        self._apply_mode_visibility()

    # --- Internals ---------------------------------------------------------

    def _on_mode_toggle(self, _checked: bool):
        new_mode = "quotation" if self.btn_mode_quotes.isChecked() else "sale"
        if new_mode != self._doc_type:
            self._doc_type = new_mode
            self._apply_mode_visibility()
            self.modeChanged.emit(self._doc_type)

    def _apply_mode_visibility(self):
        """Show/hide or enable/disable widgets based on current mode."""
        is_quote = (self._doc_type == "quotation")

        # Buttons:
        # - Quotations: show Convert, hide/disable Return, Record Payment & Apply Credit
        # - Sales: hide Convert, enable Return, Record Payment & Apply Credit
        self.btn_convert.setVisible(is_quote)
        self.btn_convert.setEnabled(is_quote)

        self.btn_return.setVisible(not is_quote)
        self.btn_return.setEnabled(not is_quote)

        self.btn_record_payment.setVisible(not is_quote)
        self.btn_record_payment.setEnabled(not is_quote)

        self.btn_apply_credit.setVisible(not is_quote)   # NEW: only in Sales mode
        self.btn_apply_credit.setEnabled(not is_quote)


        # Search placeholder
        self.search.setPlaceholderText(
            "Search quotations (id, customer, status)…" if is_quote
            else "Search sales (id, customer, status)…"
        )
