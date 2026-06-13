from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ProductSummary:
    total: int = 0
    low_stock: int = 0
    priced: int = 0
    with_uoms: int = 0


class ProductToolbar(QWidget):
    add_requested = Signal()
    import_requested = Signal()
    edit_requested = Signal()
    delete_requested = Signal()
    price_requested = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.btn_add = QPushButton("Add Product")
        self.btn_import = QPushButton("Import")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        self.btn_price = QPushButton("Set Price")

        for btn in (
            self.btn_add,
            self.btn_import,
            self.btn_edit,
            self.btn_delete,
            self.btn_price,
        ):
            root.addWidget(btn)

        root.addStretch(1)

        self.search = QLabel("Search")
        self.search.setVisible(False)
        root.addWidget(self.search)

    def wire(self, search_widget: QWidget) -> None:
        self.btn_add.clicked.connect(lambda: self.add_requested.emit())
        self.btn_import.clicked.connect(lambda: self.import_requested.emit())
        self.btn_edit.clicked.connect(lambda: self.edit_requested.emit())
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit())
        self.btn_price.clicked.connect(lambda: self.price_requested.emit())
        if hasattr(search_widget, "textChanged"):
            search_widget.textChanged.connect(lambda text: self.search_changed.emit(text))


class ProductSummaryBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("productSummaryBar")

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(12)

        self.lbl_total, self.val_total = self._pill("Products", "0")
        self.lbl_low_stock, self.val_low_stock = self._pill("Low Stock", "0")
        self.lbl_priced, self.val_priced = self._pill("Priced", "0")
        self.lbl_with_uoms, self.val_with_uoms = self._pill("With UoMs", "0")

        root.addWidget(self.lbl_total)
        root.addWidget(self.lbl_low_stock)
        root.addWidget(self.lbl_priced)
        root.addWidget(self.lbl_with_uoms)
        root.addStretch(1)

    def _pill(self, title: str, value: str) -> tuple[QFrame, QLabel]:
        box = QFrame(self)
        box.setFrameShape(QFrame.StyledPanel)
        box.setObjectName("productSummaryPill")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 11px; color: #666;")
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet("font-size: 18px; font-weight: 600;")
        lay.addWidget(title_lbl)
        lay.addWidget(value_lbl)
        return box, value_lbl

    def set_summary(self, summary: ProductSummary) -> None:
        self.val_total.setText(str(summary.total))
        self.val_low_stock.setText(str(summary.low_stock))
        self.val_priced.setText(str(summary.priced))
        self.val_with_uoms.setText(str(summary.with_uoms))


class ProductDetailsPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("productDetailsPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.title = QLabel("No product selected")
        self.title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.title.setWordWrap(True)
        root.addWidget(self.title)

        self.subtitle = QLabel("Select a product to see details.")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #666;")
        root.addWidget(self.subtitle)

        self.fields = {}
        for key, label in (
            ("product_id", "Product ID"),
            ("category", "Category"),
            ("min_stock", "Min Stock"),
            ("base_uom", "Base UoM"),
            ("alt_uoms", "Alt UoMs"),
            ("sale_price", "Sale Price"),
            ("cost_price", "Last Cost"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addStretch(1)
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.fields[key] = value
            row.addWidget(value)
            root.addLayout(row)

        self.notes = QLabel(" ")
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: #666;")
        root.addWidget(self.notes)
        root.addStretch(1)

    def clear(self) -> None:
        self.title.setText("No product selected")
        self.subtitle.setText("Select a product to see details.")
        for value in self.fields.values():
            value.setText("—")
        self.notes.setText(" ")

    def set_empty(self, title: str, subtitle: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        for value in self.fields.values():
            value.setText("—")
        self.notes.setText(" ")

    def set_product(
        self,
        *,
        product_id: int,
        name: str,
        category: Optional[str],
        min_stock_level: float,
        base_uom_name: Optional[str],
        alt_uom_names: Optional[str],
        sale_price: Optional[float] = None,
        cost_price: Optional[float] = None,
        description: Optional[str] = None,
    ) -> None:
        self.title.setText(name or "Unnamed product")
        parts = [f"Product #{product_id}"]
        if category:
            parts.append(category)
        self.subtitle.setText(" · ".join(parts))
        self.fields["product_id"].setText(str(product_id))
        self.fields["category"].setText(category or "—")
        self.fields["min_stock"].setText(f"{float(min_stock_level or 0.0):g}")
        self.fields["base_uom"].setText(base_uom_name or "—")
        self.fields["alt_uoms"].setText(alt_uom_names or "—")
        self.fields["sale_price"].setText("—" if sale_price is None else f"{float(sale_price):,.2f}")
        self.fields["cost_price"].setText("—" if cost_price is None else f"{float(cost_price):,.2f}")
        self.notes.setText(description or "No description.")
