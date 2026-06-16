import sqlite3

from inventory_management.database.repositories.customers_repo import CustomersRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.customer.controller import CustomerController


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


def seed_customers(conn):
    repo = CustomersRepo(conn)
    alpha_id = repo.create("Alpha Buyer", "555-0100", "Alpha Street")
    alpine_id = repo.create("Alpine Buyer", "555-0200", "Alpine Street")
    beta_id = repo.create("Beta Buyer", "555-0300", "Beta Street")
    return repo, alpha_id, alpine_id, beta_id


def test_customer_controller_reuses_models_and_searches_in_repo(qtbot):
    conn = make_db()
    repo, alpha_id, _, _ = seed_customers(conn)
    controller = CustomerController(conn)
    qtbot.addWidget(controller.get_widget())

    base = controller.base
    proxy = controller.proxy
    controller._select_customer_id(alpha_id)

    def fail_proxy_filter(*_args, **_kwargs):
        raise AssertionError("customer search should not filter the proxy")

    controller.proxy.setFilterRegularExpression = fail_proxy_filter

    controller._apply_filter("Alpha")

    assert controller.base is base
    assert controller.proxy is proxy
    assert controller.base.rowCount() == 1
    assert controller._selected_id() == alpha_id
    assert controller.view.list_status.text() == "Showing 1 of 1 match(es)"

    controller._apply_filter("missing")

    assert controller.base is base
    assert controller.proxy is proxy
    assert controller.base.rowCount() == 0
    assert controller._selected_id() is None
    assert controller.view.details.lab_id.text() == "-"
    assert controller.view.list_status.text() == "No customers match this search."

    conn.close()


def test_customer_controller_does_not_stack_detail_refreshes(qtbot):
    conn = make_db()
    _, alpha_id, _, _ = seed_customers(conn)
    controller = CustomerController(conn)
    qtbot.addWidget(controller.get_widget())
    controller._select_customer_id(alpha_id)

    calls = []
    original = controller.repo.get_detail_snapshot

    def spy(customer_id):
        calls.append(customer_id)
        return original(customer_id)

    controller.repo.get_detail_snapshot = spy
    controller._last_detail_customer_id = None
    calls.clear()

    controller._apply_filter("Al")
    controller._apply_filter("Alp")
    controller._apply_filter("Alpha")
    controller._update_details_now()

    assert calls == [alpha_id]

    controller._schedule_details_update()
    controller._update_details_now()

    assert calls == [alpha_id]

    conn.close()


def test_customer_controller_pages_with_query_metadata(qtbot):
    conn = make_db()
    repo = CustomersRepo(conn)
    for idx in range(105):
        repo.create(f"Paged Customer {idx:03d}", f"555-{idx:04d}", "Paged Street")
    controller = CustomerController(conn)
    qtbot.addWidget(controller.get_widget())

    assert controller.base.rowCount() == controller.PAGE_SIZE
    assert controller.view.list_status.text() == "Showing 100 of 105 customer(s)"
    assert controller.view.lbl_page.text() == "Page 1 / 2"
    assert controller.view.btn_next_page.isEnabled()

    controller._next_page()

    assert controller.base.rowCount() == 5
    assert controller.view.list_status.text() == "Showing 5 of 105 customer(s)"
    assert controller.view.lbl_page.text() == "Page 2 / 2"
    assert not controller.view.btn_next_page.isEnabled()

    conn.close()


def test_customer_repo_detail_snapshot_returns_financial_fields():
    conn = make_db()
    repo, customer_id, _, _ = seed_customers(conn)

    conn.execute("INSERT INTO uoms(unit_name) VALUES (?)", ("Each",))
    uom_id = conn.execute("SELECT uom_id FROM uoms WHERE unit_name = ?", ("Each",)).fetchone()["uom_id"]
    conn.execute(
        "INSERT INTO products(name, description, category, min_stock_level) VALUES (?,?,?,?)",
        ("Widget", "", "", 0),
    )
    product_id = conn.execute("SELECT product_id FROM products WHERE name = ?", ("Widget",)).fetchone()["product_id"]
    conn.execute(
        "INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base) VALUES (?,?,?,?)",
        (product_id, uom_id, 1, 1),
    )
    conn.execute(
        """
        INSERT INTO sales(
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, doc_type
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        ("SO-1", customer_id, "2026-01-10", 20, 0, "partial", 5, 2, "sale"),
    )
    conn.execute(
        """
        INSERT INTO sale_items(sale_id, product_id, quantity, uom_id, unit_price, item_discount)
        VALUES (?,?,?,?,?,?)
        """,
        ("SO-1", product_id, 1, uom_id, 20, 0),
    )
    conn.execute(
        """
        INSERT INTO sale_payments(sale_id, date, amount, method, clearing_state)
        VALUES (?,?,?,?,?)
        """,
        ("SO-1", "2026-01-12", 5, "Cash", "posted"),
    )
    conn.execute(
        """
        INSERT INTO customer_advances(customer_id, tx_date, amount, source_type, method)
        VALUES (?,?,?,?,?)
        """,
        (customer_id, "2026-01-05", 7, "deposit", "Cash"),
    )
    conn.execute(
        """
        INSERT INTO customer_advances(customer_id, tx_date, amount, source_type, source_id)
        VALUES (?,?,?,?,?)
        """,
        (customer_id, "2026-01-13", -2, "applied_to_sale", "SO-1"),
    )
    conn.commit()

    snapshot = repo.get_detail_snapshot(customer_id)

    assert snapshot["customer_id"] == customer_id
    assert snapshot["name"] == "Alpha Buyer"
    assert snapshot["credit_balance"] == 5.0
    assert snapshot["sales_count"] == 1
    assert snapshot["open_due_sum"] == 13.0
    assert snapshot["last_sale_date"] == "2026-01-10"
    assert snapshot["last_payment_date"] == "2026-01-12"
    assert snapshot["last_advance_date"] == "2026-01-13"

    conn.close()
