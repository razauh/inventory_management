from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from inventory_management.modules.product.form import ProductForm, UomPicker

from .conftest import (
    drive_product_form,
    fill_line_edit,
    ok_button,
    cancel_button,
    select_row_by_name,
    summary_values,
    table_text,
    type_search,
)


def fill_combo(combo, text: str) -> None:
    fill_line_edit(combo.lineEdit(), text)


def fill_valid_form(dialog: ProductForm, name: str = "GUI Added Product") -> None:
    fill_line_edit(dialog.name, name)
    fill_line_edit(dialog.category, "GUI Category")
    fill_line_edit(dialog.min_stock, "7")
    fill_line_edit(dialog.desc, "created by real GUI test")
    fill_combo(dialog.cmb_base, "Box")


def test_open_add_product_dialog_and_save_valid_product(qtbot, product_controller, conn, message_log):
    view = product_controller.view

    def interact(dialog: ProductForm):
        fill_valid_form(dialog)
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_add, interact)
    qtbot.waitUntil(lambda: product_controller._total_products == 122, timeout=3000)
    type_search(qtbot, product_controller, "GUI Added Product", expected_total=1)

    assert table_text(view, 0, 1) == "GUI Added Product"
    assert table_text(view, 0, 5) == "Box"
    assert summary_values(view)["Products"] == "122"
    row = conn.execute("SELECT name FROM products WHERE name='GUI Added Product'").fetchone()
    assert row is not None
    assert any(call[1] == "Saved" for call in message_log)


def test_cancel_add_product_keeps_table_and_database_unchanged(qtbot, product_controller, conn):
    view = product_controller.view

    def interact(dialog: ProductForm):
        fill_valid_form(dialog, "Cancelled Product")
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_add, interact)
    qtbot.wait(50)

    assert product_controller._total_products == 121
    assert conn.execute("SELECT 1 FROM products WHERE name='Cancelled Product'").fetchone() is None


@pytest.mark.parametrize(
    ("name", "min_stock", "base_uom", "field", "message"),
    [
        ("", "1", "Box", "name_error", "Name is required"),
        ("Bad Min", "abc", "Box", "min_stock_error", "Enter a valid non-negative number"),
        ("Bad Negative", "-1", "Box", "min_stock_error", "Enter a valid non-negative number"),
        ("No Base", "1", "", "base_uom_error", "Base UoM is required"),
    ],
)
def test_product_form_validation_permutations(qtbot, product_repo, name, min_stock, base_uom, field, message):
    dialog = ProductForm(repo=product_repo)
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.name, name)
    fill_line_edit(dialog.min_stock, min_stock)
    fill_combo(dialog.cmb_base, base_uom)
    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    assert dialog.isVisible()
    label = getattr(dialog, field)
    assert label.text() == message


@pytest.mark.parametrize(
    ("base_text", "expected_key"),
    [
        ("Piece", "uom_id"),
        ("New GUI Unit", "uom_name"),
        ("  Pack  ", "uom_id"),
    ],
)
def test_uom_picker_existing_new_and_trimmed_input(qtbot, product_repo, base_text, expected_key):
    picker = UomPicker(product_repo)
    qtbot.addWidget(picker)
    picker.show()

    fill_combo(picker, base_text)
    ref = picker.current_uom_ref()

    assert ref is not None
    assert expected_key in ref
    assert (ref.get("unit_name") or ref.get("uom_name")).strip() == base_text.strip()


def test_uom_picker_empty_input_returns_none(qtbot, product_repo):
    picker = UomPicker(product_repo)
    qtbot.addWidget(picker)
    picker.show()

    fill_combo(picker, "")

    assert picker.current_uom_ref() is None
    assert picker.current_uom_id() is None


def test_uom_picker_case_difference_returns_existing_uom(qtbot, product_repo):
    picker = UomPicker(product_repo)
    qtbot.addWidget(picker)
    picker.show()

    fill_combo(picker, "piece")

    assert "uom_id" in picker.current_uom_ref()


