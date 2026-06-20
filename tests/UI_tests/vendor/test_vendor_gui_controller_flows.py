from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.modules.vendor.model import VendorBankAccountsTableModel, VendorsTableModel

from .conftest import (
    drive_account_edit,
    drive_vendor_form,
    fill_line_edit,
    fill_plain_text,
    fill_valid_account_dialog,
    ok_button,
    select_account_row,
    select_vendor_by_name,
    table_text,
    type_search,
)


def test_controller_loads_vendor_rows_status_selection_and_accounts(qtbot, vendor_controller):
    view = vendor_controller.view

    assert vendor_controller.base_model.rowCount() == 100
    assert vendor_controller._total_vendors == 125
    assert view.list_status.text() == "Showing 100 of 125 vendor(s)"

    select_vendor_by_name(qtbot, vendor_controller, "Primary Account Vendor")
    assert view.details.lab_name.text() == "Primary Account Vendor"
    assert view.accounts_table.model().rowCount() == 1


def test_controller_add_and_edit_flows_from_toolbar(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view

    def add(dialog):
        fill_line_edit(dialog.name, "Controller Vendor")
        fill_plain_text(dialog.contact, "Controller contact")
        fill_plain_text(dialog.addr, "Controller address")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_add, add)
    qtbot.waitUntil(lambda: vendor_controller._total_vendors == 126, timeout=3000)
    type_search(qtbot, vendor_controller, "Controller Vendor", expected_total=1)
    select_vendor_by_name(qtbot, vendor_controller, "Controller Vendor")

    def edit(dialog):
        fill_line_edit(dialog.name, "Controller Vendor Edited")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_edit, edit)
    type_search(qtbot, vendor_controller, "Controller Vendor Edited", expected_total=1)

    assert table_text(view, 0, 1) == "Controller Vendor Edited"
    assert conn.execute("SELECT 1 FROM vendors WHERE name='Controller Vendor Edited'").fetchone() is not None
    assert any(call[1] == "Saved" for call in message_log)


def test_controller_import_cancel_does_not_change_table(qtbot, vendor_controller, monkeypatch):
    view = vendor_controller.view
    before = vendor_controller._total_vendors
    monkeypatch.setattr(
        "inventory_management.modules.vendor.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    QTest.mouseClick(view.btn_import, Qt.LeftButton)
    qtbot.wait(50)

    assert vendor_controller._total_vendors == before


def test_controller_import_button_uses_file_dialog_imports_and_reloads(qtbot, vendor_controller, monkeypatch, tmp_path, message_log):
    view = vendor_controller.view
    xlsx_path = tmp_path / "vendors.xlsx"
    xlsx_path.write_bytes(b"not read by fake importer")

    monkeypatch.setattr(
        "inventory_management.modules.vendor.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(xlsx_path), "Excel Workbooks (*.xlsx)"),
    )

    def fake_import(conn, path):
        assert path == xlsx_path
        VendorsRepo(conn).create("Imported Vendor GUI", "import contact", "import address")
        return SimpleNamespace(imported_count=1, failed_count=0)

    fake_module = types.SimpleNamespace(
        ImportValidationError=Exception,
        import_vendors_from_xlsx=fake_import,
    )
    monkeypatch.setitem(sys.modules, "inventory_management.scripts.bulk_import_vendors", fake_module)
    monkeypatch.setitem(sys.modules, "scripts.bulk_import_vendors", fake_module)

    QTest.mouseClick(view.btn_import, Qt.LeftButton)
    qtbot.waitUntil(lambda: vendor_controller._total_vendors == 126, timeout=3000)
    type_search(qtbot, vendor_controller, "Imported Vendor GUI", expected_total=1)

    assert table_text(view, 0, 1) == "Imported Vendor GUI"
    assert any(call[1] == "Import complete" for call in message_log)


def test_controller_import_invalid_path_shows_failure(qtbot, vendor_controller, monkeypatch, message_log):
    view = vendor_controller.view
    monkeypatch.setattr(
        "inventory_management.modules.vendor.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("/missing/vendors.xlsx", "Excel Workbooks (*.xlsx)"),
    )

    QTest.mouseClick(view.btn_import, Qt.LeftButton)
    qtbot.wait(50)

    assert any(call[1] == "Import failed" for call in message_log)


def test_controller_right_panel_account_actions_are_user_visible(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "No Account Vendor 500")

    def add(dialog):
        fill_valid_account_dialog(dialog, "Controller Account")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_account_edit(qtbot, view.btn_acc_add, add)
    qtbot.waitUntil(lambda: view.accounts_table.model().rowCount() == 1, timeout=3000)
    select_account_row(qtbot, view, 0)

    assert view.lblAccLabel.text() == "Controller Account"
    assert conn.execute("SELECT 1 FROM vendor_bank_accounts WHERE label='Controller Account'").fetchone() is not None
    assert any(call[1] == "Added" for call in message_log)


def test_vendor_table_and_account_models_display_and_replace():
    vendors = [
        {"vendor_id": 1, "name": "Alpha", "contact_info": None, "address": None},
        {"vendor_id": 2, "name": "Beta", "contact_info": "Contact", "address": "Address"},
    ]
    model = VendorsTableModel(vendors)
    assert model.rowCount() == 2
    assert model.columnCount() == 4
    assert model.data(model.index(0, 2), Qt.DisplayRole) is None
    assert model.data(model.index(0, 3), Qt.DisplayRole) == ""
    model.replace([vendors[1]])
    assert model.vendor_ids() == [2]

    accounts = VendorBankAccountsTableModel([
        {
            "vendor_bank_account_id": 3,
            "label": "Masked",
            "bank_name": "Bank",
            "account_no": "123456789",
            "iban": "IBAN123456789",
            "routing_no": "ROUT1234",
            "is_primary": 1,
            "is_active": 0,
        }
    ])
    assert accounts.rowCount() == 1
    assert accounts.columnCount() == 8
    assert accounts.data(accounts.index(0, 3), Qt.DisplayRole).endswith("6789")
    assert accounts.data(accounts.index(0, 4), Qt.DisplayRole).endswith("456789")
    assert accounts.data(accounts.index(0, 6), Qt.DisplayRole) == "Yes"
    assert accounts.data(accounts.index(0, 7), Qt.DisplayRole) == "No"
