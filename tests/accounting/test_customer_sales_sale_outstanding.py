"""Characterization tests for sale outstanding / receivable position."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import (
    AccountingService,
    SaleFinancialSummary,
    SaleOutstanding,
)


def _build_sale_fixture(conn) -> str:
    """Create a minimal sale with a payment, return its sale_id."""
    cur = conn.execute("SELECT MAX(CAST(SUBSTR(sale_id, 11) AS INTEGER)) FROM sales")
    max_seq = (cur.fetchone() or (0,))[0] or 0
    sid = f"SO20000101-{max_seq + 1:04d}"

    conn.execute(
        """
        INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount,
                           payment_status, paid_amount, advance_payment_applied, doc_type)
        VALUES (?, 1, '2026-06-21', 18.0, 2.0, 'partial', 5.0, 0.0, 'sale')
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
        UPDATE sales SET paid_amount = 5.0, payment_status = 'partial' WHERE sale_id = ?
        """,
        (sid,),
    )
    return sid


def _ensure_views(conn):
    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS sale_detailed_totals AS
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
    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS sale_receivable_totals AS
        SELECT
          s.sale_id,
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


def test_sale_outstanding_matches_receivable_view():
    conn = connect(":memory:")
    conn.row_factory = None
    conn.executescript(
        """
        CREATE TABLE sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0, advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER, doc_type TEXT DEFAULT 'sale',
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
            allocated_order_discount REAL, cogs_reversal_value REAL,
            return_date TEXT
        );
        """
    )
    _ensure_views(conn)
    sid = _build_sale_fixture(conn)

    conn.row_factory = SqliteRow
    view_row = conn.execute(
        "SELECT * FROM sale_receivable_totals WHERE sale_id = ?", (sid,)
    ).fetchone()
    assert view_row

    svc = AccountingService(conn)
    result = svc.get_sale_outstanding(sid)

    assert float(result.outstanding) == float(view_row["remaining_due"])


def test_sale_financial_summary_matches_sales_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript(
        """
        CREATE TABLE sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0, advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER, doc_type TEXT DEFAULT 'sale',
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
            allocated_order_discount REAL, cogs_reversal_value REAL,
            return_date TEXT
        );
        """
    )
    _ensure_views(conn)
    sid = _build_sale_fixture(conn)

    from database.repositories.sales_repo import SalesRepo
    repo = SalesRepo(conn)
    repo_position = repo.get_receivable_position(sid)

    svc = AccountingService(conn)
    fin = svc.get_sale_financial_summary(sid)

    assert float(fin.gross_total_amount) == repo_position["gross_total_amount"]
    assert float(fin.returned_value) == repo_position["returned_value"]
    assert float(fin.net_total) == repo_position["net_total_amount"]
    assert float(fin.paid_amount) == repo_position["paid_amount"]
    assert float(fin.applied_credit) == repo_position["advance_payment_applied"]
    assert float(fin.outstanding) == repo_position["remaining_due"]
