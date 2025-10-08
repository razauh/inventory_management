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
        self._base_uom_id = None
        self.cmb_uom = QComboBox()
        self.cmb_uom.setEditable(False)
        self.cmb_uom.setEnabled(False)
        self.txt_qty = QLineEdit(); self.txt_qty.setPlaceholderText("Quantity")
        self.txt_buy = QLineEdit(); self.txt_buy.setPlaceholderText("Purchase price")
        self.txt_sale = QLineEdit(); self.txt_sale.setPlaceholderText("Default sale price")
        self.txt_disc = QLineEdit(); self.txt_disc.setPlaceholderText("Item discount (per-unit)")
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
        self.cmb_product.currentIndexChanged.connect(self._on_product_changed)
        self._on_product_changed()
        if initial:
            idx = self.cmb_product.findData(initial["product_id"])
            if idx >= 0:
                self.cmb_product.setCurrentIndex(idx)
            self.txt_qty.setText(str(initial["quantity"]))
            self.txt_buy.setText(str(initial["purchase_price"]))
            self.txt_sale.setText(str(initial["sale_price"]))
            self.txt_disc.setText(str(initial["item_discount"]))

    def _fetch_product_record(self, product_id):
        """
        Fetch product record with base UoM information using multiple fallback approaches.
        Returns dict with product info or None if not found.
        """
        repo = getattr(self, "repo", None)
        for m in ("get_by_id", "get", "get_product", "find_by_id", "get_one"):
            if repo and hasattr(repo, m):
                try:
                    rec = getattr(repo, m)(int(product_id))
                    if rec:
                        return dict(rec)
                except Exception:
                    pass
        for m in ("list", "list_all", "list_products"):
            if repo and hasattr(repo, m):
                try:
                    rows = getattr(repo, m)()
                    for row in rows or []:
                        d = dict(row)
                        if int(d.get("product_id") or d.get("id") or -1) == int(product_id):
                            return d
                except Exception:
                    pass
        try:
            conn = getattr(repo, "conn", None)
            if conn is not None:
                row = conn.execute(
                    """
                    SELECT p.product_id,
                           COALESCE(p.base_uom_id, p.uom_id) AS base_uom_id,
                           u.unit_name AS unit_name
                    FROM products p
                    LEFT JOIN uoms u ON u.uom_id = COALESCE(p.base_uom_id, p.uom_id)
                    WHERE p.product_id = ?
                    """,
                    (int(product_id),)
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            pass
        return None

    def _resolve_base_uom(self, product_id: int):
        """
        Try repo.get_base_uom(product_id) first. If not available, scan repo.product_uoms(product_id) for is_base=1.
        Returns (uom_id, unit_name) or None if not found.
        """
        if hasattr(self.repo, "get_base_uom"):
            try:
                row = self.repo.get_base_uom(product_id)
                if row:
                    rd = dict(row)
                    if rd.get("uom_id") is not None:
                        return int(rd["uom_id"]), rd["unit_name"]
            except Exception:
                pass
        try:
            puoms = self.repo.product_uoms(product_id) or []
            for m in puoms:
                md = dict(m)
                if str(md.get("is_base", 0)) in ("1", "True", "true"):
                    return int(md["uom_id"]), md["unit_name"]
        except Exception:
            pass
        return None

    def _on_product_changed(self, *_):
        """Load ONLY the base UoM for the currently selected product (sync, no timers)."""
        try:
            pid = self.cmb_product.currentData()
        except Exception:
            pid = None
        if pid is None:
            return
        base = None
        if getattr(self, "repo", None) and hasattr(self.repo, "get_base_uom"):
            try:
                row = self.repo.get_base_uom(int(pid))
                if row:
                    base = (int(row["uom_id"]), row["unit_name"])
            except Exception:
                pass
        if base is None and hasattr(self.repo, "product_uoms"):
            try:
                for m in (self.repo.product_uoms(int(pid)) or []):
                    md = dict(m)
                    if int(md.get("is_base") or 0) == 1:
                        base = (int(md["uom_id"]), md["unit_name"])
                        break
            except Exception:
                pass
        if base is None:
            try:
                conn = getattr(self.repo, "conn", None)
                if conn:
                    row = conn.execute(
                        """
                        SELECT
                            COALESCE(pu.uom_id, p.uom_id) AS uom_id,
                            u.unit_name
                        FROM products p
                        LEFT JOIN product_uoms pu
                               ON pu.product_id = p.product_id AND pu.is_base = 1
                        LEFT JOIN uoms u
                               ON u.uom_id = COALESCE(pu.uom_id, p.uom_id)
                        WHERE p.product_id = ?
                        """,
                        (int(pid),)
                    ).fetchone()
                    if row:
                        is_mapping = isinstance(row, dict) or hasattr(row, "keys")
                        uom_id = int(row["uom_id"] if is_mapping else row[0])
                        name = row["unit_name"] if is_mapping else row[1]
                        base = (uom_id, name)
            except Exception:
                pass
        self._base_uom_id = base[0] if base else None
        if hasattr(self, "cmb_uom"):
            self.cmb_uom.blockSignals(True)
            try:
                self.cmb_uom.clear()
                if base:
                    self.cmb_uom.addItem(str(base[1]), int(base[0]))
                else:
                    self.cmb_uom.addItem("UoM", -1)
            finally:
                self.cmb_uom.blockSignals(False)
            self.cmb_uom.setEnabled(False)

    def get_payload(self) -> dict | None:
        pid = self.cmb_product.currentData()
        uom_id = self._base_uom_id if self._base_uom_id is not None else (self.cmb_uom.currentData() if hasattr(self, "cmb_uom") else None)
        if not pid or uom_id is None:
            return None
        try:
            qty_val = float((self.txt_qty.text() or "").strip())
            buy_val = float((self.txt_buy.text() or "").strip())
            sale_val = float((self.txt_sale.text() or "0").strip())
        except Exception:
            return None
        if not (qty_val > 0.0):
            return None
        if not (buy_val > 0.0):
            return None
        if sale_val < 0.0:
            return None
        disc_str = (self.txt_disc.text() or "").strip()
        try:
            disc_val = float(disc_str) if disc_str else 0.0
        except Exception:
            return None
        if disc_val < 0.0 or disc_val >= buy_val:
            return None
        return {
            "product_id": int(pid),
            "uom_id": int(uom_id),
            "quantity": qty_val,
            "purchase_price": buy_val,
            "sale_price": sale_val,
            "item_discount": disc_val
        }

    def accept(self):
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload
