import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.vendor.controller import VendorController


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


def test_list_vendors_includes_cached_balance(vendor_balance_db):
    conn, vendor_a, vendor_b = vendor_balance_db
    repo = VendorsRepo(conn)

    rows = repo.list_vendors()

    assert rows[0].vendor_id == vendor_b
    assert rows[0].balance == pytest.approx(0.0)
    assert rows[1].vendor_id == vendor_a
    assert rows[1].balance == pytest.approx(42.5)


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
