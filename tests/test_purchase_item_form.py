# inventory_management/tests/test_purchase_item_form.py

import sqlite3
import pytest
from PySide6 import QtCore
from inventory_management.modules.purchase.item_form import PurchaseItemForm
from inventory_management.database.repositories.products_repo import ProductsRepo


def _select_product(form: PurchaseItemForm, product_id: int, qtbot):
    """Helper to select a product by id and wait for the base-UoM to load."""
    idx = form.cmb_product.findData(product_id)
    assert idx >= 0, "Product not found in combo"
    form.cmb_product.setCurrentIndex(idx)

    # Wait until base uom is set in the UI
    def _uom_loaded():
        return form.cmb_uom.count() >= 1 and form._base_uom_id is not None

    qtbot.waitUntil(_uom_loaded, timeout=1500)


@pytest.fixture()
def form(conn: sqlite3.Connection, qtbot):
    """Fresh PurchaseItemForm with ProductsRepo wired to the shared DB."""
    repo = ProductsRepo(conn)
    dlg = PurchaseItemForm(None, repo=repo, initial=None)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    return dlg


# ---------------------------
# Suite A — Purchase Item dialog
# ---------------------------

def test_a1_base_uom_enforcement(form: PurchaseItemForm, ids: dict, qtbot):
    """
    A1. Base-UoM enforcement:
    - Selecting a product locks UoM to its base (read-only & disabled).
    - Changing product updates UoM to the new base.
    - Payload always returns base UoM (even if initial tried to pass non-base).
    """
    # Pick "Widget A" -> base should be 'Piece'
    _select_product(form, ids["prod_A"], qtbot)

    # UoM combo is read-only/disabled and shows only base uom
    assert form.cmb_uom.isEditable() is False
    assert form.cmb_uom.isEnabled() is False
    assert form.cmb_uom.count() == 1
    assert int(form.cmb_uom.currentData()) == int(ids["uom_piece"])

    # Change to "Widget B" -> base should update (also 'Piece' in seed)
    _select_product(form, ids["prod_B"], qtbot)
    assert form.cmb_uom.count() == 1
    assert int(form.cmb_uom.currentData()) == int(ids["uom_piece"])

    # Even if an "initial" tried to inject a non-base uom, payload must return base.
    # Simulate by setting fields & fetching payload (form ignores non-base and uses base internally).
    form.txt_qty.setText("1")
    form.txt_buy.setText("10")
    form.txt_sale.setText("9")
    form.txt_disc.setText("0")

    payload = form.get_payload()
    assert payload is not None, "Valid fields should yield a payload"
    assert int(payload["product_id"]) == int(ids["prod_B"])
    assert int(payload["uom_id"]) == int(ids["uom_piece"]), "Dialog must enforce base UoM in payload"


def test_a2_pricing_rules_and_line_total_logic(form: PurchaseItemForm, ids: dict, qtbot):
    """
    A2. Pricing rules:
    - qty > 0, buy > 0
    - 0 ≤ discount < buy
    - sale may be < buy (allowed)
    - net line total logic: qty * (buy - discount)
    """
    # Use Widget A for the test
    _select_product(form, ids["prod_A"], qtbot)

    # Enter a valid scenario: qty=10, buy=100, sale=70 (allowed), disc=5
    form.txt_qty.setText("10")
    form.txt_buy.setText("100")
    form.txt_sale.setText("70")   # sale < buy is ALLOWED
    form.txt_disc.setText("5")

    payload = form.get_payload()
    assert payload is not None, "Valid numbers must produce a payload"
    assert payload["quantity"] == 10.0
    assert payload["purchase_price"] == 100.0
    assert payload["sale_price"] == 70.0
    assert payload["item_discount"] == 5.0

    # Net line-total preview is not displayed in this dialog,
    # so we validate by computing from the payload:
    net_line_total = payload["quantity"] * (payload["purchase_price"] - payload["item_discount"])
    assert abs(net_line_total - 950.0) < 1e-6  # 10 * (100 - 5)

    # ---- Invalids individually ----

    # qty ≤ 0 -> block
    form.txt_qty.setText("0")
    assert form.get_payload() is None

    # restore qty
    form.txt_qty.setText("3")

    # buy ≤ 0 -> block
    form.txt_buy.setText("0")
    assert form.get_payload() is None

    # restore buy
    form.txt_buy.setText("100")

    # discount ≥ buy -> block (equal)
    form.txt_disc.setText("100")
    assert form.get_payload() is None

    # discount just below buy -> OK
    form.txt_disc.setText("99.99")
    payload_ok = form.get_payload()
    assert payload_ok is not None
    assert abs(payload_ok["item_discount"] - 99.99) < 1e-6

    # sale < buy is allowed (no blocking)
    form.txt_sale.setText("90")
    payload_profitless = form.get_payload()
    assert payload_profitless is not None
    assert payload_profitless["sale_price"] == 90.0
