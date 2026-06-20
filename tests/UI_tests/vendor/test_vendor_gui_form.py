from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from inventory_management.modules.vendor.form import VendorForm

from .conftest import (
    cancel_button,
    drive_vendor_form,
    fill_line_edit,
    fill_plain_text,
    fill_valid_vendor_form,
    ok_button,
    select_vendor_by_name,
    table_text,
    type_search,
)


def test_open_add_vendor_dialog_and_save_valid_vendor(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view

    def interact(dialog: VendorForm):
        fill_valid_vendor_form(dialog, "GUI Added Vendor")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_add, interact)
    qtbot.waitUntil(lambda: vendor_controller._total_vendors == 126, timeout=3000)
    type_search(qtbot, vendor_controller, "GUI Added Vendor", expected_total=1)

    assert table_text(view, 0, 1) == "GUI Added Vendor"
    assert conn.execute("SELECT 1 FROM vendors WHERE name='GUI Added Vendor'").fetchone() is not None
    assert any(call[1] == "Saved" for call in message_log)


def test_cancel_add_vendor_does_not_persist(qtbot, vendor_controller, conn):
    view = vendor_controller.view

    def interact(dialog: VendorForm):
        fill_valid_vendor_form(dialog, "Cancelled Vendor")
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_add, interact)
    qtbot.wait(50)

    assert conn.execute("SELECT 1 FROM vendors WHERE name='Cancelled Vendor'").fetchone() is None
    assert vendor_controller._total_vendors == 125


@pytest.mark.parametrize(
    ("name", "contact", "focused"),
    [
        ("", "Contact", "name"),
        ("   ", "Contact", "name"),
        ("Valid Vendor", "", "contact"),
        ("Valid Vendor", "   ", "contact"),
    ],
)
def test_vendor_form_validation_permutations(qtbot, name, contact, focused):
    dialog = VendorForm()
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.name, name)
    fill_plain_text(dialog.contact, contact)
    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    assert dialog.isVisible()
    assert dialog.payload() is None
    if focused == "name":
        assert not dialog.name.text().strip()
    else:
        assert not dialog.contact.toPlainText().strip()


def test_vendor_form_name_only_save_is_rejected(qtbot):
    dialog = VendorForm()
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.name, "Name Only Vendor")
    fill_plain_text(dialog.contact, "")
    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    assert dialog.isVisible()
    assert dialog.payload() is None
    assert dialog.contact.hasFocus()


def test_edit_existing_vendor_updates_table_details_and_database(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "Primary Account Vendor")

    def interact(dialog: VendorForm):
        assert dialog.name.text() == "Primary Account Vendor"
        fill_line_edit(dialog.name, "Primary Account Vendor Edited")
        fill_plain_text(dialog.contact, "edited contact")
        fill_plain_text(dialog.addr, "edited address")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_edit, interact)
    type_search(qtbot, vendor_controller, "Primary Account Vendor Edited", expected_total=1)
    select_vendor_by_name(qtbot, vendor_controller, "Primary Account Vendor Edited")

    assert view.details.lab_name.text() == "Primary Account Vendor Edited"
    assert view.details.lab_contact.text() == "edited contact"
    assert conn.execute("SELECT contact_info FROM vendors WHERE name='Primary Account Vendor Edited'").fetchone()[0] == "edited contact"
    assert any(call[1] == "Saved" for call in message_log)


def test_cancel_edit_keeps_existing_values(qtbot, vendor_controller, conn):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "Mixed CASE Vendor")

    def interact(dialog: VendorForm):
        fill_line_edit(dialog.name, "Should Not Save")
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_vendor_form(qtbot, view.btn_edit, interact)
    qtbot.wait(50)

    assert conn.execute("SELECT 1 FROM vendors WHERE name='Should Not Save'").fetchone() is None
    assert conn.execute("SELECT 1 FROM vendors WHERE name='Mixed CASE Vendor'").fetchone() is not None


def test_manage_accounts_button_emits_after_existing_vendor_click(qtbot):
    dialog = VendorForm(initial={"vendor_id": 9, "name": "Signal Vendor", "contact_info": "Contact", "address": ""})
    qtbot.addWidget(dialog)
    dialog.show()
    seen: list[tuple[str, int]] = []
    dialog.manageBankAccounts.connect(lambda vendor_id: seen.append(("accounts", vendor_id)))

    QTest.mouseClick(dialog.btn_manage_accounts, Qt.LeftButton)

    assert not hasattr(dialog, "btn_grant_credit")
    assert seen == [("accounts", 9)]


def test_ensure_vendor_exists_signal_for_new_vendor_operation(qtbot):
    dialog = VendorForm()
    qtbot.addWidget(dialog)
    dialog.show()
    seen: list[dict] = []

    def ensure(payload):
        seen.append(payload)
        dialog.set_vendor_id(77)

    dialog.ensureVendorExists.connect(ensure)
    dialog.manageBankAccounts.connect(lambda vendor_id: seen.append({"vendor_id": vendor_id}))
    fill_valid_vendor_form(dialog, "Ensure Signal Vendor")

    QTest.mouseClick(dialog.btn_manage_accounts, Qt.LeftButton)

    assert seen[0]["name"] == "Ensure Signal Vendor"
    assert seen[1] == {"vendor_id": 77}
