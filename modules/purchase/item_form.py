from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QVBoxLayout, QComboBox, QLineEdit
from PySide6.QtCore import Qt
from ...utils.validators import is_positive_number, non_empty
from ...database.repositories.products_repo import ProductsRepo

class PurchaseItemForm(QDialog):
    def __init__(self, parent=None, repo: ProductsRepo | None = None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase Item")
        self.setModal(True)
        self.repo = repo

        self.cmb_product = QComboBox()
        self.cmb_product.setEditable(True)
        for p in self.repo.list_products():
            self.cmb_product.addItem(f"{p.name} (#{p.product_id})", p.product_id)
        self.cmb_product.currentIndexChanged.connect(self._load_uoms)

        self.cmb_uom = QComboBox()
        self.cmb_uom.setEditable(True)

        self.txt_qty = QLineEdit();      self.txt_qty.setPlaceholderText("Quantity")
        self.txt_buy = QLineEdit();      self.txt_buy.setPlaceholderText("Purchase price")
        self.txt_sale = QLineEdit();     self.txt_sale.setPlaceholderText("Default sale price")
        self.txt_disc = QLineEdit();     self.txt_disc.setPlaceholderText("Item discount (0)")

        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Product*", self.cmb_product)
        form.addRow("UoM*", self.cmb_uom)
        form.addRow("Quantity*", self.txt_qty)
        form.addRow("Purchase Price*", self.txt_buy)
        form.addRow("Sale Price*", self.txt_sale)
        form.addRow("Item Discount", self.txt_disc)
        lay.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._payload = None
        self._load_uoms()
        if initial:
            # initial dict keys: product_id, uom_id, quantity, purchase_price, sale_price, item_discount
            idx = self.cmb_product.findData(initial["product_id"])
            if idx >= 0: self.cmb_product.setCurrentIndex(idx)
            self._load_uoms()
            idx = self.cmb_uom.findData(initial["uom_id"])
            if idx >= 0: self.cmb_uom.setCurrentIndex(idx)
            self.txt_qty.setText(str(initial["quantity"]))
            self.txt_buy.setText(str(initial["purchase_price"]))
            self.txt_sale.setText(str(initial["sale_price"]))
            self.txt_disc.setText(str(initial["item_discount"]))

    def _load_uoms(self):
        self.cmb_uom.clear()
        pid = self.cmb_product.currentData()
        if pid:
            # prefer product-specific UOMs; fallback to global list
            puoms = self.repo.product_uoms(pid)
            if puoms:
                for m in puoms:
                    self.cmb_uom.addItem(m["unit_name"], m["uom_id"])
                return
        for u in self.repo.list_uoms():
            self.cmb_uom.addItem(u["unit_name"], u["uom_id"])

    def get_payload(self) -> dict | None:
        pid = self.cmb_product.currentData()
        uom = self.cmb_uom.currentData()
        if not pid or not uom: return None
        if not (is_positive_number(self.txt_qty.text()) and is_positive_number(self.txt_buy.text()) and is_positive_number(self.txt_sale.text())):
            return None
        disc = float(self.txt_disc.text()) if self.txt_disc.text().strip() else 0.0
        return {
            "product_id": int(pid),
            "uom_id": int(uom),
            "quantity": float(self.txt_qty.text()),
            "purchase_price": float(self.txt_buy.text()),
            "sale_price": float(self.txt_sale.text()),
            "item_discount": float(disc)
        }

    def accept(self):
        p = self.get_payload()
        if p is None: return
        self._payload = p
        super().accept()

    def payload(self): return self._payload
