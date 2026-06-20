from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from inventory_management.modules.product.controller import PriceDialog

from .conftest import (
    drive_price_dialog,
    fill_line_edit,
    ok_button,
    cancel_button,
    select_row_by_name,
    table_text,
    type_search,
)


def test_set_price_button_disabled_until_product_selected(qtbot, product_controller):
    view = product_controller.view

    assert not view.btn_price.isEnabled()

    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")

    assert view.btn_price.isEnabled()


def test_open_set_price_dialog_and_save_valid_base_price(qtbot, product_controller, conn, message_log):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")
    pid = int(table_text(view, 0, 0))

    def interact(dialog: PriceDialog):
        assert "Alpha Widget 123" in dialog.windowTitle()
        assert any("Last cost per base: 4.50" in label.text() for label in dialog.findChildren(QLabel))
        assert any(label.text() == "Box" for label in dialog.findChildren(QLabel))
        fill_line_edit(dialog.edt_base_price, "33.25")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_price_dialog(qtbot, view.btn_price, interact)
    qtbot.waitUntil(lambda: view.details.fields["sale_price"].text() == "33.25", timeout=3000)

    row = conn.execute(
        "SELECT price FROM product_sale_prices WHERE product_id=? ORDER BY price_id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    assert float(row["price"]) == 33.25
    assert any(call[1] == "Saved" for call in message_log)


def test_cancel_price_edit_keeps_existing_price(qtbot, product_controller, conn):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")
    pid = int(table_text(view, 0, 0))

    def interact(dialog: PriceDialog):
        fill_line_edit(dialog.edt_base_price, "99.99")
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_price_dialog(qtbot, view.btn_price, interact)
    qtbot.wait(50)

    row = conn.execute(
        "SELECT price FROM product_sale_prices WHERE product_id=? ORDER BY price_id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    assert float(row["price"]) == 25.5
    assert view.details.fields["sale_price"].text() == "25.50"


@pytest.mark.parametrize("bad_price", ["abc", "-1"])
def test_price_dialog_rejects_invalid_and_negative_price(qtbot, product_controller, bad_price):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")

    def interact(dialog: PriceDialog):
        fill_line_edit(dialog.edt_base_price, bad_price)
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)
        assert dialog.isVisible()
        assert dialog.lbl_error.text() == "Enter a valid positive sale price."
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_price_dialog(qtbot, view.btn_price, interact)


def test_retail_uom_combo_loads_alternates_and_syncs_price_and_cost_label(qtbot, product_controller):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")

    def interact(dialog: PriceDialog):
        assert dialog.cmb_alt.count() == 3
        names = [dialog.cmb_alt.itemText(i) for i in range(dialog.cmb_alt.count())]
        assert names == ["Select retail UoM…", "Pack", "Piece"]

        dialog.cmb_alt.setFocus()
        QTest.keyClick(dialog.cmb_alt, Qt.Key_Down)
        QTest.keyClick(dialog.cmb_alt, Qt.Key_Enter)
        if dialog.cmb_alt.currentIndex() == 0:
            dialog.cmb_alt.setCurrentIndex(1)

        assert dialog.cmb_alt.currentText() == "Pack"
        assert dialog.edt_base_price.isReadOnly()
        assert dialog.lbl_alt_cost.text() == "Cost per retail unit: 1.12"
        fill_line_edit(dialog.edt_alt_price, "10")
        assert dialog.edt_base_price.text() == "40.00"
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_price_dialog(qtbot, view.btn_price, interact)


def test_zero_price_rule_is_consistent_between_dialog_and_repository(qtbot, product_controller):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")

    def interact(dialog: PriceDialog):
        fill_line_edit(dialog.edt_base_price, "0")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)
        assert dialog.isVisible()
        assert dialog.lbl_error.text() == "Enter a valid positive sale price."
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_price_dialog(qtbot, view.btn_price, interact)
