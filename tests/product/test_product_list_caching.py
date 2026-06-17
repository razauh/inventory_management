from types import SimpleNamespace

import pytest

from inventory_management.database.repositories.products_repo import Product, ProductsRepo
from inventory_management.modules.product.components import ProductSummary
from inventory_management.modules.product.controller import ProductController


def test_list_products_returns_cached_metrics_and_uom_labels(conn, ids):
    repo = ProductsRepo(conn)
    product_id = repo.create("Perf Cache Product", "Cached row", "Tools", 8)
    base_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('Perf Cache Unit')"
    ).lastrowid
    alt_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('Perf Cache Box')"
    ).lastrowid
    repo.set_base_uom(product_id, int(base_uom_id))
    repo.add_alt_uom(product_id, int(alt_uom_id), 10)
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-PROD-CACHE', ?, '2026-06-14', 100, 'unpaid')
        """,
        (ids["vendor_id"],),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id, purchase_price, sale_price
        ) VALUES ('PO-PROD-CACHE', ?, 2, ?, 100, 150)
        """,
        (product_id, int(base_uom_id)),
    )
    conn.execute(
        """
        INSERT INTO product_sale_prices (product_id, price, date)
        VALUES (?, 17, '2026-06-15')
        """,
        (product_id,),
    )
    conn.execute(
        """
        INSERT INTO stock_valuation_history (
            product_id, valuation_date, quantity, unit_value, total_value, valuation_method
        ) VALUES (?, '2026-06-15', 7, 10, 70, 'moving_average')
        """,
        (product_id,),
    )

    row = next(product for product in repo.list_products() if product.product_id == product_id)
    metrics = repo.product_page_metrics([product_id])[product_id]

    assert row.base_uom_name is None
    assert metrics["base_uom_name"] == "Perf Cache Unit"
    assert metrics["alt_uom_names"] == "Perf Cache Box"
    assert metrics["on_hand_base"] == pytest.approx(7.0)
    assert metrics["cost_price_base"] == pytest.approx(10.0)
    assert metrics["sale_price_base"] == pytest.approx(17.0)
    assert metrics["latest_price_date"] == "2026-06-15"


def test_list_products_defaults_cached_metrics_without_history(conn):
    repo = ProductsRepo(conn)
    product_id = repo.create("No Cache History Product", None, None, 0)
    base_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('No Cache Unit')"
    ).lastrowid
    repo.set_base_uom(product_id, int(base_uom_id))

    metrics = repo.product_page_metrics([product_id])[product_id]

    assert metrics["base_uom_name"] == "No Cache Unit"
    assert metrics["on_hand_base"] == pytest.approx(0.0)
    assert metrics["cost_price_base"] == pytest.approx(0.0)
    assert metrics["sale_price_base"] == pytest.approx(0.0)
    assert metrics["latest_price_date"] is None


def test_list_products_searches_uoms_and_paginates(conn):
    repo = ProductsRepo(conn)
    first_id = repo.create("Paged A", None, "One", 0)
    second_id = repo.create("Paged B", None, "Two", 0)
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Searchable Crate')").lastrowid
    repo.set_base_uom(first_id, int(uom_id))

    searched = repo.list_products(search="crate", limit=10, offset=0)
    page = repo.list_products(search="Paged", limit=1, offset=0)

    assert repo.count_products("crate") == 1
    assert [p.product_id for p in searched] == [first_id]
    assert [p.product_id for p in page] == [second_id]


def test_list_products_search_matches_case_insensitive_substrings(conn):
    repo = ProductsRepo(conn)
    product_id = repo.create(
        "ielts advantage with answers",
        "Practice workbook",
        "Exam Prep",
        0,
    )
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Study Pack')").lastrowid
    repo.set_base_uom(product_id, int(uom_id))

    assert [p.product_id for p in repo.list_products(search="ADVANTAGE")] == [product_id]
    assert [p.product_id for p in repo.list_products(search="answer")] == [product_id]
    assert [p.product_id for p in repo.list_products(search="with")] == [product_id]
    assert [p.product_id for p in repo.list_products(search="work")] == [product_id]
    assert [p.product_id for p in repo.list_products(search="prep")] == [product_id]
    assert [p.product_id for p in repo.list_products(search="pack")] == [product_id]
    assert repo.count_products(str(product_id)[-1:]) >= 1


def test_product_summary_uses_aggregate_counts(conn):
    repo = ProductsRepo(conn)
    before = repo.product_summary()
    product_id = repo.create("Aggregate Summary Product", None, "Tools", 8)
    base_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('Aggregate Summary Unit')"
    ).lastrowid
    repo.set_base_uom(product_id, int(base_uom_id))
    conn.execute(
        """
        INSERT INTO product_sale_prices (product_id, price, date)
        VALUES (?, 17, '2026-06-15')
        """,
        (product_id,),
    )
    conn.execute(
        """
        INSERT INTO stock_valuation_history (
            product_id, valuation_date, quantity, unit_value, total_value, valuation_method
        ) VALUES (?, '2026-06-15', 7, 10, 70, 'moving_average')
        """,
        (product_id,),
    )

    after = repo.product_summary()

    assert after["total"] == before["total"] + 1
    assert after["low_stock"] == before["low_stock"] + 1
    assert after["priced"] == before["priced"] + 1
    assert after["with_uoms"] == before["with_uoms"] + 1


