import sqlite3

import pytest

from inventory_management.database import schema
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.modules.purchase.form import PurchaseForm
from inventory_management.modules.purchase.payment_form import PaymentForm
from inventory_management.modules.purchase.return_form import PurchaseReturnForm
from inventory_management.modules.purchase.validation import (
    SALE_PRICE_RULE_MESSAGE,
    parse_strict_float,
)


@pytest.mark.parametrize("value", ["1abc2", "12xyz", "abc12", "--10", "10..5", ""])
def test_strict_purchase_numeric_parser_rejects_malformed_input(value):
    with pytest.raises(ValueError):
        parse_strict_float(value)


@pytest.mark.parametrize("value, expected", [("10", 10.0), ("10.5", 10.5), ("0.75", 0.75)])
def test_strict_purchase_numeric_parser_accepts_decimal_input(value, expected):
    assert parse_strict_float(value) == expected


def test_payment_and_return_forms_use_strict_numeric_parsing():
    for invalid in ("1abc2", "12xyz", "10..5"):
        with pytest.raises(ValueError):
            PaymentForm._to_float_safe(None, invalid)
        with pytest.raises(ValueError):
            PurchaseReturnForm._to_float_safe(None, invalid)


def test_purchase_form_blocks_product_without_base_uom(qtbot, conn, ids):
    conn.execute("INSERT INTO products (name, min_stock_level) VALUES ('No Base UOM Product', 0)")
    product_id = conn.execute(
        "SELECT product_id FROM products WHERE name='No Base UOM Product'"
    ).fetchone()[0]

    form = PurchaseForm(None, vendors=VendorsRepo(conn), products=ProductsRepo(conn))
    qtbot.addWidget(form)
    form.cmb_vendor.setCurrentIndex(form.cmb_vendor.findData(ids["vendor_id"]))

    product_combo = form.tbl.cellWidget(0, 1)
    product_combo.setCurrentIndex(product_combo.findData(product_id))
    form.tbl.item(0, 2).setText("1")
    form.tbl.item(0, 3).setText("10")
    form.tbl.item(0, 4).setText("11")

    assert form._base_uom_id(product_id) is None
    ok, errors = form.validate_form()

    assert not ok
    assert any("Selected product has no configured base UOM" in err for err in errors)


@pytest.mark.parametrize("sale_price", ["9.99", "10"])
def test_purchase_form_rejects_sale_price_not_greater_than_purchase_price(
    qtbot, conn, ids, sale_price
):
    form = PurchaseForm(None, vendors=VendorsRepo(conn), products=ProductsRepo(conn))
    qtbot.addWidget(form)
    form.cmb_vendor.setCurrentIndex(form.cmb_vendor.findData(ids["vendor_id"]))

    product_combo = form.tbl.cellWidget(0, 1)
    product_combo.setCurrentIndex(product_combo.findData(ids["prod_A"]))
    form.tbl.item(0, 2).setText("1")
    form.tbl.item(0, 3).setText("10")
    form.tbl.item(0, 4).setText(sale_price)

    ok, errors = form.validate_form()

    assert not ok
    assert any(SALE_PRICE_RULE_MESSAGE in err for err in errors)


def test_purchases_repo_rejects_sale_price_not_greater_than_purchase_price(conn, ids):
    repo = PurchasesRepo(conn)
    header = PurchaseHeader(
        purchase_id="PO-PRICE-RULE",
        vendor_id=ids["vendor_id"],
        date="2024-01-01",
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )
    item = PurchaseItem(
        item_id=None,
        purchase_id="PO-PRICE-RULE",
        product_id=ids["prod_A"],
        quantity=1.0,
        uom_id=ids["uom_piece"],
        purchase_price=10.0,
        sale_price=10.0,
        item_discount=0.0,
    )

    with pytest.raises(ValueError, match=SALE_PRICE_RULE_MESSAGE):
        repo.create_purchase(header, [item])


def test_schema_rejects_sale_price_not_greater_than_purchase_price():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(schema.SQL)
    con.execute("INSERT INTO vendors (vendor_id, name, contact_info) VALUES (1, 'Vendor', 'Contact')")
    con.execute("INSERT INTO products (product_id, name, min_stock_level) VALUES (1, 'Widget', 0)")
    con.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'Piece')")
    con.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) "
        "VALUES (1, 1, 1, 1)"
    )
    con.execute(
        "INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status) "
        "VALUES ('PO-SCHEMA-PRICE', 1, '2024-01-01', 10, 'unpaid')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="Sale price must be greater than purchase price"):
        con.execute(
            "INSERT INTO purchase_items "
            "(purchase_id, product_id, quantity, uom_id, purchase_price, sale_price) "
            "VALUES ('PO-SCHEMA-PRICE', 1, 1, 1, 10, 10)"
        )
