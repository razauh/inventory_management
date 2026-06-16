import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.vendor.controller import VendorController
from inventory_management.modules.vendor.model import VendorBankAccountsTableModel, VendorsTableModel


@pytest.fixture()
def vendor_balance_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_a = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor A', 'A')"
    ).lastrowid
    vendor_b = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor B', 'B')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-06-15', 42.5, 'deposit')
        """,
        (vendor_a,),
    )
    conn.commit()
    try:
        yield conn, int(vendor_a), int(vendor_b)
    finally:
        conn.close()


def test_list_vendors_is_light_and_balances_are_batched(vendor_balance_db):
    conn, vendor_a, vendor_b = vendor_balance_db
    repo = VendorsRepo(conn)

    rows = repo.list_vendors()
    balances = repo.vendor_balances([vendor_a, vendor_b])

    assert rows[0].vendor_id == vendor_b
    assert rows[0].balance is None
    assert rows[1].vendor_id == vendor_a
    assert rows[1].balance is None
    assert balances[vendor_b] == pytest.approx(0.0)
    assert balances[vendor_a] == pytest.approx(42.5)


def test_list_vendors_search_count_and_paging(vendor_balance_db):
    conn, vendor_a, vendor_b = vendor_balance_db
    repo = VendorsRepo(conn)
    vendor_c = repo.create("Vendor C", "C", "Central")

    page = repo.list_vendors(limit=2, offset=0)
    second_page = repo.list_vendors(limit=2, offset=2)
    searched = repo.list_vendors(search="Central", limit=10, offset=0)

    assert [row.vendor_id for row in page] == [vendor_c, vendor_b]
    assert [row.vendor_id for row in second_page] == [vendor_a]
    assert [row.vendor_id for row in searched] == [vendor_c]
    assert repo.count_vendors("Vendor") == 3
    assert repo.count_vendors("missing") == 0


def test_update_details_uses_cached_vendor_row_balance():
    scheduled: list[int | None] = []
    credit_calls: list[float] = []
    data_calls: list[dict] = []

    controller = VendorController.__new__(VendorController)
    controller._selected_id = MagicMock(return_value=17)
    controller._current_vendor_row = MagicMock(
        return_value={
            "vendor_id": 17,
            "name": "Cached Vendor",
            "contact_info": "Contact",
            "address": "Addr",
            "balance": 55.75,
        }
    )
    controller.vadv = SimpleNamespace(
        get_balance=MagicMock(side_effect=AssertionError("balance query should not run"))
    )
    controller.view = SimpleNamespace(
        details=SimpleNamespace(
            set_data=lambda row: data_calls.append(row),
            set_credit=lambda amount: credit_calls.append(float(amount)),
            set_credit_error=lambda *_args, **_kwargs: None,
        )
    )
    controller._schedule_accounts_reload = lambda vendor_id: scheduled.append(vendor_id)
    controller._hook_acc_selection_enablement = lambda: None
    controller._update_acc_buttons_enabled = lambda *_args, **_kwargs: None

    controller._update_details()

    assert data_calls == [
        {
            "vendor_id": 17,
            "name": "Cached Vendor",
            "contact_info": "Contact",
            "address": "Addr",
            "balance": 55.75,
        }
    ]
    assert credit_calls == [55.75]
    assert scheduled == [17]


def test_account_reload_schedule_keeps_latest_selection():
    controller = VendorController.__new__(VendorController)
    controller._pending_accounts_vendor_id = None
    controller._pending_accounts_keep_id = None
    controller._accounts_reload_timer = SimpleNamespace(start=MagicMock())
    controller._reload_accounts = MagicMock()

    controller._schedule_accounts_reload(11)
    controller._schedule_accounts_reload(12, keep_account_id=99)
    controller._run_pending_account_reload()

    controller._reload_accounts.assert_called_once_with(12, 99)


def _account_reload_controller(vbank):
    controller = VendorController.__new__(VendorController)
    controller.vbank = vbank
    controller._accounts_model = VendorBankAccountsTableModel([])
    controller._accounts_loaded_vendor_id = None
    controller._accounts_cache = {}
    controller._pending_accounts_vendor_id = None
    controller._pending_accounts_keep_id = None
    controller._accounts_reload_timer = SimpleNamespace(stop=lambda: None)
    controller._accounts_columns_resized = False
    controller.view = SimpleNamespace(
        accounts_table=SimpleNamespace(
            resizeColumnsToContents=lambda: None,
            horizontalHeader=lambda: SimpleNamespace(
                setSectionResizeMode=lambda *_args, **_kwargs: None,
                setStretchLastSection=lambda *_args, **_kwargs: None,
            ),
            setColumnWidth=lambda *_args, **_kwargs: None,
            selectionModel=lambda: None,
            setCurrentIndex=lambda *_args, **_kwargs: None,
            model=lambda: controller._accounts_model,
        )
    )
    controller._clear_account_details = lambda: None
    controller._after_accounts_model_bound = lambda: None
    controller._hook_acc_selection_enablement = lambda: None
    controller._update_acc_buttons_enabled = lambda *_args, **_kwargs: None
    controller._update_account_details = lambda *_args, **_kwargs: None
    return controller


def test_account_reload_uses_cached_rows_when_vendor_reselected():
    rows_by_vendor = {
        1: [{"vendor_bank_account_id": 10, "label": "A"}],
        2: [{"vendor_bank_account_id": 20, "label": "B"}],
    }
    vbank = SimpleNamespace(
        list=MagicMock(side_effect=lambda vendor_id, active_only=False: rows_by_vendor[vendor_id])
    )
    controller = _account_reload_controller(vbank)

    controller._reload_accounts(1)
    controller._reload_accounts(2)
    controller._reload_accounts(1)

    assert [call.args[0] for call in vbank.list.call_args_list] == [1, 2]
    assert controller._accounts_model.row_at(0)["vendor_bank_account_id"] == 10


def test_account_reload_force_refreshes_cache():
    vbank = SimpleNamespace(
        list=MagicMock(
            side_effect=[
                [{"vendor_bank_account_id": 10, "label": "Old"}],
                [{"vendor_bank_account_id": 11, "label": "New"}],
            ]
        )
    )
    controller = _account_reload_controller(vbank)

    controller._reload_accounts(1)
    controller._reload_accounts(1, force=True)

    assert vbank.list.call_count == 2
    assert controller._accounts_cache[1][0]["vendor_bank_account_id"] == 11
    assert controller._accounts_model.row_at(0)["label"] == "New"


def test_account_cache_clear_can_target_one_vendor_or_all():
    controller = VendorController.__new__(VendorController)
    controller._accounts_cache = {1: [{"id": 1}], 2: [{"id": 2}]}
    controller._accounts_loaded_vendor_id = 1

    controller._clear_accounts_cache(1)

    assert controller._accounts_cache == {2: [{"id": 2}]}
    assert controller._accounts_loaded_vendor_id is None

    controller._clear_accounts_cache()

    assert controller._accounts_cache == {}


def test_build_model_loads_one_page_and_batches_balances():
    rows = [SimpleNamespace(vendor_id=3, name="C", contact_info="C", address=None)]
    balances: list[list[int]] = []
    list_calls: list[tuple[str, int, int]] = []

    controller = VendorController.__new__(VendorController)
    controller.PAGE_SIZE = 100
    controller._page_offset = 20
    controller._pending_search = "needle"
    controller._balance_token = 0
    controller.repo = SimpleNamespace(
        count_vendors=lambda search: 120,
        list_vendors=lambda search, limit, offset: list_calls.append((search, limit, offset)) or rows,
        vendor_balances=lambda ids: balances.append(ids) or {3: 12.5},
    )
    controller.base_model = VendorsTableModel([])
    controller.proxy = SimpleNamespace(rowCount=lambda: controller.base_model.rowCount())
    controller.view = SimpleNamespace(
        table=SimpleNamespace(
            resizeColumnsToContents=lambda: None,
            horizontalHeader=lambda: SimpleNamespace(
                setSectionResizeMode=lambda *_args, **_kwargs: None,
                setStretchLastSection=lambda *_args, **_kwargs: None,
            ),
            setColumnWidth=lambda *_args, **_kwargs: None,
        ),
        lbl_page=SimpleNamespace(setText=lambda text: None),
        btn_prev_page=SimpleNamespace(setEnabled=lambda enabled: None),
        btn_next_page=SimpleNamespace(setEnabled=lambda enabled: None),
        list_status=SimpleNamespace(setText=lambda text: None),
        details=SimpleNamespace(set_data=lambda row: None, set_credit=lambda amount: None),
    )
    controller._update_details = lambda *_args, **_kwargs: None

    controller._build_model()
    controller._hydrate_visible_balances(controller._balance_token)

    assert controller.base_model.rowCount() == 1
    assert list_calls == [("needle", 100, 20)]
    assert balances == [[3]]
    assert controller.base_model.row_at(0)["balance"] == pytest.approx(12.5)


def test_vendor_apply_filter_only_starts_debounce_timer():
    starts: list[bool] = []

    class ProxyStub:
        def setFilterRegularExpression(self, *_args, **_kwargs):
            raise AssertionError("vendor search should not filter the proxy")

    controller = VendorController.__new__(VendorController)
    controller.proxy = ProxyStub()
    controller._pending_search = ""
    controller._search_timer = SimpleNamespace(start=lambda: starts.append(True))

    controller._apply_filter("  vendor  ")

    assert controller._pending_search == "vendor"
    assert starts == [True]


def test_vendor_search_reload_resets_offset():
    reload_offsets: list[int] = []

    controller = VendorController.__new__(VendorController)
    controller._page_offset = 200
    controller._reload = lambda: reload_offsets.append(controller._page_offset)

    controller._run_search_reload()

    assert reload_offsets == [0]
