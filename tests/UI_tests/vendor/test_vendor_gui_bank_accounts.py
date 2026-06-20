from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from inventory_management.modules.vendor.bank_accounts_dialog import AccountEditDialog, VendorBankAccountsDialog

from .conftest import (
    account_text,
    cancel_button,
    cell_text,
    drive_account_edit,
    fill_line_edit,
    fill_valid_account_dialog,
    ok_button,
    select_account_row,
    select_vendor_by_name,
    vendor_id_by_name,
)


def test_account_edit_dialog_save_cancel_validation_and_trim(qtbot, message_log):
    dialog = AccountEditDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)
    assert dialog.isVisible()
    assert any(call[1] == "Required" for call in message_log)

    fill_line_edit(dialog.txt_label, "  Trimmed Label  ")
    fill_line_edit(dialog.txt_bank, "  Trimmed Bank  ")
    fill_line_edit(dialog.txt_acc, "  44445555  ")
    fill_line_edit(dialog.txt_iban, "  IBAN444  ")
    fill_line_edit(dialog.txt_rout, "  ROUT444  ")
    QTest.mouseClick(dialog.chk_active, Qt.LeftButton)
    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    assert not dialog.isVisible()
    assert dialog.payload() == {
        "label": "Trimmed Label",
        "bank_name": "Trimmed Bank",
        "account_no": "44445555",
        "iban": "IBAN444",
        "routing_no": "ROUT444",
        "is_active": 0,
    }


def test_account_edit_cancel_keeps_payload_empty(qtbot):
    dialog = AccountEditDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    fill_valid_account_dialog(dialog, "Cancelled Account")
    QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    assert dialog.payload() is None


def test_main_accounts_panel_add_edit_deactivate_activate_and_primary(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "Multi Account Vendor")
    before = view.accounts_table.model().rowCount()

    def add_account(dialog):
        fill_valid_account_dialog(dialog, "Panel Added")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_account_edit(qtbot, view.btn_acc_add, add_account)
    qtbot.waitUntil(lambda: view.accounts_table.model().rowCount() == before + 1, timeout=3000)
    assert conn.execute("SELECT 1 FROM vendor_bank_accounts WHERE label='Panel Added'").fetchone() is not None

    select_account_row(qtbot, view, 0)

    def edit_account(dialog):
        fill_line_edit(dialog.txt_label, "Panel Edited")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_account_edit(qtbot, view.btn_acc_edit, edit_account)
    qtbot.waitUntil(lambda: "Panel Edited" in [account_text(view, r, 1) for r in range(view.accounts_table.model().rowCount())], timeout=3000)

    select_account_row(qtbot, view, 0)
    QTest.mouseClick(view.btn_acc_set_primary, Qt.LeftButton)
    qtbot.wait(180)
    assert account_text(view, 0, 6) == "Yes"

    if view.btn_acc_deactivate.isEnabled() and account_text(view, 0, 6) == "No":
        QTest.mouseClick(view.btn_acc_deactivate, Qt.LeftButton)
        qtbot.wait(180)
        assert "No" in [account_text(view, r, 7) for r in range(view.accounts_table.model().rowCount())]

    assert any(call[1] in {"Added", "Updated"} for call in message_log)


def test_bank_accounts_management_dialog_empty_state_add_edit_toggle_primary_and_close(qtbot, conn, message_log):
    vendor_id = vendor_id_by_name(conn, "No Account Vendor 500")
    dialog = VendorBankAccountsDialog(conn=conn, vendor_id=vendor_id)
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.empty_label.isVisible()
    assert dialog.empty_label.text() == "No bank accounts yet."
    assert dialog.tbl.rowCount() == 0
    assert not dialog.btn_edit.isEnabled()
    assert not dialog.btn_toggle.isEnabled()
    assert not dialog.btn_primary.isEnabled()

    def add_account(child):
        fill_valid_account_dialog(child, "Dialog Added")
        QTest.mouseClick(ok_button(child), Qt.LeftButton)

    drive_account_edit(qtbot, dialog.btn_add, add_account)
    qtbot.waitUntil(lambda: dialog.tbl.rowCount() == 1, timeout=3000)

    assert not dialog.empty_label.isVisible()
    assert cell_text(dialog.tbl, 0, 1) == "Dialog Added"
    assert dialog.btn_edit.isEnabled()
    assert dialog.btn_toggle.text() == "Deactivate"

    def edit_account(child):
        fill_line_edit(child.txt_label, "Dialog Edited")
        QTest.mouseClick(ok_button(child), Qt.LeftButton)

    drive_account_edit(qtbot, dialog.btn_edit, edit_account)
    assert cell_text(dialog.tbl, 0, 1) == "Dialog Edited"

    QTest.mouseClick(dialog.btn_primary, Qt.LeftButton)
    qtbot.wait(100)
    assert cell_text(dialog.tbl, 0, 4) == "Yes"

    button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
    QTest.mouseClick(button, Qt.LeftButton)
    assert not dialog.isVisible()


def test_bank_accounts_management_dialog_active_inactive_button_states(qtbot, conn):
    vendor_id = vendor_id_by_name(conn, "Inactive Account Vendor")
    dialog = VendorBankAccountsDialog(conn=conn, vendor_id=vendor_id)
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.tbl.rowCount() == 1
    dialog.tbl.selectRow(0)
    qtbot.wait(50)
    assert cell_text(dialog.tbl, 0, 5) == "Inactive"
    assert dialog.btn_toggle.text() == "Activate"
    assert dialog.btn_primary.isEnabled() is False

    QTest.mouseClick(dialog.btn_toggle, Qt.LeftButton)
    qtbot.wait(100)
    assert cell_text(dialog.tbl, 0, 5) == "Active"
    assert dialog.btn_toggle.text() == "Deactivate"
    assert dialog.btn_primary.isEnabled()
