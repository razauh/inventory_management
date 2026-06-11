import sqlite3

import pytest

from inventory_management.database.repositories.dashboard_repo import DashboardRepo
from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import SQL, _backfill_sale_return_snapshots
from inventory_management.modules.sales.controller import SalesController


@pytest.fixture()
def sale_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "sale-return-receivables.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SQL)
    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Return Customer', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Return Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    try:
        yield conn, int(customer_id), int(product_id), int(uom_id)
    finally:
        conn.close()


def _create_sale(sale_db, *, sale_id="SAL-001", paid=0.0, advance=0.0):
    conn, customer_id, product_id, uom_id = sale_db
    repo = SalesRepo(conn)
    repo.create_sale(
        SaleHeader(
            sale_id=sale_id,
            customer_id=customer_id,
            date="2026-06-11",
            total_amount=100.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=advance,
            notes=None,
            created_by=None,
        ),
        [SaleItem(None, sale_id, product_id, 10.0, uom_id, 10.0, 0.0)],
    )
    if paid:
        conn.execute(
            """
            INSERT INTO sale_payments (
                sale_id, date, amount, method, instrument_type, clearing_state
            ) VALUES (?, '2026-06-11', ?, 'Cash', 'other', 'cleared')
            """,
            (sale_id, paid),
        )
    item_id = int(repo.list_items(sale_id)[0]["item_id"])
    return repo, item_id


def _return(repo, item_id, qty, *, cash=0.0):
    item = repo.conn.execute(
        "SELECT product_id, uom_id FROM sale_items WHERE item_id=?",
        (item_id,),
    ).fetchone()
    return repo.record_return(
        sid="SAL-001",
        date="2026-06-11",
        created_by=None,
        lines=[{
            "item_id": item_id,
            "product_id": int(item["product_id"]),
            "uom_id": int(item["uom_id"]),
            "qty_return": qty,
        }],
        notes="[Return]",
        settlement={"cash_refund": cash},
    )


def test_partial_payment_return_reduces_ar_before_settlement(sale_db):
    conn, *_ = sale_db
    repo, item_id = _create_sale(sale_db, paid=60.0)
    result = _return(repo, item_id, 3.0, cash=30.0)

    assert result["return_value"] == pytest.approx(30.0)
    assert result["cash_refund"] == pytest.approx(0.0)
    assert result["credit_amount"] == pytest.approx(0.0)
    assert result["net_total_amount"] == pytest.approx(70.0)
    assert result["remaining_due_after_return"] == pytest.approx(10.0)
    assert result["payment_status"] == "partial"
    assert conn.execute("SELECT COUNT(*) FROM customer_advances").fetchone()[0] == 0


def test_unpaid_sale_return_only_reduces_receivable(sale_db):
    repo, item_id = _create_sale(sale_db)
    result = _return(repo, item_id, 3.0)

    assert result["net_total_amount"] == pytest.approx(70.0)
    assert result["remaining_due_after_return"] == pytest.approx(70.0)
    assert result["settlement_due"] == pytest.approx(0.0)
    assert result["payment_status"] == "unpaid"


def test_fully_paid_return_can_refund_cash(sale_db):
    conn, *_ = sale_db
    repo, item_id = _create_sale(sale_db, paid=100.0)
    result = _return(repo, item_id, 3.0, cash=30.0)

    assert result["cash_refund"] == pytest.approx(30.0)
    assert result["credit_amount"] == pytest.approx(0.0)
    assert float(conn.execute("SELECT paid_amount FROM sales WHERE sale_id='SAL-001'").fetchone()[0]) == pytest.approx(70.0)
    assert result["remaining_due_after_return"] == pytest.approx(0.0)


def test_fully_paid_return_can_create_customer_credit(sale_db):
    conn, customer_id, *_ = sale_db
    repo, item_id = _create_sale(sale_db, paid=100.0)
    result = _return(repo, item_id, 3.0)

    credit = conn.execute(
        "SELECT customer_id, amount FROM customer_advances WHERE source_type='return_credit'"
    ).fetchone()
    assert result["credit_amount"] == pytest.approx(30.0)
    assert int(credit["customer_id"]) == customer_id
    assert float(credit["amount"]) == pytest.approx(30.0)


def test_full_paid_sale_full_return_closes_at_zero(sale_db):
    conn, *_ = sale_db
    repo, item_id = _create_sale(sale_db, paid=100.0)
    result = _return(repo, item_id, 10.0, cash=100.0)

    assert result["net_total_amount"] == pytest.approx(0.0)
    assert result["remaining_due_after_return"] == pytest.approx(0.0)
    assert result["payment_status"] == "paid"
    assert float(conn.execute("SELECT paid_amount FROM sales WHERE sale_id='SAL-001'").fetchone()[0]) == pytest.approx(0.0)


def test_repeated_partial_returns_use_snapshot_totals(sale_db):
    repo, item_id = _create_sale(sale_db)
    _return(repo, item_id, 2.0)
    _return(repo, item_id, 3.0)

    totals = repo.get_receivable_position("SAL-001")
    assert totals["gross_total_amount"] == pytest.approx(100.0)
    assert totals["returned_value"] == pytest.approx(50.0)
    assert totals["net_total_amount"] == pytest.approx(50.0)
    assert totals["remaining_due"] == pytest.approx(50.0)


def test_sale_return_snapshots_are_immutable_and_block_sale_edits(sale_db):
    conn, customer_id, product_id, uom_id = sale_db
    repo, item_id = _create_sale(sale_db)
    _return(repo, item_id, 2.0)
    transaction_id = conn.execute(
        "SELECT transaction_id FROM sale_return_snapshots WHERE sale_id='SAL-001'"
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="snapshots are immutable"):
        conn.execute(
            "UPDATE sale_return_snapshots SET return_value=999 WHERE transaction_id=?",
            (transaction_id,),
        )
    with pytest.raises(ValueError, match="Cannot edit a sale after returns exist"):
        repo.update_sale(
            SaleHeader("SAL-001", customer_id, "2026-06-11", 100.0, 0.0, "unpaid", 0.0, 0.0, None, None),
            [SaleItem(item_id, "SAL-001", product_id, 10.0, uom_id, 12.0, 0.0)],
        )


def test_legacy_sale_return_backfill_uses_stored_sale_terms(sale_db):
    conn, _, product_id, uom_id = sale_db
    repo, item_id = _create_sale(sale_db)
    conn.execute("DROP TRIGGER trg_sale_return_snapshot_insert")
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 2, ?, 'sale_return', 'sales', 'SAL-001', ?, '2026-06-11')
        """,
        (product_id, uom_id, item_id),
    )

    _backfill_sale_return_snapshots(conn)
    snapshot = conn.execute(
        "SELECT unit_sale_price, unit_discount, return_value FROM sale_return_snapshots"
    ).fetchone()
    assert float(snapshot["unit_sale_price"]) == pytest.approx(10.0)
    assert float(snapshot["unit_discount"]) == pytest.approx(0.0)
    assert float(snapshot["return_value"]) == pytest.approx(20.0)
    assert repo.get_receivable_position("SAL-001")["net_total_amount"] == pytest.approx(80.0)


def test_dashboard_and_sales_financials_use_net_remaining(sale_db):
    conn, *_ = sale_db
    repo, item_id = _create_sale(sale_db, paid=40.0)
    _return(repo, item_id, 3.0)

    controller = SalesController.__new__(SalesController)
    controller.conn = conn
    assert controller._fetch_sale_financials("SAL-001")["remaining_due"] == pytest.approx(30.0)
    assert DashboardRepo(conn).open_receivables() == pytest.approx(30.0)
