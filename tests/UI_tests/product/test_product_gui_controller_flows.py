from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from inventory_management.database.repositories.products_repo import Product, ProductsRepo
from inventory_management.modules.product.components import ProductSummary
from inventory_management.modules.product.model import ProductFilterProxy, ProductsTableModel

from .conftest import (
    clear_search,
    drive_product_form,
    fill_line_edit,
    ok_button,
    select_row_by_name,
    summary_values,
    table_text,
    type_search,
)


def test_controller_loads_product_rows_summary_and_selection_details(qtbot, product_controller):
    view = product_controller.view

    assert product_controller.base_model.rowCount() == 100
    assert product_controller._total_products == 121
    assert summary_values(view)["Products"] == "121"

    select_row_by_name(qtbot, view, "Alpha Widget 123")
    assert view.details.title.text() == "Alpha Widget 123"


def test_controller_add_flow_from_toolbar_reloads_table_summary_and_details(qtbot, product_controller, message_log):
    view = product_controller.view

    def interact(dialog):
        fill_line_edit(dialog.name, "Controller Add Flow")
        fill_line_edit(dialog.category, "Flows")
        fill_line_edit(dialog.min_stock, "2")
        fill_line_edit(dialog.desc, "added through controller")
        fill_line_edit(dialog.cmb_base.lineEdit(), "Case")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_add, interact)
    qtbot.waitUntil(lambda: product_controller._total_products == 122, timeout=3000)
    type_search(qtbot, product_controller, "Controller Add Flow", expected_total=1)
    select_row_by_name(qtbot, view, "Controller Add Flow")

    assert table_text(view, 0, 1) == "Controller Add Flow"
    assert view.details.fields["base_uom"].text() == "Case"
    assert summary_values(view)["Products"] == "122"
    assert any(call[1] == "Saved" for call in message_log)


def test_controller_delete_confirmation_cancel_keeps_row(qtbot, product_controller, monkeypatch, message_log):
    view = product_controller.view
    type_search(qtbot, product_controller, "No UoM Product", expected_total=1)
    select_row_by_name(qtbot, view, "No UoM Product")

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    QTest.mouseClick(view.btn_delete, Qt.LeftButton)
    qtbot.wait(50)

    assert product_controller._total_products == 1
    assert table_text(view, 0, 1) == "No UoM Product"
    assert not any(call[1] == "Deleted" for call in message_log)


def test_controller_delete_confirmation_accept_removes_row_and_updates_summary(qtbot, product_controller, monkeypatch, message_log):
    view = product_controller.view
    type_search(qtbot, product_controller, "No UoM Product", expected_total=1)
    select_row_by_name(qtbot, view, "No UoM Product")

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    QTest.mouseClick(view.btn_delete, Qt.LeftButton)
    qtbot.waitUntil(lambda: product_controller._total_products == 0, timeout=3000)

    assert view.table.model().rowCount() == 0
    assert summary_values(view)["Products"] == "120"
    assert any(call[1] == "Deleted" for call in message_log)


def test_controller_import_cancel_does_not_reload_or_change_summary(qtbot, product_controller, monkeypatch):
    view = product_controller.view
    before = summary_values(view)
    monkeypatch.setattr(
        "inventory_management.modules.product.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    QTest.mouseClick(view.btn_import, Qt.LeftButton)
    qtbot.wait(50)

    assert summary_values(view) == before
    assert product_controller._total_products == 121


def test_controller_import_button_uses_file_dialog_imports_and_reloads(qtbot, product_controller, monkeypatch, tmp_path, message_log):
    view = product_controller.view
    xlsx_path = tmp_path / "products.xlsx"
    xlsx_path.write_bytes(b"not read by fake importer")

    monkeypatch.setattr(
        "inventory_management.modules.product.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(xlsx_path), "Excel Workbooks (*.xlsx)"),
    )

    def fake_import(conn, path):
        assert path == xlsx_path
        repo = ProductsRepo(conn)
        pid = repo.create("Imported From GUI", "imported through toolbar", "Import", 0)
        case_id = repo.add_uom("Import Case")
        repo.set_base_uom(pid, case_id)
        return SimpleNamespace(imported_count=1, failed_count=0)

    monkeypatch.setattr(
        "inventory_management.scripts.bulk_import_products.import_products_from_xlsx",
        fake_import,
    )

    QTest.mouseClick(view.btn_import, Qt.LeftButton)
    qtbot.waitUntil(lambda: product_controller._total_products == 122, timeout=3000)
    type_search(qtbot, product_controller, "Imported From GUI", expected_total=1)

    assert table_text(view, 0, 1) == "Imported From GUI"
    assert table_text(view, 0, 5) == "Import Case"
    assert any(call[1] == "Import complete" for call in message_log)


def test_paging_after_add_and_delete_from_non_first_page(qtbot, product_controller, monkeypatch):
    view = product_controller.view
    QTest.mouseClick(view.btn_next_page, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=1000)

    def interact(dialog):
        fill_line_edit(dialog.name, "Non First Page Add")
        fill_line_edit(dialog.min_stock, "0")
        fill_line_edit(dialog.cmb_base.lineEdit(), "Piece")
        QTest.mouseClick(ok_button(dialog), Qt.LeftButton)

    drive_product_form(qtbot, view.btn_add, interact)
    qtbot.waitUntil(lambda: view.lbl_page.text() == "Page 2 / 2", timeout=3000)
    assert product_controller._total_products == 122

    type_search(qtbot, product_controller, "Non First Page Add", expected_total=1)
    select_row_by_name(qtbot, view, "Non First Page Add")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    QTest.mouseClick(view.btn_delete, Qt.LeftButton)
    qtbot.waitUntil(lambda: product_controller._total_products == 0, timeout=3000)

    clear_search(qtbot, product_controller, expected_total=121)
    assert view.lbl_page.text() == "Page 1 / 2"


def test_products_table_model_and_proxy_display_reset_and_filter_behavior():
    rows = [
        Product(1, "Alpha", "desc one", "Tools", 2, "Box", "Piece"),
        Product(2, "Beta", None, None, 0, "Kg", None),
    ]
    model = ProductsTableModel(rows)
    proxy = ProductFilterProxy()
    proxy.setSourceModel(model)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)

    assert model.rowCount() == 2
    assert model.columnCount() == 7
    assert model.headerData(1, Qt.Horizontal, Qt.DisplayRole) == "Name"
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "Alpha"
    assert model.data(model.index(0, 3), Qt.DisplayRole) == "2"

    proxy.setFilterFixedString("piece")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1), Qt.DisplayRole) == "Alpha"

    model.replace([rows[1]])
    assert model.rowCount() == 1
    assert model.product_ids() == [2]


def test_product_summary_dataclass_feeds_summary_bar(product_view):
    product_view.summary.set_summary(ProductSummary(total=4, low_stock=1, priced=2, with_uoms=3))

    assert summary_values(product_view) == {
        "Products": "4",
        "Low Stock": "1",
        "Priced": "2",
        "With UoMs": "3",
    }