def test_sales_alternates_table_add_multiple_duplicate_remove_and_read_only(qtbot, product_repo, message_log):
    dialog = ProductForm(repo=product_repo)
    qtbot.addWidget(dialog)
    dialog.show()

    fill_combo(dialog.cmb_base, "Box")
    QTest.mouseClick(dialog.chk_sales, Qt.LeftButton)
    assert dialog.cmb_sales_alt.isEnabled()
    assert dialog.tbl_sales.isEnabled()

    fill_combo(dialog.cmb_sales_alt, "Piece")
    fill_line_edit(dialog.txt_sales_factor, "100")
    QTest.mouseClick(dialog.btn_sales_add, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 1
    assert dialog.tbl_sales.horizontalHeaderItem(0).text() == "UoM"
    assert dialog.tbl_sales.horizontalHeaderItem(1).text() == "Units per base"
    assert dialog.tbl_sales.item(0, 0).text() == "Piece"
    assert dialog.tbl_sales.item(0, 1).text() == "100"
    assert dialog.tbl_sales.editTriggers() == QAbstractItemView.NoEditTriggers

    fill_combo(dialog.cmb_sales_alt, "Pack")
    fill_line_edit(dialog.txt_sales_factor, "4")
    QTest.mouseClick(dialog.btn_sales_add, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 2

    fill_combo(dialog.cmb_sales_alt, "Pack")
    fill_line_edit(dialog.txt_sales_factor, "8")
    QTest.mouseClick(dialog.btn_sales_add, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 2
    assert dialog.tbl_sales.item(1, 1).text() == "8"

    dialog.tbl_sales.selectRow(1)
    QTest.mouseClick(dialog.btn_remove, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 1

    dialog.tbl_sales.clearSelection()
    QTest.mouseClick(dialog.btn_remove, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 1
    assert any("Please select a Sales alternate" in call[2] for call in message_log)


@pytest.mark.parametrize("factor", ["abc", "0", "-4"])
def test_sales_alternate_rejects_invalid_zero_and_negative_factor(qtbot, product_repo, message_log, factor):
    dialog = ProductForm(repo=product_repo)
    qtbot.addWidget(dialog)
    dialog.show()

    fill_combo(dialog.cmb_base, "Box")
    QTest.mouseClick(dialog.chk_sales, Qt.LeftButton)
    fill_combo(dialog.cmb_sales_alt, "Piece")
    fill_line_edit(dialog.txt_sales_factor, factor)
    QTest.mouseClick(dialog.btn_sales_add, Qt.LeftButton)

    assert dialog.tbl_sales.rowCount() == 0
    assert any("greater than zero" in call[2] for call in message_log)


def test_disable_sales_alternates_excludes_rows_from_payload(qtbot, product_repo):
    dialog = ProductForm(repo=product_repo)
    qtbot.addWidget(dialog)
    dialog.show()

    fill_line_edit(dialog.name, "No Sales Alt")
    fill_line_edit(dialog.min_stock, "")
    fill_combo(dialog.cmb_base, "Box")
    QTest.mouseClick(dialog.chk_sales, Qt.LeftButton)
    fill_combo(dialog.cmb_sales_alt, "Piece")
    fill_line_edit(dialog.txt_sales_factor, "100")
    QTest.mouseClick(dialog.btn_sales_add, Qt.LeftButton)
    assert dialog.tbl_sales.rowCount() == 1

    QTest.mouseClick(dialog.chk_sales, Qt.LeftButton)
    QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    assert not dialog.isVisible()
    assert dialog.payload()["uoms"]["enabled_sales"] is False
    assert dialog.payload()["uoms"]["sales_alts"] == []


def test_edit_existing_product_from_gui_updates_table_and_details(qtbot, product_controller, message_log):
    view = product_controller.view
    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")

    def interact(dialog: ProductForm):
        assert dialog.name.text() == "Alpha Widget 123"
        fill_line_edit(dialog.name, "Alpha Widget Edited")
        fill_line_edit(dialog.category, "Edited Tools")
        fill_line_edit(dialog.min_stock, "3")
        fill_line_edit(dialog.desc, "edited from gui")
        fill_combo(dialog.cmb_base, "Carton")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_edit, interact)
    type_search(qtbot, product_controller, "Alpha Widget Edited", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget Edited")

    assert table_text(view, 0, 1) == "Alpha Widget Edited"
    assert table_text(view, 0, 2) == "Edited Tools"
    assert table_text(view, 0, 5) == "Carton"
    assert view.details.title.text() == "Alpha Widget Edited"
    assert view.details.notes.text() == "edited from gui"
    assert any(call[1] == "Saved" for call in message_log)


def test_cancel_edit_keeps_original_values(qtbot, product_controller):
    view = product_controller.view
    type_search(qtbot, product_controller, "Vitamin CAPS", expected_total=1)
    select_row_by_name(qtbot, view, "Vitamin CAPS Mixed")

    def interact(dialog: ProductForm):
        fill_line_edit(dialog.name, "Should Not Persist")
        QTest.mouseClick(cancel_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_edit, interact)
    type_search(qtbot, product_controller, "Vitamin CAPS", expected_total=1)

    assert table_text(view, 0, 1) == "Vitamin CAPS Mixed"
