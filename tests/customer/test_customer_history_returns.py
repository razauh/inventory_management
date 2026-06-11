import sqlite3

from inventory_management.database.schema import SQL
from inventory_management.modules.customer.history import CustomerHistoryService


def test_sale_returns_include_item_and_prorated_value(tmp_path):
    db_path = tmp_path / "customer-history-returns.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SQL)
    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Customer', 'Contact')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Widget')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    conn.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, doc_type
        ) VALUES ('SALE-RETURN', ?, '2026-06-11', 90, 10, 'unpaid', 0, 0, 'sale')
        """,
        (customer_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO sale_items (
            sale_id, product_id, quantity, uom_id, unit_price, item_discount
        ) VALUES ('SALE-RETURN', ?, 2, ?, 50, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type, reference_table,
            reference_id, reference_item_id, date, txn_seq, notes
        ) VALUES (?, 1, ?, 'sale_return', 'sales', 'SALE-RETURN', ?, '2026-06-12', 10, '[Return]')
        """,
        (product_id, uom_id, item_id),
    )
    conn.commit()
    conn.close()

    returned = CustomerHistoryService(db_path).sale_returns(customer_id)

    assert len(returned) == 1
    assert returned[0]["sale_id"] == "SALE-RETURN"
    assert returned[0]["product_name"] == "Widget"
    assert returned[0]["quantity"] == 1.0
    assert returned[0]["uom_name"] == "Piece"
    assert returned[0]["amount"] == -45.0
