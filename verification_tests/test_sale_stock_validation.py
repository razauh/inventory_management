from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))

database_package = types.ModuleType("inventory_management.database")
database_package.__path__ = [str(PROJECT_ROOT / "database")]
sys.modules.setdefault("inventory_management.database", database_package)

from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import init_schema


@pytest.fixture
def sales_stock_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[str, int]]:
    db_path = tmp_path / "sale-stock-validation.sqlite"
    init_schema(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    customer_id = con.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Test Customer', '123')"
    ).lastrowid
    uom_id = con.execute("INSERT INTO uoms (unit_name) VALUES ('Each')").lastrowid
    product_id = con.execute(
        "INSERT INTO products (name, description, category) VALUES ('Test Item', '', '')"
    ).lastrowid
    con.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1.0)",
        (product_id, uom_id),
    )

    # Let's seed initial stock of 10 items
    con.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type, date
        ) VALUES (?, 10.0, ?, 'purchase', '2026-06-11')
        """,
        (product_id, uom_id),
    )
    con.commit()

    ids = {
        "customer": int(customer_id),
        "product": int(product_id),
        "uom": int(uom_id),
    }
    try:
        yield con, ids
    finally:
        con.close()


def test_create_sale_insufficient_stock_fails(sales_stock_db):
    con, ids = sales_stock_db
    repo = SalesRepo(con)

    header = SaleHeader(
        sale_id="SALE-1",
        customer_id=ids["customer"],
        date="2026-06-11",
        total_amount=1200,
        order_discount=0,
        payment_status="unpaid",
        paid_amount=0,
        advance_payment_applied=0,
        notes=None,
        created_by=None,
    )
    # Requested 11 when stock is 10
    items = [SaleItem(None, "SALE-1", ids["product"], 11.0, ids["uom"], 100, 0)]

    with pytest.raises(ValueError, match="Insufficient stock"):
        repo.create_sale(header, items)


def test_create_sale_aggregate_oversell_fails(sales_stock_db):
    con, ids = sales_stock_db
    repo = SalesRepo(con)

    header = SaleHeader(
        sale_id="SALE-2",
        customer_id=ids["customer"],
        date="2026-06-11",
        total_amount=1200,
        order_discount=0,
        payment_status="unpaid",
        paid_amount=0,
        advance_payment_applied=0,
        notes=None,
        created_by=None,
    )
    # Two duplicate rows requesting 6 each (total 12) when stock is 10
    items = [
        SaleItem(None, "SALE-2", ids["product"], 6.0, ids["uom"], 100, 0),
        SaleItem(None, "SALE-2", ids["product"], 6.0, ids["uom"], 100, 0),
    ]

    with pytest.raises(ValueError, match="Insufficient stock"):
        repo.create_sale(header, items)


def test_update_sale_oversell_fails(sales_stock_db):
    con, ids = sales_stock_db
    repo = SalesRepo(con)

    # First, create a valid sale of 6 items (stock remaining: 4)
    header = SaleHeader(
        sale_id="SALE-3",
        customer_id=ids["customer"],
        date="2026-06-11",
        total_amount=600,
        order_discount=0,
        payment_status="unpaid",
        paid_amount=0,
        advance_payment_applied=0,
        notes=None,
        created_by=None,
    )
    items = [SaleItem(None, "SALE-3", ids["product"], 6.0, ids["uom"], 100, 0)]
    repo.create_sale(header, items)

    # Now, update it to 12 items (original 6 plus 6 more, total 12, exceeding stock of 10)
    updated_items = [SaleItem(None, "SALE-3", ids["product"], 12.0, ids["uom"], 100, 0)]
    with pytest.raises(ValueError, match="Insufficient stock"):
        repo.update_sale(header, updated_items)


def test_convert_quotation_oversell_fails(sales_stock_db):
    con, ids = sales_stock_db
    repo = SalesRepo(con)

    # Create a quotation requesting 12 items
    con.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, doc_type
        ) VALUES ('QUOTE-1', ?, '2026-06-11', 1200, 0, 'unpaid', 0, 0, 'quotation')
        """,
        (ids["customer"],),
    )
    con.execute(
        """
        INSERT INTO sale_items (
            sale_id, product_id, quantity, uom_id, unit_price, item_discount
        ) VALUES ('QUOTE-1', ?, 12.0, ?, 100, 0)
        """,
        (ids["product"], ids["uom"]),
    )
    con.commit()

    # Try to convert it to a sale. It should fail since stock is 10.
    with pytest.raises(ValueError, match="Insufficient stock"):
        repo.convert_quotation_to_sale("QUOTE-1", "SALE-4", "2026-06-11", None)


def test_database_trigger_enforces_sale_stock_limit(sales_stock_db):
    con, ids = sales_stock_db

    # Attempting to directly insert a sale transaction that exceeds stock
    # Stock is 10. We try to insert 11.
    with pytest.raises(sqlite3.IntegrityError, match="Sale quantity exceeds available stock"):
        con.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type, date, reference_table, reference_id
            ) VALUES (?, 11.0, ?, 'sale', '2026-06-11', 'sales', 'SALE-5')
            """,
            (ids["product"], ids["uom"]),
        )
