import sqlite3

import pytest

from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService
from inventory_management.modules.vendor.controller import VendorController


def _setup_vendor_statement_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid

    def add_purchase(purchase_id, date, amount):
        conn.execute(
            """
            INSERT INTO purchases (
                purchase_id, vendor_id, date, total_amount, payment_status
            ) VALUES (?, ?, ?, ?, 'unpaid')
            """,
            (purchase_id, vendor_id, date, amount),
        )
        conn.execute(
            """
            INSERT INTO purchase_items (
                purchase_id, product_id, quantity, uom_id,
                purchase_price, sale_price, item_discount
            ) VALUES (?, ?, 1, ?, ?, ?, 0)
            """,
            (purchase_id, product_id, uom_id, amount, amount + 1),
        )

    add_purchase("PO-OPEN", "2026-05-01", 100)
    add_purchase("PO-IN", "2026-06-02", 50)
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, clearing_state
        ) VALUES ('PO-OPEN', '2026-05-15', 30, 'Cash', 'cleared')
        """
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type
        ) VALUES (?, '2026-05-18', 20, 'deposit')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id
        ) VALUES (?, '2026-06-03', 10, 'return_credit', 'PO-IN')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id
        ) VALUES (?, '2026-06-04', -5, 'applied_to_purchase', 'PO-IN')
        """,
        (vendor_id,),
    )
    return conn, vendor_id


def test_service_vendor_statement_matches_controller_payload():
    conn, vendor_id = _setup_vendor_statement_db()
    controller = VendorController.__new__(VendorController)
    controller.conn = conn
    controller.accounting = AccountingService(conn)

    assert AccountingService(conn).get_vendor_statement(
        vendor_id,
        "2026-06-01",
        "2026-06-30",
    ) == controller.build_vendor_statement(
        vendor_id,
        date_from="2026-06-01",
        date_to="2026-06-30",
    )
    conn.close()


def test_vendor_statement_preserves_opening_and_closing_balances():
    conn, vendor_id = _setup_vendor_statement_db()

    statement = AccountingService(conn).get_vendor_statement(
        vendor_id,
        "2026-06-01",
        "2026-06-30",
    )

    assert statement["opening_credit"] == pytest.approx(20.0)
    assert statement["opening_payable"] == pytest.approx(50.0)
    assert [(row["type"], row["doc_id"]) for row in statement["rows"]] == [
        ("Purchase", "PO-IN"),
        ("Credit Note", "PO-IN"),
        ("Credit Applied", "PO-IN"),
    ]
    assert statement["closing_balance"] == pytest.approx(100.0)
    assert statement["period"] == {"from": "2026-06-01", "to": "2026-06-30"}
    conn.close()


def test_vendor_statement_opening_credit_includes_return_credit_balance():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid

    # Pre-period deposit
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-05-10', 25.0, 'deposit')
        """,
        (vendor_id,),
    )

    # Pre-period return credit
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-05-15', 15.0, 'return_credit')
        """,
        (vendor_id,),
    )

    # Pre-period credit applied
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-05-20', -10.0, 'applied_to_purchase')
        """,
        (vendor_id,),
    )

    statement = AccountingService(conn).get_vendor_statement(
        vendor_id,
        "2026-06-01",
        "2026-06-30",
    )

    # Opening credit should be 25.0 + 15.0 - 10.0 = 30.0
    assert statement["opening_credit"] == pytest.approx(30.0)
    conn.close()


def test_vendor_statement_opening_credit_matches_vendor_balance_basis():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid

    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-05-10', 50.0, 'deposit')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-05-15', 30.0, 'return_credit')
        """,
        (vendor_id,),
    )

    # View balance matches before 2026-06-01
    service = AccountingService(conn)
    statement = service.get_vendor_statement(
        vendor_id,
        "2026-06-01",
        "2026-06-30",
    )

    view_balance = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS balance FROM vendor_advances WHERE vendor_id = ? AND DATE(tx_date) < '2026-06-01'",
        (vendor_id,),
    ).fetchone()["balance"]

    assert statement["opening_credit"] == pytest.approx(view_balance)
    conn.close()

