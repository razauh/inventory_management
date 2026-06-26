import sqlite3
from decimal import Decimal

import pytest

from database.repositories.inventory_repo import DomainError, InventoryRepo
from database.schema import SQL
from modules.accounting import (
    AccountingService,
    PurchaseInventoryLine,
    PurchaseInventoryPayload,
    SaleInventoryLine,
    SaleInventoryPayload,
    StockAdjustmentPayload,
    StockAdjustmentResult,
)


@pytest.fixture()
def inventory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Test')"
    ).lastrowid
    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    conn.execute(
        "INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status) VALUES ('P1', ?, '2026-06-20', 50, 'unpaid')",
        (vendor_id,),
    )
    purchase_item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
        ) VALUES ('P1', ?, 5, ?, 10, 12, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, payment_status, doc_type) VALUES ('S1', ?, '2026-06-21', 24, 'unpaid', 'sale')",
        (customer_id,),
    )
    sale_item_id = conn.execute(
        """
        INSERT INTO sale_items (
            sale_id, product_id, quantity, uom_id, unit_price, item_discount
        ) VALUES ('S1', ?, 2, ?, 12, 0)
        """,
        (product_id, uom_id),
    ).lastrowid

    try:
        yield conn, int(product_id), int(uom_id), int(purchase_item_id), int(sale_item_id)
    finally:
        conn.close()


def test_no_stock_returns_zero(inventory_db):
    conn, product_id, _uom_id, _purchase_item_id, _sale_item_id = inventory_db

    value = AccountingService(conn).get_inventory_value(product_id)

    assert value.quantity == 0
    assert value.unit_value == 0
    assert value.total_value == 0


def test_purchase_creates_inventory_value(inventory_db):
    conn, product_id, uom_id, purchase_item_id, _sale_item_id = inventory_db
    service = AccountingService(conn)

    service.record_purchase_inventory_event(
        PurchaseInventoryPayload(
            purchase_id="P1",
            date="2026-06-20",
            created_by=None,
            lines=(
                PurchaseInventoryLine(
                    item_id=purchase_item_id,
                    product_id=product_id,
                    quantity=Decimal("5"),
                    uom_id=uom_id,
                ),
            ),
        )
    )

    value = service.get_inventory_value(product_id)

    assert float(value.quantity) == pytest.approx(5.0)
    assert float(value.unit_value) == pytest.approx(10.0)
    assert float(value.total_value) == pytest.approx(50.0)


def test_sale_reduces_quantity_and_keeps_unit_value(inventory_db):
    conn, product_id, uom_id, purchase_item_id, sale_item_id = inventory_db
    service = AccountingService(conn)
    service.record_purchase_inventory_event(
        PurchaseInventoryPayload(
            purchase_id="P1",
            date="2026-06-20",
            created_by=None,
            lines=(PurchaseInventoryLine(purchase_item_id, product_id, Decimal("5"), uom_id),),
        )
    )
    service.record_sale_inventory_event(
        SaleInventoryPayload(
            sale_id="S1",
            date="2026-06-21",
            created_by=None,
            lines=(SaleInventoryLine(sale_item_id, product_id, Decimal("2"), uom_id),),
        )
    )

    value = service.get_inventory_value(product_id)

    assert float(value.quantity) == pytest.approx(3.0)
    assert float(value.unit_value) == pytest.approx(10.0)
    assert float(value.total_value) == pytest.approx(30.0)


def test_positive_adjustment_increases_quantity_at_current_valuation(inventory_db):
    conn, product_id, uom_id, purchase_item_id, _sale_item_id = inventory_db
    service = AccountingService(conn)
    service.record_purchase_inventory_event(
        PurchaseInventoryPayload(
            purchase_id="P1",
            date="2026-06-20",
            created_by=None,
            lines=(PurchaseInventoryLine(purchase_item_id, product_id, Decimal("5"), uom_id),),
        )
    )

    service.record_stock_adjustment_event(
        StockAdjustmentPayload(product_id, uom_id, Decimal("2"), "2026-06-22")
    )
    value = service.get_inventory_value(product_id)

    assert float(value.quantity) == pytest.approx(7.0)
    assert float(value.unit_value) == pytest.approx(10.0)
    assert float(value.total_value) == pytest.approx(70.0)


def test_negative_adjustment_rejects_overdraw(inventory_db):
    conn, product_id, uom_id, _purchase_item_id, _sale_item_id = inventory_db

    with pytest.raises(DomainError, match="available stock"):
        AccountingService(conn).record_stock_adjustment_event(
            StockAdjustmentPayload(product_id, uom_id, Decimal("-1"), "2026-06-22")
        )


def test_inventory_repo_add_adjustment_routes_through_accounting_service(monkeypatch, inventory_db):
    conn, product_id, uom_id, _purchase_item_id, _sale_item_id = inventory_db
    calls = []

    def fake_record(self, payload):
        calls.append(payload)
        return StockAdjustmentResult(transaction_id=123, product_id=payload.product_id)

    monkeypatch.setattr(AccountingService, "record_stock_adjustment_event", fake_record)

    tx_id = InventoryRepo(conn).add_adjustment(
        product_id=product_id,
        uom_id=uom_id,
        quantity=2,
        date="2026-06-22",
        notes="count",
        created_by=7,
    )

    assert tx_id == 123
    assert calls == [
        StockAdjustmentPayload(
            product_id=product_id,
            uom_id=uom_id,
            quantity=2.0,
            date="2026-06-22",
            notes="count",
            created_by=7,
        )
    ]
