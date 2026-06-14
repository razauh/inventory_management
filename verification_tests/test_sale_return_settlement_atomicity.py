import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def sale_db(tmp_path):
    db_path = tmp_path / "sale-return-atomicity.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Return Customer', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Return Product')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 100.0, ?, 'adjustment', NULL, NULL, NULL, '2026-06-11', 1)
        """,
        (product_id, uom_id),
    )
    from inventory_management.database.repositories.inventory_repo import rebuild_dirty_valuations
    rebuild_dirty_valuations(conn)

    repo = SalesRepo(conn)
    repo.create_sale(
        SaleHeader(
            sale_id="SO-RETURN-ATOMIC",
            customer_id=int(customer_id),
            date="2026-06-11",
            total_amount=100,
            order_discount=0,
            payment_status="unpaid",
            paid_amount=0,
            advance_payment_applied=0,
            notes=None,
            created_by=None,
        ),
        [
            SaleItem(
                item_id=None,
                sale_id="SO-RETURN-ATOMIC",
                product_id=int(product_id),
                quantity=10,
                uom_id=int(uom_id),
                unit_price=10,
                item_discount=0,
            )
        ],
    )
    item_id = conn.execute(
        "SELECT item_id FROM sale_items WHERE sale_id = 'SO-RETURN-ATOMIC'"
    ).fetchone()["item_id"]

    try:
        yield conn, repo, int(customer_id), int(product_id), int(uom_id), int(item_id)
    finally:
        conn.close()


def _return_lines(product_id, uom_id, item_id, quantity):
    return [
        {
            "item_id": item_id,
            "product_id": product_id,
            "uom_id": uom_id,
            "qty_return": quantity,
        }
    ]


def test_split_return_settlement_commits_inventory_refund_and_credit_together(sale_db):
    conn, repo, customer_id, product_id, uom_id, item_id = sale_db
    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, clearing_state
        ) VALUES ('SO-RETURN-ATOMIC', '2026-06-11', 100, 'Cash', 'other', 'cleared')
        """
    )

    repo.record_return(
        sid="SO-RETURN-ATOMIC",
        date="2026-06-11",
        created_by=None,
        lines=_return_lines(product_id, uom_id, item_id, 4),
        notes="[Return]",
        settlement={"cash_refund": 25, "credit_amount": 15},
    )

    returned = conn.execute(
        "SELECT SUM(quantity) AS qty FROM inventory_transactions WHERE transaction_type = 'sale_return'"
    ).fetchone()["qty"]
    refund = conn.execute(
        "SELECT amount FROM sale_payments WHERE amount < 0"
    ).fetchone()["amount"]
    credit = conn.execute(
        """
        SELECT customer_id, amount, source_type, source_id
        FROM customer_advances
        WHERE source_type = 'return_credit'
        """
    ).fetchone()

    assert float(returned) == pytest.approx(4)
    assert float(refund) == pytest.approx(-25)
    assert int(credit["customer_id"]) == customer_id
    assert float(credit["amount"]) == pytest.approx(15)
    assert credit["source_id"] == "SO-RETURN-ATOMIC"


def test_credit_failure_rolls_back_inventory_return(sale_db):
    conn, repo, _, product_id, uom_id, item_id = sale_db
    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, clearing_state
        ) VALUES ('SO-RETURN-ATOMIC', '2026-06-11', 100, 'Cash', 'other', 'cleared')
        """
    )
    conn.execute(
        """
        CREATE TRIGGER fail_return_credit
        BEFORE INSERT ON customer_advances
        WHEN NEW.source_type = 'return_credit'
        BEGIN
            SELECT RAISE(ABORT, 'forced return credit failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced return credit failure"):
        repo.record_return(
            sid="SO-RETURN-ATOMIC",
            date="2026-06-11",
            created_by=None,
            lines=_return_lines(product_id, uom_id, item_id, 2),
            notes="[Return]",
            settlement={"cash_refund": 0, "credit_amount": 20},
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM inventory_transactions WHERE transaction_type = 'sale_return'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM customer_advances").fetchone()[0] == 0


def test_refund_failure_rolls_back_inventory_return(sale_db):
    conn, repo, _, product_id, uom_id, item_id = sale_db
    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, clearing_state
        ) VALUES ('SO-RETURN-ATOMIC', '2026-06-11', 100, 'Cash', 'other', 'cleared')
        """
    )
    conn.execute(
        """
        CREATE TRIGGER fail_return_refund
        BEFORE INSERT ON sale_payments
        WHEN NEW.amount < 0
        BEGIN
            SELECT RAISE(ABORT, 'forced return refund failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced return refund failure"):
        repo.record_return(
            sid="SO-RETURN-ATOMIC",
            date="2026-06-11",
            created_by=None,
            lines=_return_lines(product_id, uom_id, item_id, 2),
            notes="[Return]",
            settlement={"cash_refund": 20, "credit_amount": 0},
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM inventory_transactions WHERE transaction_type = 'sale_return'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sale_payments WHERE amount < 0").fetchone()[0] == 0
