from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from inventory_management.modules.product.model import ProductsTableModel

from .conftest import (
    all_table_text,
    click_table_row,
    select_row_by_name,
    summary_values,
    table_text,
    type_search,
)


def test_product_view_initial_state_has_real_table_summary_pager_and_disabled_actions(product_controller):
    view = product_controller.view

    assert view.search.placeholderText() == "Search products by id, name, category, description, or UoM"
    assert [view.table.model().headerData(i, Qt.Horizontal, Qt.DisplayRole) for i in range(7)] == ProductsTableModel.HEADERS
    assert view.table.model().columnCount() == 7
    assert view.table.model().rowCount() == 100
    assert view.lbl_page.text() == "Page 1 / 2"
    assert not view.btn_prev_page.isEnabled()
    assert view.btn_next_page.isEnabled()
    assert summary_values(view) == {
        "Products": "121",
        "Low Stock": "1",
        "Priced": "2",
        "With UoMs": "120",
    }
    assert view.btn_add.isEnabled()
    assert view.btn_import.isEnabled()
    assert not view.btn_edit.isEnabled()
    assert not view.btn_delete.isEnabled()
    assert not view.btn_price.isEnabled()
    assert view.details.title.text() == "No product selected"


def test_table_renders_seeded_product_data_after_real_search_typing(qtbot, product_controller):
    view = product_controller.view

    type_search(qtbot, product_controller, "Alpha Widget", expected_total=1)

    assert view.table.model().rowCount() == 1
    assert table_text(view, 0, 1) == "Alpha Widget 123"
    assert table_text(view, 0, 2) == "Tools"
    assert table_text(view, 0, 3) == "10"
    assert table_text(view, 0, 4) == "left handed tool numeric 123"
    assert table_text(view, 0, 5) == "Box"
    assert "Piece" in table_text(view, 0, 6)
    assert "Pack" in table_text(view, 0, 6)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Alpha Widget 123", {"category": "Tools", "base_uom": "Box", "alt_uoms": "Piece", "sale_price": "25.50", "cost_price": "4.50"}),
        ("Vitamin CAPS Mixed", {"category": "Health", "base_uom": "Bottle", "alt_uoms": "Tablet", "sale_price": "18.75", "cost_price": "6.50"}),
        ("Long Description Ledger", {"category": "—", "base_uom": "Sheet", "alt_uoms": "—", "notes": "long description"}),
        ("No UoM Product", {"category": "Legacy", "base_uom": "—", "alt_uoms": "—"}),
    ],
)
def test_details_panel_updates_for_selection_permutations(qtbot, product_controller, name, expected):
    view = product_controller.view
    type_search(qtbot, product_controller, name, expected_total=1)

    select_row_by_name(qtbot, view, name)

    assert view.details.title.text() == name
    assert expected["category"] in view.details.fields["category"].text()
    assert view.details.fields["base_uom"].text() == expected["base_uom"]
    assert expected["alt_uoms"] in view.details.fields["alt_uoms"].text()
    if "sale_price" in expected:
        assert view.details.fields["sale_price"].text() == expected["sale_price"]
    if "cost_price" in expected:
        assert view.details.fields["cost_price"].text() == expected["cost_price"]
    if "notes" in expected:
        assert expected["notes"] in view.details.notes.text()
    assert view.btn_edit.isEnabled()
    assert view.btn_delete.isEnabled()
    assert view.btn_price.isEnabled()


def test_selecting_another_product_replaces_details_panel(qtbot, product_controller):
    view = product_controller.view

    type_search(qtbot, product_controller, "Widget", expected_total=1)
    select_row_by_name(qtbot, view, "Alpha Widget 123")
    assert view.details.title.text() == "Alpha Widget 123"

    type_search(qtbot, product_controller, "answers", expected_total=1)
    select_row_by_name(qtbot, view, "ielts advantage with answers")

    assert view.details.title.text() == "ielts advantage with answers"
    assert view.details.fields["category"].text() == "Books"
    assert view.details.notes.text() == "middle word answers reading guide"


def test_table_sorting_changes_visible_order_through_header_click(qtbot, product_controller):
    view = product_controller.view
    before = [row[1] for row in all_table_text(view)[:5]]

    header = view.table.horizontalHeader()
    x = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, header.height() // 2))
    qtbot.wait(50)

    after = [row[1] for row in all_table_text(view)[:5]]
    assert after != before


def test_single_row_selection_replaces_previous_selection(qtbot, product_controller):
    view = product_controller.view
    type_search(qtbot, product_controller, "Page Seed", expected_total=115)

    click_table_row(qtbot, view, 0)
    assert len(view.table.selectionModel().selectedRows()) == 1
    first_id = table_text(view, 0, 0)

    click_table_row(qtbot, view, 1)
    selected = view.table.selectionModel().selectedRows()
    assert len(selected) == 1
    assert table_text(view, selected[0].row(), 0) != first_id


@pytest.mark.xfail(reason="ProductController passes 0.0 to details when no price exists, so panel shows 0.00 instead of no-price dash.")
def test_details_panel_shows_dash_for_product_without_price_data(qtbot, product_controller):
    view = product_controller.view
    type_search(qtbot, product_controller, "ielts advantage", expected_total=1)
    select_row_by_name(qtbot, view, "ielts advantage with answers")

    assert view.details.fields["sale_price"].text() == "—"
    assert view.details.fields["cost_price"].text() == "—"
