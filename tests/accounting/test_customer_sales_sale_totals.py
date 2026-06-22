"""Characterization tests for sale totals consolidation."""

from decimal import Decimal
from sqlite3 import connect

from modules.accounting import (
    AccountingService,
    SaleTotalInputLine,
    SaleTotals,
)


def _build_sale_fixture(conn) -> str:
    """Create a minimal sale with items and returns, return its sale_id."""
    conn.row_factory = None
    cur = conn.execute("SELECT MAX(CAST(SUBSTR(sale_id, 11) AS INTEGER)) FROM sales")
    max_seq = (cur.fetchone() or (0,))[0] or 0
    sid = f"SO20000101-{max_seq + 1:04d}"

    conn.execute(
        """
        INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount,
                           payment_status, paid_amount, advance_payment_applied, doc_type)
        VALUES (?, 1, '2026-06-21', 0.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')
        """,
        (sid,),
    )
    conn.execute(
        """
        INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
        VALUES (?, 1, 2.0, 1, 10.0, 1.0)
        """,
        (sid,),
    )
    conn.execute(
        """
        INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
        VALUES (?, 1, 1.0, 1, 20.0, 0.0)
        """,
        (sid,),
    )
    # Update total_amount to match calculated value
    conn.execute(
        "UPDATE sales SET total_amount = 38.0, order_discount = 2.0 WHERE sale_id = ?",
        (sid,),
    )
    return sid


def test_sale_totals_match_current_view():
    conn = connect(":memory:")
    try:
        from database.schema import apply_migrations
        apply_migrations(conn)
    except ImportError:
        conn.executescript(
            """
            CREATE TABLE sales (
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
            CREATE TABLE sale_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT,
                product_id INTEGER, quantity REAL, uom_id INTEGER,
                unit_price REAL, item_discount REAL DEFAULT 0
            );
            CREATE TABLE sale_return_snapshots (
                transaction_id INTEGER PRIMARY KEY, sale_id TEXT,
                product_id INTEGER, uom_id INTEGER,
                returned_quantity REAL, return_value REAL,
                allocated_order_discount REAL,
                cogs_reversal_value REAL, return_date TEXT
            );
            CREATE VIEW sale_detailed_totals AS
            SELECT s.sale_id,
                   CAST(s.order_discount AS REAL) AS order_discount,
                   COALESCE((
                     SELECT SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                     FROM sale_items si WHERE si.sale_id = s.sale_id
                   ),0.0) AS subtotal_before_order_discount,
                   COALESCE((
                     SELECT SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                     FROM sale_items si WHERE si.sale_id = s.sale_id
                   ),0.0) - CAST(s.order_discount AS REAL) AS calculated_total_amount,
                   COALESCE((
                     SELECT SUM(CAST(srs.return_value AS REAL))
                     FROM sale_return_snapshots srs WHERE srs.sale_id = s.sale_id
                   ),0.0) AS returned_value,
                   MAX(0.0,
                     COALESCE((
                       SELECT SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                       FROM sale_items si WHERE si.sale_id = s.sale_id
                     ),0.0) - CAST(s.order_discount AS REAL)
                     - COALESCE((
                       SELECT SUM(CAST(srs.return_value AS REAL))
                       FROM sale_return_snapshots srs WHERE srs.sale_id = s.sale_id
                     ),0.0)
                   ) AS net_total_amount
            FROM sales s;
            """
        )

    conn.row_factory = None
    sid = _build_sale_fixture(conn)
    conn.row_factory = __import__("sqlite3").Row

    view_row = conn.execute(
        "SELECT * FROM sale_detailed_totals WHERE sale_id = ?", (sid,)
    ).fetchone()
    assert view_row, "Sale must exist in view"

    svc = AccountingService(conn)
    result = svc.get_sale_totals(sid)

    assert float(result.subtotal_before_order_discount) == float(
        view_row["subtotal_before_order_discount"]
    )
    assert float(result.order_discount) == float(view_row["order_discount"])
    assert float(result.returned_value) == float(view_row["returned_value"] or 0)
    assert float(result.net_total) == float(view_row["net_total_amount"])
    assert float(result.stored_total) == float(view_row["calculated_total_amount"])


def test_sale_totals_preserve_item_and_order_discount_behavior():
    items = (
        SaleTotalInputLine(quantity=Decimal("2"), unit_price=Decimal("10"), item_discount=Decimal("1")),
        SaleTotalInputLine(quantity=Decimal("1"), unit_price=Decimal("20"), item_discount=Decimal("0")),
    )
    result = AccountingService().preview_sale_total(items, Decimal("2"))

    # sub_raw = 2*10 + 1*20 = 40
    assert float(result.subtotal_before_order_discount) == 40.0
    # line_disc = 2*1 + 1*0 = 2
    # net = 40 - 2 = 38
    # total = 38 - 2 = 36
    assert float(result.order_discount) == 2.0
    assert float(result.net_total) == 36.0
    assert result.returned_value == Decimal("0")
    assert result.sale_id is None
    assert float(result.stored_total) == 36.0


def test_sales_repo_routes_sale_totals_through_accounting_service():
    from database.repositories.sales_repo import SalesRepo

    conn = connect(":memory:")
    try:
        from database.schema import apply_migrations
        apply_migrations(conn)
    except ImportError:
        conn.executescript(
            """
            CREATE TABLE sales (
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
            CREATE TABLE sale_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT,
                product_id INTEGER, quantity REAL, uom_id INTEGER,
                unit_price REAL, item_discount REAL DEFAULT 0
            );
            CREATE TABLE sale_receivable_totals AS SELECT * FROM (
                SELECT 'dummy' AS sale_id, 0.0 AS canonical_total_amount,
                       0.0 AS paid_amount, 0.0 AS advance_payment_applied,
                       0.0 AS remaining_due WHERE 0
            );
            CREATE TABLE customer_advances (
                advance_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER,
                tx_date TEXT, amount REAL, source_type TEXT, source_id TEXT,
                notes TEXT, created_by INTEGER
            );
            CREATE TABLE inventory_transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER,
                quantity REAL, uom_id INTEGER, transaction_type TEXT,
                reference_table TEXT, reference_id TEXT, reference_item_id INTEGER,
                date TEXT, txn_seq INTEGER, notes TEXT, created_by INTEGER
            );
            """
        )
    conn.row_factory = __import__("sqlite3").Row

    repo = SalesRepo(conn)
    assert repo.accounting is not None
    assert isinstance(repo.accounting, AccountingService)
