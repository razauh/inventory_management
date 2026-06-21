import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from inventory_management.database.schema import SQL
from inventory_management.database.repositories.sales_repo import SalesRepo
from inventory_management.modules.sales.controller import SalesController, SalesStatusProxy
from inventory_management.modules.sales.model import SalesTableModel


class _ButtonStub:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setToolTip(self, text):
        self.tooltip = text


class _LabelStub:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


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

    class ProxyShouldStayIdle(SalesStatusProxy):
        def set_status_filter(self, status: str):
            raise AssertionError("status filter should be SQL-backed")

    controller = SalesController.__new__(SalesController)
    controller._page_offset = 200
    controller._status_filter = "all"
    controller.proxy = ProxyShouldStayIdle()
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


def test_sales_table_model_indexes_rows_by_sale_id():
    model = SalesTableModel(
        [
            {"sale_id": "SO-1", "date": "", "customer_name": "", "total_amount": 0, "paid_amount": 0, "payment_status": "unpaid"},
            {"sale_id": "SO-2", "date": "", "customer_name": "", "total_amount": 0, "paid_amount": 0, "payment_status": "paid"},
        ]
    )

    assert model.row_for_sale_id("SO-2") == 1
    assert model.row_for_sale_id("SO-MISSING") is None

    model.replace(
        [
            {"sale_id": "SO-3", "date": "", "customer_name": "", "total_amount": 0, "paid_amount": 0, "payment_status": "unpaid"}
        ]
    )

    assert model.row_for_sale_id("SO-2") is None
    assert model.row_for_sale_id("SO-3") == 0


def test_select_row_by_sale_id_uses_model_row_map(app):
    selected_rows: list[int] = []
    scroll_rows: list[int] = []

    class ProxyNoLoop(SalesStatusProxy):
        def rowCount(self, parent=None):
            raise AssertionError("restore should not scan proxy rows")

    controller = SalesController.__new__(SalesController)
    controller.base = SalesTableModel(
        [
            {"sale_id": "SO-1", "date": "", "customer_name": "", "total_amount": 0, "paid_amount": 0, "payment_status": "unpaid"},
            {"sale_id": "SO-2", "date": "", "customer_name": "", "total_amount": 0, "paid_amount": 0, "payment_status": "paid"},
        ]
    )
    controller.proxy = ProxyNoLoop()
    controller.proxy.setSourceModel(controller.base)
    controller.view = SimpleNamespace(
        tbl=SimpleNamespace(
            selectRow=lambda row: selected_rows.append(row),
            scrollTo=lambda index: scroll_rows.append(index.row()),
        )
    )

    assert controller._select_row_by_sale_id("SO-2") is True
    assert selected_rows == [1]
    assert scroll_rows == [1]
    assert controller._select_row_by_sale_id("SO-MISSING") is False


def test_sales_selection_defers_detail_queries():
    starts: list[bool] = []

    controller = SalesController.__new__(SalesController)
    controller._doc_type = "sale"
    controller._detail_request_token = 0
    controller._selected_row = lambda: {
        "sale_id": "SO-DEFER",
        "customer_id": 1,
        "payment_status": "unpaid",
    }
    controller._detail_timer = SimpleNamespace(start=lambda: starts.append(True))
    controller.repo = SimpleNamespace(
        get_sale_detail_snapshot=lambda sale_id: (_ for _ in ()).throw(
            AssertionError("selection should defer detail query")
        )
    )
    controller.view = SimpleNamespace(
        btn_edit=_ButtonStub(),
        btn_print=_ButtonStub(),
        btn_return=_ButtonStub(),
        lbl_return_eligibility=_LabelStub(),
        btn_record_payment=_ButtonStub(),
        btn_apply_credit=_ButtonStub(),
        btn_convert=_ButtonStub(),
    )

    controller._on_selection_changed()

    assert starts == [True]
    assert controller.view.btn_return.enabled is False
    assert controller.view.lbl_return_eligibility.text == "Return eligibility loading."


