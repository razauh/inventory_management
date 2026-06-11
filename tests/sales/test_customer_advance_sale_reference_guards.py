import sqlite3

import pytest

from inventory_management.database.schema import SQL


SALE_ID = "SO-CREDIT-GUARD"


@pytest.fixture()
def credit_guard_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_a = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer A', 'A')"
    ).lastrowid
    customer_b = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer B', 'B')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Credit Guard Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    for sale_id, customer_id, doc_type, quotation_status in (
        (SALE_ID, customer_a, "sale", None),
        ("SO-UNLINKED", customer_a, "sale", None),
        ("QT-CREDIT-GUARD", customer_a, "quotation", "draft"),
    ):
        conn.execute(
            """
            INSERT INTO sales (
                sale_id, customer_id, date, total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied,
                doc_type, quotation_status
            ) VALUES (?, ?, '2026-06-11', 100, 0, 'unpaid', 0, 0, ?, ?)
            """,
            (sale_id, customer_id, doc_type, quotation_status),
        )
        conn.execute(
            """
            INSERT INTO sale_items (
                sale_id, product_id, quantity, uom_id, unit_price, item_discount
            ) VALUES (?, ?, 1, ?, 100, 0)
            """,
            (sale_id, product_id, uom_id),
        )

    conn.execute(
        """
        INSERT INTO customer_advances (customer_id, amount, source_type)
        VALUES (?, 100, 'deposit')
        """,
        (customer_a,),
    )

    try:
        yield {
            "conn": conn,
            "customer_a": int(customer_a),
            "customer_b": int(customer_b),
        }
    finally:
        conn.close()


def _insert_linked_credit(db, source_type="applied_to_sale", source_id=SALE_ID):
    amount = -20 if source_type == "applied_to_sale" else 20
    return db["conn"].execute(
        """
        INSERT INTO customer_advances (
            customer_id, amount, source_type, source_id
        ) VALUES (?, ?, ?, ?)
        """,
        (db["customer_a"], amount, source_type, source_id),
    ).lastrowid


@pytest.mark.parametrize("source_type", ["applied_to_sale", "return_credit"])
def test_valid_sale_linked_credit_is_allowed(credit_guard_db, source_type):
    tx_id = _insert_linked_credit(credit_guard_db, source_type)

    row = credit_guard_db["conn"].execute(
        "SELECT source_type, source_id FROM customer_advances WHERE tx_id=?",
        (tx_id,),
    ).fetchone()
    assert row["source_type"] == source_type
    assert row["source_id"] == SALE_ID


@pytest.mark.parametrize("source_id", [None, "", "SO-MISSING"])
def test_sale_linked_credit_requires_existing_sale(credit_guard_db, source_id):
    with pytest.raises(sqlite3.IntegrityError, match="sale reference|Invalid sale"):
        _insert_linked_credit(credit_guard_db, "return_credit", source_id)


def test_sale_linked_credit_rejects_quotation(credit_guard_db):
    with pytest.raises(sqlite3.IntegrityError, match="Invalid sale"):
        _insert_linked_credit(credit_guard_db, "return_credit", "QT-CREDIT-GUARD")


def test_sale_linked_credit_rejects_wrong_customer(credit_guard_db):
    with pytest.raises(sqlite3.IntegrityError, match="Invalid sale or customer"):
        credit_guard_db["conn"].execute(
            """
            INSERT INTO customer_advances (
                customer_id, amount, source_type, source_id
            ) VALUES (?, 20, 'return_credit', ?)
            """,
            (credit_guard_db["customer_b"], SALE_ID),
        )


@pytest.mark.parametrize("source_type", ["applied_to_sale", "return_credit"])
def test_linked_credit_blocks_sale_delete(credit_guard_db, source_type):
    _insert_linked_credit(credit_guard_db, source_type)

    with pytest.raises(sqlite3.IntegrityError, match="Cannot delete a sale"):
        credit_guard_db["conn"].execute(
            "DELETE FROM sales WHERE sale_id=?", (SALE_ID,)
        )


@pytest.mark.parametrize("field,value", [("customer_id", None), ("sale_id", "SO-RENAMED")])
def test_linked_credit_blocks_sale_identity_changes(credit_guard_db, field, value):
    _insert_linked_credit(credit_guard_db, "return_credit")
    if field == "customer_id":
        value = credit_guard_db["customer_b"]

    with pytest.raises(sqlite3.IntegrityError, match="Cannot change a sale"):
        credit_guard_db["conn"].execute(
            f"UPDATE sales SET {field}=? WHERE sale_id=?", (value, SALE_ID)
        )


@pytest.mark.parametrize(
    "assignment,params",
    [
        ("customer_id=?", "customer_b"),
        ("source_type='deposit'", None),
        ("source_id='SO-UNLINKED'", None),
    ],
)
def test_linked_credit_identity_is_immutable(credit_guard_db, assignment, params):
    tx_id = _insert_linked_credit(credit_guard_db, "return_credit")
    values = []
    if params == "customer_b":
        values.append(credit_guard_db["customer_b"])
    values.append(tx_id)

    with pytest.raises(sqlite3.IntegrityError, match="Cannot change sale-linked"):
        credit_guard_db["conn"].execute(
            f"UPDATE customer_advances SET {assignment} WHERE tx_id=?", values
        )


def test_deposit_cannot_be_converted_into_sale_linked_credit(credit_guard_db):
    tx_id = credit_guard_db["conn"].execute(
        "SELECT tx_id FROM customer_advances WHERE source_type='deposit'"
    ).fetchone()["tx_id"]

    with pytest.raises(sqlite3.IntegrityError, match="Cannot change sale-linked"):
        credit_guard_db["conn"].execute(
            """
            UPDATE customer_advances
            SET source_type='return_credit', source_id=?
            WHERE tx_id=?
            """,
            (SALE_ID, tx_id),
        )


def test_unlinked_sale_and_deposit_do_not_create_lock(credit_guard_db):
    credit_guard_db["conn"].execute(
        "UPDATE sales SET customer_id=? WHERE sale_id='SO-UNLINKED'",
        (credit_guard_db["customer_b"],),
    )
    credit_guard_db["conn"].execute("DELETE FROM sales WHERE sale_id='SO-UNLINKED'")

    assert credit_guard_db["conn"].execute(
        "SELECT 1 FROM sales WHERE sale_id='SO-UNLINKED'"
    ).fetchone() is None
