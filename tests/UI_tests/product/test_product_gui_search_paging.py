from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from .conftest import clear_search, select_row_by_name, table_text, type_search


@pytest.mark.parametrize(
    ("field", "term", "expected_name"),
    [
        ("product id", "121", "Alpha Widget 123"),
        ("name exact", "Alpha Widget 123", "Alpha Widget 123"),
        ("name middle", "answers", "ielts advantage with answers"),
        ("category", "TOOLS", "Alpha Widget 123"),
        ("description", "reading guide", "ielts advantage with answers"),
        ("base uom", "sheet", "Long Description Ledger"),
        ("alternate uom", "pack", "Alpha Widget 123"),
    ],
)
def test_search_matches_all_supported_fields_with_real_typing(qtbot, product_controller, field, term, expected_name):
    view = product_controller.view

    type_search(qtbot, product_controller, term, expected_total=1)

    assert view.table.model().rowCount() == 1, field
    assert table_text(view, 0, 1) == expected_name


@pytest.mark.parametrize(
    ("term", "expected_min"),
    [
        ("P", 100),
        ("seed 00", 9),
        ("SeEd", 100),
    ],
)
def test_search_one_character_partial_and_case_insensitive(qtbot, product_controller, term, expected_min):
    view = product_controller.view

    type_search(qtbot, product_controller, term)

    assert product_controller._total_products >= expected_min
    assert view.table.model().rowCount() >= 1


def test_empty_search_and_clear_search_restore_full_first_page(qtbot, product_controller):
    view = product_controller.view
    assert view.table.model().rowCount() == 100

    type_search(qtbot, product_controller, "answers", expected_total=1)
    assert view.table.model().rowCount() == 1

    clear_search(qtbot, product_controller)

    assert view.search.text() == ""
    assert product_controller._total_products == 121
    assert view.table.model().rowCount() == 100
    assert view.lbl_page.text() == "Page 1 / 2"


def test_no_results_search_updates_table_buttons_and_details(qtbot, product_controller):
    view = product_controller.view

    type_search(qtbot, product_controller, "zz-no-product-here", expected_total=0)

    assert view.table.model().rowCount() == 0
    assert view.details.title.text() == "No products found"
    assert view.details.subtitle.text() == "Clear the search to see products again."
    assert not view.btn_edit.isEnabled()
    assert not view.btn_delete.isEnabled()
    assert not view.btn_price.isEnabled()
    assert view.lbl_page.text() == "Page 1 / 1"


def test_search_selection_updates_details_panel(qtbot, product_controller):
    view = product_controller.view

    type_search(qtbot, product_controller, "answers", expected_total=1)
    select_row_by_name(qtbot, view, "ielts advantage with answers")

    assert view.details.title.text() == "ielts advantage with answers"
    assert view.details.fields["category"].text() == "Books"


def test_pager_initial_next_previous_and_disabled_states(qtbot, product_controller):
    view = product_controller.view

    assert view.lbl_page.text() == "Page 1 / 2"
    assert not view.btn_prev_page.isEnabled()
    assert view.btn_next_page.isEnabled()

    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)

    assert view.table.model().rowCount() == 21
    assert view.btn_prev_page.isEnabled()
    assert not view.btn_next_page.isEnabled()

    QTest.mouseClick(view.btn_prev_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 1 / 2", timeout=1000)

    assert view.table.model().rowCount() == 100
    assert not view.btn_prev_page.isEnabled()
    assert view.btn_next_page.isEnabled()


def test_paging_combined_with_search_and_clear(qtbot, product_controller):
    view = product_controller.view

    type_search(qtbot, product_controller, "Page Seed", expected_total=115)
    assert view.lbl_page.text() == "Page 1 / 2"

    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)
    select_row_by_name(qtbot, view, "Page Seed")
    page_2_title = view.details.title.text()

    type_search(qtbot, product_controller, "Page Seed 001", expected_total=1)
    assert view.lbl_page.text() == "Page 1 / 1"
    assert table_text(view, 0, 1) == "Page Seed 001"

    clear_search(qtbot, product_controller)
    assert view.lbl_page.text() == "Page 1 / 2"
    assert page_2_title != view.details.title.text()


def test_page_navigation_clears_selection_when_selected_product_not_on_page(qtbot, product_controller):
    view = product_controller.view

    select_row_by_name(qtbot, view, "Alpha Widget 123")
    assert view.details.title.text() == "Alpha Widget 123"

    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)

    assert view.details.title.text() == "No product selected"
    assert not view.btn_edit.isEnabled()
