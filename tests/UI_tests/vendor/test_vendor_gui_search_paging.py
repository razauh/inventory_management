from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from .conftest import clear_search, select_vendor_by_name, table_text, type_search


def visible_vendor_rows(view) -> list[list[str]]:
    model = view.table.model()
    return [
        [str(model.data(model.index(row, col), Qt.DisplayRole)) for col in range(model.columnCount())]
        for row in range(model.rowCount())
    ]


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("Mixed CASE Vendor", "Mixed CASE Vendor"),
        ("mixed case vendor", "Mixed CASE Vendor"),
        ("CASE", "Mixed CASE Vendor"),
        ("12345", "Numeric Vendor 12345"),
        ("Numeric Contact", "Numeric Vendor 12345"),
        ("Block 12345", "Numeric Vendor 12345"),
        ("phone 111", "Primary Account Vendor"),
    ],
)
def test_search_filters_by_id_name_contact_address_and_substrings(qtbot, vendor_controller, query, expected_name):
    view = vendor_controller.view

    type_search(qtbot, vendor_controller, query, expected_total=1)

    assert view.table.model().rowCount() == 1, (
        f"query={query!r} expected_name={expected_name!r} "
        f"total={vendor_controller._total_vendors} rows={visible_vendor_rows(view)!r}"
    )
    assert table_text(view, 0, 1) == expected_name, (
        f"query={query!r} expected_name={expected_name!r} "
        f"rows={visible_vendor_rows(view)!r}"
    )


def test_search_one_character_and_clear_restore_paging(qtbot, vendor_controller):
    view = vendor_controller.view

    type_search(qtbot, vendor_controller, "P")
    assert vendor_controller._total_vendors > 1

    clear_search(qtbot, vendor_controller)
    assert vendor_controller._total_vendors == 125
    assert view.lbl_page.text() == "Page 1 / 2"
    assert view.table.model().rowCount() == 100


def test_search_no_results_then_clear_restores_selection_and_accounts(qtbot, vendor_controller):
    view = vendor_controller.view

    type_search(qtbot, vendor_controller, "nothing matches this", expected_total=0)
    assert view.details.lab_id.text() == "No vendor selected"

    clear_search(qtbot, vendor_controller)
    select_vendor_by_name(qtbot, vendor_controller, "Primary Account Vendor")

    assert view.details.lab_name.text() == "Primary Account Vendor"
    assert view.accounts_table.model().rowCount() == 1


def test_pager_next_previous_and_search_reduces_pages(qtbot, vendor_controller):
    view = vendor_controller.view

    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)
    assert view.btn_prev_page.isEnabled()
    assert not view.btn_next_page.isEnabled()
    assert view.table.model().rowCount() == 25

    QTest.mouseClick(view.btn_prev_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 1 / 2", timeout=1000)

    type_search(qtbot, vendor_controller, "Page Vendor 001", expected_total=1)
    assert view.lbl_page.text() == "Page 1 / 1"
    assert not view.btn_prev_page.isEnabled()
    assert not view.btn_next_page.isEnabled()


def test_page_change_selects_visible_vendor_and_refreshes_details(qtbot, vendor_controller):
    view = vendor_controller.view

    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)

    assert view.details.lab_name.text()
    assert view.details.lab_id.text().startswith("Vendor #")