def test_sales_sync_details_uses_single_snapshot():
    snapshot_calls: list[str] = []
    item_rows: list[list[dict]] = []
    payment_rows: list[list[dict]] = []
    detail_payloads: list[dict] = []

    class RepoStub:
        def get_sale_detail_snapshot(self, sale_id):
            snapshot_calls.append(sale_id)
            return {
                "header": {
                    "sale_id": sale_id,
                    "customer_id": 1,
                    "customer_name": "Alpha Customer",
                    "order_discount": 1.0,
                    "total_amount": 20.0,
                    "paid_amount": 5.0,
                    "doc_type": "sale",
                },
                "items": [
                    {
                        "item_id": 1,
                        "sale_id": sale_id,
                        "product_id": 1,
                        "product_name": "Widget",
                        "quantity": 2.0,
                        "uom_id": 1,
                        "unit_name": "Piece",
                        "unit_price": 10.0,
                        "item_discount": 1.0,
                    }
                ],
                "summary": {
                    "returned_qty": 0.0,
                    "returned_value": 0.0,
                    "gross_total_amount": 20.0,
                    "net_total_amount": 18.0,
                    "paid_amount": 5.0,
                    "advance_payment_applied": 0.0,
                    "calculated_total_amount": 18.0,
                    "remaining_due": 13.0,
                },
                "payments": [{"payment_id": 1, "sale_id": sale_id, "amount": 5.0}],
                "customer_credit_balance": 20.0,
                "returnable_lines": 1,
            }

        def list_items(self, sale_id):
            raise AssertionError("items must come from detail snapshot")

        def get_sale_detail_summary(self, sale_id):
            raise AssertionError("summary must come from detail snapshot")

    controller = SalesController.__new__(SalesController)
    controller._doc_type = "sale"
    controller._last_detail_key = None
    controller._detail_request_token = 1
    controller._selected_row = lambda: {
        "sale_id": "SO-SNAPSHOT",
        "customer_id": 1,
        "customer_name": "Alpha Customer",
        "order_discount": 1.0,
        "total_amount": 20.0,
    }
    controller.repo = RepoStub()
    controller.view = SimpleNamespace(
        items=SimpleNamespace(set_rows=lambda rows: item_rows.append(rows)),
        payments=SimpleNamespace(set_rows=lambda rows: payment_rows.append(rows)),
        details=SimpleNamespace(
            set_mode=lambda mode: None,
            set_data=lambda payload: detail_payloads.append(payload),
        ),
        btn_edit=_ButtonStub(),
        btn_print=_ButtonStub(),
        btn_return=_ButtonStub(),
        lbl_return_eligibility=_LabelStub(),
        btn_record_payment=_ButtonStub(),
        btn_apply_credit=_ButtonStub(),
        btn_convert=_ButtonStub(),
    )

    controller._sync_details_impl(token=1)

    assert snapshot_calls == ["SO-SNAPSHOT"]
    assert len(item_rows[0]) == 1
    assert payment_rows[0][0]["payment_id"] == 1
    assert detail_payloads[0]["remaining_due"] == 13.0
    assert controller.view.btn_return.enabled is True
    assert controller.view.btn_apply_credit.enabled is True


def test_sale_invoice_render_has_template_item_fields(monkeypatch):
    conn = _sales_db()

    class RepoStub:
        def get_header_with_customer(self, sale_id):
            return {
                "sale_id": sale_id,
                "date": "2026-06-21",
                "customer_name": "Alpha Customer",
                "customer_contact_info": "alpha@example.test",
                "customer_address": "Customer Road",
                "order_discount": 0.0,
                "payment_status": "unpaid",
            }

        def list_items(self, sale_id):
            return [
                {
                    "item_id": 1,
                    "sale_id": sale_id,
                    "product_id": 1,
                    "product_name": "Widget",
                    "quantity": 2.0,
                    "uom_id": 1,
                    "unit_name": "Piece",
                    "unit_price": 10.0,
                    "item_discount": 0.0,
                }
            ]

        def get_receivable_position(self, sale_id):
            return {
                "paid_amount": 0.0,
                "advance_payment_applied": 0.0,
                "remaining_due": 20.0,
                "returned_value": 0.0,
                "net_total_amount": 20.0,
            }

    class PaymentsRepoStub:
        def __init__(self, db_path):
            pass

        def list_by_sale(self, sale_id):
            return []

    import inventory_management.database.repositories.sale_payments_repo as payments_module

    monkeypatch.setattr(payments_module, "SalePaymentsRepo", PaymentsRepoStub)

    controller = SalesController.__new__(SalesController)
    controller.repo = RepoStub()
    controller.conn = conn
    controller._db_path = ":memory:"

    html = controller._generate_invoice_html_content("SO-PRINT-1")

    assert "SO-PRINT-1" in html
    assert "Widget" in html
    assert "Piece" in html
    assert "10.00" in html
    assert "20.00" in html


def test_print_sale_invoice_opens_preview(monkeypatch):
    class FakeHTML:
        def __init__(self, *, string):
            self.string = string

        def write_pdf(self, path, stylesheets=None):
            Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")

    class FakeCSS:
        def __init__(self, *args, **kwargs):
            pass

    fake_weasyprint = ModuleType("weasyprint")
    fake_weasyprint.HTML = FakeHTML
    fake_weasyprint.CSS = FakeCSS
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasyprint)

    shown = {}
    monkeypatch.setattr(
        "inventory_management.modules.sales.controller.show_invoice_preview",
        lambda parent, path, title: shown.update({"path": path, "title": title}),
    )

    controller = SalesController.__new__(SalesController)
    controller.view = SimpleNamespace()
    controller._generate_invoice_html_content = lambda sale_id: "<html>SO</html>"

    controller._print_sale_invoice("SO-PREVIEW-1")

    assert shown["title"] == "Sale Invoice SO-PREVIEW-1"
    assert Path(shown["path"]).exists()
    assert Path(shown["path"]).name == "SO-PREVIEW-1.pdf"
