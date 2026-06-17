import sqlite3
from types import SimpleNamespace

from inventory_management.database.schema import SQL
from inventory_management.database.repositories.sales_repo import SalesRepo
from inventory_management.modules.sales.controller import SalesController, SalesStatusProxy
from inventory_management.modules.sales.model import SalesTableModel


def _sales_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.execute(
        "INSERT INTO customers (customer_id, name, contact_info) VALUES (1, 'Alpha Customer', '')"
    )
    conn.execute(
        "INSERT INTO customers (customer_id, name, contact_info) VALUES (2, 'Beta Customer', '')"
    )
    return conn


def _insert_sale(
    conn: sqlite3.Connection,
    sale_id: str,
    *,
    customer_id: int = 1,
    status: str = "unpaid",
    doc_type: str = "sale",
    quotation_status: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied,
            doc_type, quotation_status
        ) VALUES (?, ?, '2026-06-11', 10.0, 0.0, ?, 0.0, 0.0, ?, ?)
        """,
        (sale_id, customer_id, status, doc_type, quotation_status),
    )


def test_list_sales_defaults_to_recent_slice_limit():
    conn = _sales_db()
    try:
        repo = SalesRepo(conn)
        for idx in range(SalesRepo.DEFAULT_LIST_LIMIT + 5):
            _insert_sale(conn, f"SO-LIMIT-{idx:04d}")

        rows = repo.list_sales()

        assert len(rows) == SalesRepo.DEFAULT_LIST_LIMIT
    finally:
        conn.close()


def test_search_sales_paginates_and_counts_matching_rows():
    conn = _sales_db()
    try:
        repo = SalesRepo(conn)
        for idx in range(3):
            _insert_sale(conn, f"SO-ALPHA-{idx}", customer_id=1)
        for idx in range(2):
            _insert_sale(conn, f"SO-BETA-{idx}", customer_id=2)

        rows = repo.search_sales("Customer", limit=2, offset=2)

        assert repo.count_sales("Customer") == 5
        assert len(rows) == 2
    finally:
        conn.close()


def test_sales_status_filter_is_sql_backed():
    conn = _sales_db()
    try:
        repo = SalesRepo(conn)
        _insert_sale(conn, "SO-UNPAID", status="unpaid")
        _insert_sale(conn, "SO-PAID", status="paid")
        _insert_sale(conn, "SO-PARTIAL", status="partial")

        rows = repo.search_sales(status="paid", limit=10)

        assert [row["sale_id"] for row in rows] == ["SO-PAID"]
        assert repo.count_sales(status="paid") == 1
    finally:
        conn.close()


def test_quotation_status_filter_is_sql_backed():
    conn = _sales_db()
    try:
        repo = SalesRepo(conn)
        _insert_sale(
            conn,
            "QO-DRAFT",
            doc_type="quotation",
            quotation_status="draft",
        )
        _insert_sale(
            conn,
            "QO-SENT",
            doc_type="quotation",
            quotation_status="sent",
        )

        rows = repo.search_sales(doc_type="quotation", status="sent", limit=10)

        assert [row["sale_id"] for row in rows] == ["QO-SENT"]
        assert repo.count_sales(doc_type="quotation", status="sent") == 1
    finally:
        conn.close()


def test_build_model_fetches_one_server_page(app):
    rows = [
        {
            "sale_id": "SO-PAGE",
            "date": "2026-06-11",
            "customer_id": 1,
            "customer_name": "Alpha Customer",
            "total_amount": 10.0,
            "order_discount": 0.0,
            "paid_amount": 0.0,
            "payment_status": "unpaid",
            "doc_type": "sale",
            "quotation_status": None,
            "notes": None,
            "source_type": "direct",
            "source_id": None,
        }
    ]
    calls: list[tuple[str, str, str, int, int]] = []

    controller = SalesController.__new__(SalesController)
    controller._search_text = "needle"
    controller._doc_type = "sale"
    controller._status_filter = "unpaid"
    controller._page_offset = 100
    controller._total_sales = 0
    controller._table_initialized = True
    controller.repo = SimpleNamespace(
        count_sales=lambda query, doc_type, status: 150,
        search_sales=lambda query, doc_type, status, limit, offset: calls.append(
            (query, doc_type, status, limit, offset)
        )
        or rows,
    )
    controller.base = SalesTableModel([], doc_type="sale")
    controller.proxy = SalesStatusProxy()
    controller.proxy.setSourceModel(controller.base)
    controller.view = SimpleNamespace(
        tbl=SimpleNamespace(resizeColumnsToContents=lambda: None),
        lbl_page=SimpleNamespace(setText=lambda text: None),
        btn_prev_page=SimpleNamespace(setEnabled=lambda enabled: None),
        btn_next_page=SimpleNamespace(setEnabled=lambda enabled: None),
    )

    controller._build_model()

    assert controller.base.rowCount() == 1
    assert calls == [("needle", "sale", "unpaid", controller.PAGE_SIZE, 100)]


def test_sales_search_reload_resets_to_first_page():
    reload_offsets: list[int] = []

    controller = SalesController.__new__(SalesController)
    controller._page_offset = 200
    controller._search_text = ""
    controller._reload = lambda: reload_offsets.append(controller._page_offset)

    controller._run_search_reload()

    assert reload_offsets == [0]


def test_sales_status_filter_resets_to_first_page():
    reload_offsets: list[int] = []

    controller = SalesController.__new__(SalesController)
    controller._page_offset = 200
    controller._status_filter = "all"
    controller.proxy = SimpleNamespace()
    controller.view = SimpleNamespace(
        status_filter=SimpleNamespace(
            currentData=lambda: "paid",
            currentText=lambda: "Paid",
        )
    )
    controller._reload = lambda: reload_offsets.append(controller._page_offset)
    controller._update_filter_summary = lambda: None

    controller._on_status_filter_changed(0)

    assert controller._status_filter == "paid"
    assert reload_offsets == [0]


def test_sales_next_and_prev_page_move_by_page_size():
    reload_offsets: list[int] = []

    controller = SalesController.__new__(SalesController)
    controller._page_offset = 0
    controller._total_sales = 250
    controller._reload = lambda: reload_offsets.append(controller._page_offset)

    controller._next_page()
    controller._prev_page()

    assert reload_offsets == [controller.PAGE_SIZE, 0]
