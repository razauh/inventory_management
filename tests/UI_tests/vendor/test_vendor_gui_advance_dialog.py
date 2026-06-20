from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from inventory_management.modules.vendor.payment_dialog import _VendorMoneyDialog

from .conftest import (
    drive_money_dialog,
    fill_line_edit,
    select_vendor_by_name,
    set_combo_text,
    vendor_id_by_name,
)


def test_record_advance_requires_selected_vendor(qtbot, vendor_controller, message_log):
    view = vendor_controller.view
    view.table.clearSelection()

    QTest.mouseClick(view.btn_apply_advance, Qt.LeftButton)
    qtbot.wait(50)

    assert any(call[1] == "Select" and "select a vendor" in call[2] for call in message_log)


@pytest.mark.parametrize(
    ("amount", "expected_error"),
    [
        ("", "Please enter a numeric amount."),
        ("abc", "Please enter a numeric amount."),
        ("0", "Please enter a valid payment amount greater than 0."),
    ],
)
def test_vendor_money_dialog_amount_validation(qtbot, conn, message_log, amount, expected_error):
    vendor_id = vendor_id_by_name(conn, "Advance Vendor")
    dialog = _VendorMoneyDialog(vendor_id=vendor_id, vendors=None, defaults={"vendor_display": "Advance Vendor"})
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.amount, amount)
    QTest.mouseClick(dialog.saveBtn, Qt.LeftButton)

    assert dialog.isVisible()
    assert expected_error in dialog.errorLabel.text()


@pytest.mark.parametrize(
    ("method", "company_enabled", "vendor_enabled", "instr_enabled"),
    [
        ("Cash", False, False, False),
        ("Bank Transfer", True, True, True),
        ("Cheque", True, False, True),
        ("Cross Cheque", True, True, True),
        ("Cash Deposit", False, True, True),
        ("Other", True, True, True),
    ],
)
def test_payment_method_field_permutations(qtbot, conn, method, company_enabled, vendor_enabled, instr_enabled):
    vendor_id = vendor_id_by_name(conn, "Advance Vendor")
    dialog = _VendorMoneyDialog(vendor_id=vendor_id, vendors=None, defaults={"vendor_display": "Advance Vendor"})
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.amount, "10")
    set_combo_text(dialog.method, method)
    qtbot.wait(80)

    assert dialog.company_acct.isEnabled() is company_enabled
    assert dialog.vendor_acct.isEnabled() is vendor_enabled
    assert dialog.instr_no.isEnabled() is instr_enabled


def test_record_cash_advance_from_toolbar_persists_and_updates_details(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "No Account Vendor 500")
    vendor_id = vendor_id_by_name(conn, "No Account Vendor 500")

    def interact(dialog):
        assert "No Account Vendor 500" in dialog.vendorLabel.text()
        fill_line_edit(dialog.amount, "42.50")
        set_combo_text(dialog.method, "Cash")
        fill_line_edit(dialog.notes, "cash advance gui")
        QTest.mouseClick(dialog.saveBtn, Qt.LeftButton)

    drive_money_dialog(qtbot, view.btn_apply_advance, interact)
    qtbot.waitUntil(lambda: view.details.lblAvailableAdvanceValue.text() == "42.50", timeout=3000)

    row = conn.execute(
        "SELECT amount, method, notes FROM vendor_advances WHERE vendor_id=? AND notes='cash advance gui'",
        (vendor_id,),
    ).fetchone()
    assert float(row["amount"]) == pytest.approx(42.5)
    assert row["method"] == "Cash"
    assert any(call[1] == "Recorded" for call in message_log)


def test_bank_transfer_validation_then_save_with_temp_vendor_account(qtbot, vendor_controller, conn, message_log):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "No Account Vendor 500")
    vendor_id = vendor_id_by_name(conn, "No Account Vendor 500")

    def interact(dialog):
        fill_line_edit(dialog.amount, "55")
        set_combo_text(dialog.method, "Bank Transfer")
        dialog.vendor_acct.setCurrentIndex(dialog.vendor_acct.findData(dialog.TEMP_BANK_KEY))
        QTest.mouseClick(dialog.saveBtn, Qt.LeftButton)
        assert dialog.isVisible()
        assert "please enter the instrument" in dialog.errorLabel.text()
        if dialog.company_acct.count() > 0:
            dialog.company_acct.setCurrentIndex(0)
        fill_line_edit(dialog.instr_no, "TXN55")
        fill_line_edit(dialog.temp_bank_name, "Temp Vendor Bank")
        fill_line_edit(dialog.temp_bank_number, "TEMP123")
        QTest.mouseClick(dialog.saveBtn, Qt.LeftButton)
        assert not dialog.isVisible()

    drive_money_dialog(qtbot, view.btn_apply_advance, interact)

    row = conn.execute(
        "SELECT instrument_no, temp_vendor_bank_name, temp_vendor_bank_number FROM vendor_advances WHERE vendor_id=? AND amount=55",
        (vendor_id,),
    ).fetchone()
    assert row["instrument_no"] == "TXN55"
    assert row["temp_vendor_bank_name"] == "Temp Vendor Bank"
    assert row["temp_vendor_bank_number"] == "TEMP123"
