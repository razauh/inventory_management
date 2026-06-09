import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from inventory_management.database.repositories.vendor_bank_accounts_repo import (
    VendorBankAccountsRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.vendor.controller import VendorController


def make_bank_account_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Bank Vendor', 'Test')"
    ).lastrowid
    primary_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Primary', 'Bank A', '111', 1, 1)
        """,
        (vendor_id,),
    ).lastrowid
    secondary_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Secondary', 'Bank B', '222', 0, 1)
        """,
        (vendor_id,),
    ).lastrowid
    conn.commit()
    return conn, int(vendor_id), int(primary_id), int(secondary_id)


def test_create_leaves_commit_control_to_caller():
    conn, vendor_id, _primary_id, _secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    repo.create(vendor_id, {"label": "Uncommitted"})
    assert conn.execute(
        "SELECT COUNT(*) FROM vendor_bank_accounts WHERE label = 'Uncommitted'"
    ).fetchone()[0] == 1

    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) FROM vendor_bank_accounts WHERE label = 'Uncommitted'"
    ).fetchone()[0] == 0
    conn.close()


def test_update_does_not_commit_unrelated_pending_work():
    conn, _vendor_id, primary_id, _secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    conn.execute("INSERT INTO vendors (name, contact_info) VALUES ('Pending', 'Test')")
    repo.update(primary_id, {"label": "Renamed"})
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) FROM vendors WHERE name = 'Pending'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT label FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["label"] == "Primary"
    conn.close()


def test_force_set_primary_does_not_commit_unrelated_pending_work():
    conn, vendor_id, primary_id, secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    conn.execute("INSERT INTO vendors (name, contact_info) VALUES ('Pending', 'Test')")
    repo.force_set_primary(vendor_id, secondary_id)
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) FROM vendors WHERE name = 'Pending'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["is_primary"] == 1
    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (secondary_id,),
    ).fetchone()["is_primary"] == 0
    conn.close()


def test_schema_rejects_inactive_primary_insert():
    conn, vendor_id, _primary_id, _secondary_id = make_bank_account_db()

    with pytest.raises(sqlite3.IntegrityError, match="Primary vendor bank account must be active"):
        conn.execute(
            """
            INSERT INTO vendor_bank_accounts (
                vendor_id, label, bank_name, account_no, is_primary, is_active
            ) VALUES (?, 'Inactive Primary', 'Bank C', '333', 1, 0)
            """,
            (vendor_id,),
        )

    conn.close()


def test_schema_rejects_primary_update_to_inactive():
    conn, _vendor_id, primary_id, _secondary_id = make_bank_account_db()

    with pytest.raises(sqlite3.IntegrityError, match="Primary vendor bank account must be active"):
        conn.execute(
            "UPDATE vendor_bank_accounts SET is_active = 0 WHERE vendor_bank_account_id = ?",
            (primary_id,),
        )

    row = conn.execute(
        "SELECT is_primary, is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()
    assert row["is_primary"] == 1
    assert row["is_active"] == 1
    conn.close()


def test_deactivate_rejects_primary_account():
    conn, _vendor_id, primary_id, _secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    with pytest.raises(sqlite3.IntegrityError, match="Cannot deactivate primary"):
        repo.deactivate(primary_id)

    row = conn.execute(
        "SELECT is_primary, is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()
    assert row["is_primary"] == 1
    assert row["is_active"] == 1
    conn.close()


def test_force_set_primary_rejects_inactive_account_without_clearing_existing_primary():
    conn, vendor_id, primary_id, secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)
    repo.deactivate(secondary_id)

    with pytest.raises(sqlite3.IntegrityError, match="belong to the vendor and be active"):
        repo.force_set_primary(vendor_id, secondary_id)

    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["is_primary"] == 1
    secondary_row = conn.execute(
        "SELECT is_primary, is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (secondary_id,),
    ).fetchone()
    assert secondary_row["is_primary"] == 0
    assert secondary_row["is_active"] == 0
    conn.close()


def test_force_set_primary_rejects_wrong_vendor_account_without_clearing_existing_primary():
    conn, vendor_id, primary_id, _secondary_id = make_bank_account_db()
    other_vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Other Vendor', 'Test')"
    ).lastrowid
    other_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Other Account', 'Bank D', '444', 0, 1)
        """,
        (other_vendor_id,),
    ).lastrowid
    repo = VendorBankAccountsRepo(conn)

    with pytest.raises(sqlite3.IntegrityError, match="belong to the vendor and be active"):
        repo.force_set_primary(vendor_id, int(other_account_id))

    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["is_primary"] == 1
    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (other_account_id,),
    ).fetchone()["is_primary"] == 0
    conn.close()


def test_force_set_primary_switches_to_active_same_vendor_account():
    conn, vendor_id, primary_id, secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    repo.force_set_primary(vendor_id, secondary_id)

    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["is_primary"] == 0
    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (secondary_id,),
    ).fetchone()["is_primary"] == 1
    conn.close()


def test_set_primary_switches_to_active_same_vendor_account():
    conn, vendor_id, primary_id, secondary_id = make_bank_account_db()
    repo = VendorBankAccountsRepo(conn)

    assert repo.set_primary(vendor_id, secondary_id) == 1

    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    ).fetchone()["is_primary"] == 0
    assert conn.execute(
        "SELECT is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (secondary_id,),
    ).fetchone()["is_primary"] == 1
    conn.close()


class TrackingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, parameters=()):
        self.statements.append((sql, parameters))
        return MagicMock()


def make_controller():
    controller = VendorController.__new__(VendorController)
    controller.conn = TrackingConnection()
    controller.vbank = MagicMock()
    controller.view = SimpleNamespace()
    controller._selected_id = MagicMock(return_value=7)
    return controller


def test_controller_create_bank_account_wraps_repository_call_in_savepoint():
    controller = make_controller()
    controller.vbank.create.return_value = 55

    account_id = controller.create_bank_account({"label": "Main"})

    assert account_id == 55
    controller.vbank.create.assert_called_once_with(7, {"label": "Main"})
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT vendor_bank_account_mutation",
        "RELEASE vendor_bank_account_mutation",
    ]


def test_controller_rolls_back_savepoint_when_bank_account_update_fails():
    controller = make_controller()
    controller.vbank.update.side_effect = sqlite3.IntegrityError("duplicate label")

    with patch("inventory_management.modules.vendor.controller.info") as show_info:
        result = controller.update_bank_account(9, {"label": "Duplicate"})

    assert result is False
    controller.vbank.update.assert_called_once_with(9, {"label": "Duplicate"})
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT vendor_bank_account_mutation",
        "ROLLBACK TO vendor_bank_account_mutation",
        "RELEASE vendor_bank_account_mutation",
    ]
    show_info.assert_called_once()


@pytest.mark.parametrize(
    ("method_name", "repo_method"),
    [
        ("deactivate_bank_account", "deactivate"),
        ("set_primary_bank_account", "force_set_primary"),
    ],
)
def test_controller_bank_account_helpers_release_savepoint_on_success(
    method_name, repo_method
):
    controller = make_controller()
    getattr(controller.vbank, repo_method).return_value = 1

    result = getattr(controller, method_name)(9)

    assert result is True
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT vendor_bank_account_mutation",
        "RELEASE vendor_bank_account_mutation",
    ]
