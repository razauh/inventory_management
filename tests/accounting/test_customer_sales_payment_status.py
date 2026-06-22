"""Characterization tests for sale payment status rollup."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, SalePaymentStatus


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0,
            advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER,
            doc_type TEXT DEFAULT 'sale',
            source_type TEXT DEFAULT 'direct', source_id INTEGER,
            quotation_status TEXT, expiry_date TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT,
            product_id INTEGER, quantity REAL, uom_id INTEGER,
            unit_price REAL, item_discount REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sale_return_snapshots (
            transaction_id INTEGER PRIMARY KEY, sale_id TEXT,
            product_id INTEGER, uom_id INTEGER,
            returned_quantity REAL, return_value REAL,
            allocated_order_discount REAL, cogs_reversal_value REAL,
            return_date TEXT
        );
        CREATE VIEW IF NOT EXISTS sale_detailed_totals AS
        SELECT s.sale_id,
               CAST(s.order_discount AS REAL) AS order_discount,
               COALESCE((
                 SELECT SUM(CAST(si.quantity AS REAL) *
                   (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                 FROM sale_items si WHERE si.sale_id = s.sale_id
               ),0.0) AS subtotal_before_order_discount,
               COALESCE((
                 SELECT SUM(CAST(si.quantity AS REAL) *
                   (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                 FROM sale_items si WHERE si.sale_id = s.sale_id
               ),0.0) - CAST(s.order_discount AS REAL) AS calculated_total_amount,
               COALESCE((
                 SELECT SUM(CAST(srs.return_value AS REAL))
                 FROM sale_return_snapshots srs WHERE srs.sale_id = s.sale_id
               ),0.0) AS returned_value,
               MAX(0.0,
                 COALESCE((
                   SELECT SUM(CAST(si.quantity AS REAL) *
                     (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                   FROM sale_items si WHERE si.sale_id = s.sale_id
                 ),0.0) - CAST(s.order_discount AS REAL)
                 - COALESCE((
                   SELECT SUM(CAST(srs.return_value AS REAL))
                   FROM sale_return_snapshots srs WHERE srs.sale_id = s.sale_id
                 ),0.0)
               ) AS net_total_amount
        FROM sales s;
        CREATE VIEW IF NOT EXISTS sale_receivable_totals AS
        SELECT s.sale_id,
               MAX(0.0, CAST(sdt.net_total_amount AS REAL)) AS canonical_total_amount,
               MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0)) AS paid_amount,
               MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)) AS advance_payment_applied,
               MAX(0.0,
                 MAX(0.0, CAST(sdt.net_total_amount AS REAL))
                 - MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0))
                 - MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0))
               ) AS remaining_due
        FROM sales s
        JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id;
        """
    )


def _make_sale(conn, sale_id, total, paid=0, advance=0, status="unpaid"):
    conn.execute(
        """
        INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount,
                           payment_status, paid_amount, advance_payment_applied, doc_type)
        VALUES (?, 1, '2026-06-21', ?, 0, ?, ?, ?, 'sale')
        """,
        (sale_id, total, status, paid, advance),
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount) VALUES (?, 1, 1, 1, ?, 0)",
        (sale_id, total),
    )


def test_sale_payment_status_matches_header_rollup():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    # unpaid
    unpaid_id = "SO-UNPAID"
    _make_sale(conn, unpaid_id, 100)
    svc = AccountingService(conn)
    st = svc.get_sale_payment_status(unpaid_id)
    assert st.status == "unpaid"
    assert float(st.remaining_due) == 100
    assert float(st.paid_amount) == 0

    # partial
    partial_id = "SO-PARTIAL"
    _make_sale(conn, partial_id, 100, paid=40)
    st = svc.get_sale_payment_status(partial_id)
    assert st.status == "partial"

    # paid (fully paid by payment)
    paid_id = "SO-PAID"
    _make_sale(conn, paid_id, 100, paid=100)
    st = svc.get_sale_payment_status(paid_id)
    assert st.status == "paid"

    # paid by credit alone
    credit_id = "SO-CREDIT"
    _make_sale(conn, credit_id, 100, paid=0, advance=100)
    st = svc.get_sale_payment_status(credit_id)
    assert st.status == "paid"


def test_sale_payment_status_preserves_payment_and_credit_mix():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    # Mix of payment and credit, still has remaining
    sid = "SO-MIX"
    _make_sale(conn, sid, 100, paid=30, advance=20)
    svc = AccountingService(conn)
    st = svc.get_sale_payment_status(sid)
    assert st.status == "partial"
    assert float(st.remaining_due) == 50
    assert float(st.paid_amount) == 30
    assert float(st.applied_credit) == 20


def test_recalculate_sale_payment_status_preserves_sales_repo_behavior():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    from database.repositories.sales_repo import SalesRepo

    repo = SalesRepo(conn)
    svc = AccountingService(conn)

    sid = "SO-RECALC"
    _make_sale(conn, sid, 200)
    assert conn.execute(
        "SELECT payment_status FROM sales WHERE sale_id = ?", (sid,)
    ).fetchone()["payment_status"] == "unpaid"

    # Simulate payment recorded externally (trigger would normally update header)
    conn.execute(
        "UPDATE sales SET paid_amount = 80 WHERE sale_id = ?", (sid,)
    )
    # header status is stale — recalculate via service
    result = svc.recalculate_sale_payment_status(sid)
    assert result.status == "partial"
    row = conn.execute(
        "SELECT payment_status FROM sales WHERE sale_id = ?", (sid,)
    ).fetchone()
    assert row["payment_status"] == "partial"

    # Fully paid
    conn.execute(
        "UPDATE sales SET paid_amount = 200 WHERE sale_id = ?", (sid,)
    )
    result = svc.recalculate_sale_payment_status(sid)
    assert result.status == "paid"
    row = conn.execute(
        "SELECT payment_status FROM sales WHERE sale_id = ?", (sid,)
    ).fetchone()
    assert row["payment_status"] == "paid"

    # Back to unpaid
    conn.execute(
        "UPDATE sales SET paid_amount = 0 WHERE sale_id = ?", (sid,)
    )
    result = svc.recalculate_sale_payment_status(sid)
    assert result.status == "unpaid"