def test_refresh_summary_uses_cache_until_forced():
    captured: list[ProductSummary] = []
    calls: list[bool] = []

    controller = ProductController.__new__(ProductController)
    controller._summary_cache = None
    controller.repo = SimpleNamespace(
        product_summary=lambda: calls.append(True)
        or {"total": 4, "low_stock": 1, "priced": 2, "with_uoms": 3}
    )
    controller.view = SimpleNamespace(
        summary=SimpleNamespace(set_summary=lambda summary: captured.append(summary))
    )

    controller._refresh_summary()
    controller._refresh_summary()
    controller._refresh_summary(force=True)

    assert calls == [True, True]
    assert captured == [
        ProductSummary(total=4, low_stock=1, priced=2, with_uoms=3),
        ProductSummary(total=4, low_stock=1, priced=2, with_uoms=3),
        ProductSummary(total=4, low_stock=1, priced=2, with_uoms=3),
    ]


def test_update_selected_details_uses_cached_selected_product_only():
    details_calls: list[dict] = []
    selection_events: list[int] = []
    action_states: list[bool] = []

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("selection change should not query repo")

    product = Product(
        product_id=41,
        name="Cached Product",
        description="From list cache",
        category="Tools",
        min_stock_level=3,
        base_uom_name="Piece",
        alt_uom_names="Box, Case",
        cost_price_base=12.5,
        sale_price_base=15.0,
    )

    controller = ProductController.__new__(ProductController)
    controller.repo = SimpleNamespace(
        get=_unexpected,
        product_uoms=_unexpected,
        latest_prices_base=_unexpected,
    )
    controller.proxy = SimpleNamespace(rowCount=lambda: 1)
    controller.view = SimpleNamespace(
        search=SimpleNamespace(text=lambda: ""),
        details=SimpleNamespace(
            set_product=lambda **kwargs: details_calls.append(kwargs),
            set_empty=lambda *_args, **_kwargs: None,
            clear=lambda: None,
        ),
        selection_changed=SimpleNamespace(emit=lambda product_id: selection_events.append(product_id)),
    )
    controller._set_action_state = lambda enabled: action_states.append(enabled)
    controller._selected_product = lambda: product

    controller._update_selected_details()

    assert action_states == [True]
    assert selection_events == [41]
    assert details_calls == [
        {
            "product_id": 41,
            "name": "Cached Product",
            "category": "Tools",
            "min_stock_level": 3,
            "base_uom_name": "Piece",
            "alt_uom_names": "Box, Case",
            "sale_price": 15.0,
            "cost_price": 12.5,
            "description": "From list cache",
        }
    ]


def test_build_model_reuses_model_and_fetches_one_page():
    replaced_rows: list[list[Product]] = []
    rows = [
        Product(product_id=3, name="C", description=None, category=None, min_stock_level=0),
        Product(product_id=2, name="B", description=None, category=None, min_stock_level=0),
    ]

    controller = ProductController.__new__(ProductController)
    controller.PAGE_SIZE = 100
    controller._page_offset = 0
    controller._total_products = 0
    controller.repo = SimpleNamespace(
        count_products=lambda search: 125,
        list_products=lambda search, limit, offset: rows,
    )
    controller.view = SimpleNamespace(
        search=SimpleNamespace(text=lambda: "needle"),
        lbl_page=SimpleNamespace(setText=lambda text: None),
        btn_prev_page=SimpleNamespace(setEnabled=lambda enabled: None),
        btn_next_page=SimpleNamespace(setEnabled=lambda enabled: None),
    )
    controller.base_model = SimpleNamespace(replace=lambda new_rows: replaced_rows.append(new_rows))
    controller.proxy = object()
    controller._resize_table_columns = lambda row_count: None
    controller._restore_selection = lambda selected_pid: None
    controller._refresh_summary = lambda force=False: None
    controller._update_selected_details = lambda: None
    controller._schedule_page_metrics = lambda: None

    model_before = controller.base_model
    proxy_before = controller.proxy

    controller._build_model()

    assert controller.base_model is model_before
    assert controller.proxy is proxy_before
    assert replaced_rows == [rows]
    assert controller._total_products == 125


def test_search_reload_resets_to_first_page():
    reload_offsets: list[int] = []

    controller = ProductController.__new__(ProductController)
    controller._page_offset = 200
    controller._reload = lambda: reload_offsets.append(controller._page_offset)

    controller._run_search_reload()

    assert reload_offsets == [0]


def test_apply_filter_only_starts_debounce_timer():
    starts: list[bool] = []

    class ProxyStub:
        def setFilterRegularExpression(self, *_args, **_kwargs):
            raise AssertionError("product search should not filter the proxy")

    controller = ProductController.__new__(ProductController)
    controller.proxy = ProxyStub()
    controller._search_timer = SimpleNamespace(start=lambda: starts.append(True))

    controller._apply_filter("needle")

    assert starts == [True]


def test_next_and_prev_page_move_by_page_size():
    reload_offsets: list[int] = []

    controller = ProductController.__new__(ProductController)
    controller.PAGE_SIZE = 100
    controller._page_offset = 0
    controller._total_products = 250
    controller._reload = lambda: reload_offsets.append(controller._page_offset)

    controller._next_page()
    controller._prev_page()

    assert reload_offsets == [100, 0]
