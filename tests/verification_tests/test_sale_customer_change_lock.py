from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))

from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import init_schema


@pytest.fixture
def sale_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[str, int]]:
    db_path = tmp_path / "sale-customer-change-lock.sqlite"
    init_schema(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    customer_1 = con.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer One', '1')"
    ).lastrowid
    customer_2 = con.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer Two', '2')"
    ).lastrowid
    uom_id = con.execute("INSERT INTO uoms (unit_name) VALUES ('Each')").lastrowid
    product_id = con.execute(
        "INSERT INTO products (name, description, category) VALUES ('Item', '', '')"
    ).lastrowid
    con.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    con.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, doc_type
        ) VALUES ('SALE-LOCK', ?, '2026-06-11', 100, 0, 'unpaid', 0, 0, 'sale')
        """,
        (customer_1,),
    )
    item_id = con.execute(
        """
        INSERT INTO sale_items (
            sale_id, product_id, quantity, uom_id, unit_price, item_discount
        ) VALUES ('SALE-LOCK', ?, 1, ?, 100, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    con.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 100.0, ?, 'adjustment', NULL, NULL, NULL, '2026-06-11', 1)
        """,
        (product_id, uom_id),
    )
    from inventory_management.database.repositories.inventory_repo import rebuild_dirty_valuations
    rebuild_dirty_valuations(con)
    con.commit()
    ids = {
        "customer_1": int(customer_1),
        "customer_2": int(customer_2),
        "product": int(product_id),
        "uom": int(uom_id),
        "item": int(item_id),
    }
    try:
        yield con, ids
    finally:
        con.close()


def _updated_header(customer_id: int) -> SaleHeader:
    return SaleHeader(
        sale_id="SALE-LOCK",
        customer_id=customer_id,
        date="2026-06-11",
        total_amount=100,
        order_discount=0,
        payment_status="unpaid",
        paid_amount=0,
        advance_payment_applied=0,
        notes="Edited",
        created_by=None,
    )


def _updated_items(ids: dict[str, int]) -> list[SaleItem]:
    return [
        SaleItem(None, "SALE-LOCK", ids["product"], 1, ids["uom"], 100, 0)
    ]


def _add_locking_activity(
    con: sqlite3.Connection, ids: dict[str, int], activity: str
) -> None:
    if activity == "payment":
        con.execute(
            """
            INSERT INTO sale_payments (
                sale_id, date, amount, method, instrument_type, clearing_state
            ) VALUES ('SALE-LOCK', '2026-06-11', 10, 'Cash', 'other', 'cleared')
            """
        )
    elif activity == "applied_advance":
        con.execute(
            """
            INSERT INTO customer_advances (
                customer_id, tx_date, amount, source_type, source_id
            ) VALUES (?, '2026-06-11', 20, 'deposit', NULL)
            """,
            (ids["customer_1"],),
        )
        con.execute(
            """
            INSERT INTO customer_advances (
                customer_id, tx_date, amount, source_type, source_id
            ) VALUES (?, '2026-06-11', -10, 'applied_to_sale', 'SALE-LOCK')
            """,
            (ids["customer_1"],),
        )
    elif activity == "return":
        con.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id, date
            ) VALUES (?, 1, ?, 'sale_return', 'sales', 'SALE-LOCK', ?, '2026-06-11')
            """,
            (ids["product"], ids["uom"], ids["item"]),
        )
    elif activity == "return_credit":
        con.execute(
            """
            INSERT INTO customer_advances (
                customer_id, tx_date, amount, source_type, source_id
            ) VALUES (?, '2026-06-11', 10, 'return_credit', 'SALE-LOCK')
            """,
            (ids["customer_1"],),
        )
    con.commit()


@pytest.mark.parametrize("activity", ["payment", "applied_advance", "return", "return_credit"])
def test_customer_change_is_blocked_after_linked_activity(
    sale_db: tuple[sqlite3.Connection, dict[str, int]], activity: str
) -> None:
    con, ids = sale_db
    _add_locking_activity(con, ids, activity)
    repo = SalesRepo(con)

    with pytest.raises(
        ValueError,
        match="Cannot (change the sale customer|edit a sale) after (payments, credits, or )?returns? exist",
    ):
        repo.update_sale(
            _updated_header(ids["customer_2"]),
            _updated_items(ids),
        )

    row = con.execute(
        "SELECT customer_id FROM sales WHERE sale_id = 'SALE-LOCK'"
    ).fetchone()
    assert int(row["customer_id"]) == ids["customer_1"]


def test_customer_change_is_allowed_without_linked_activity(
    sale_db: tuple[sqlite3.Connection, dict[str, int]],
) -> None:
    con, ids = sale_db
    repo = SalesRepo(con)
    repo.update_sale(
        _updated_header(ids["customer_2"]),
        _updated_items(ids),
    )

    row = con.execute(
        "SELECT customer_id FROM sales WHERE sale_id = 'SALE-LOCK'"
    ).fetchone()
    assert int(row["customer_id"]) == ids["customer_2"]


def test_same_customer_edit_remains_allowed_after_payment(
    sale_db: tuple[sqlite3.Connection, dict[str, int]],
) -> None:
    con, ids = sale_db
    _add_locking_activity(con, ids, "payment")
    repo = SalesRepo(con)
    repo.update_sale(
        _updated_header(ids["customer_1"]),
        _updated_items(ids),
    )

    payment_count = con.execute(
        "SELECT COUNT(*) FROM sale_payments WHERE sale_id = 'SALE-LOCK'"
    ).fetchone()[0]
    assert payment_count == 1
