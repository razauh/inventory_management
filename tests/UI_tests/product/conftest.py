from __future__ import annotations

import sqlite3
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QMessageBox

from inventory_management.database.schema import init_schema
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.modules.product.controller import PriceDialog, ProductController
from inventory_management.modules.product.form import ProductForm


LOG_DIR = Path(__file__).resolve().parents[3] / ".logs"
LOG_PATH = LOG_DIR / "product_gui_tests.log"


def log_event(message: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        handle.flush()


def widget_state() -> str:
    try:
        widgets = []
        for widget in QApplication.topLevelWidgets():
            widgets.append(
                f"{type(widget).__name__}(visible={widget.isVisible()}, title={widget.windowTitle()!r})"
            )
        return ", ".join(widgets) or "none"
    except Exception as exc:
        return f"unavailable: {exc}"


def pytest_configure(config):
    LOG_DIR.mkdir(exist_ok=True)
    LOG_PATH.write_text("product GUI test log\n", encoding="utf-8")


def pytest_runtest_logstart(nodeid, location):
    log_event(f"START {nodeid}")


def pytest_runtest_logreport(report):
    if report.when == "call":
        outcome = report.outcome.upper()
        if hasattr(report, "wasxfail"):
            outcome = "XPASS" if report.passed else "XFAIL"
        log_event(f"{outcome} {report.nodeid} duration={report.duration:.3f}s")
        if report.failed:
            log_event(f"FAILED_STATE {report.nodeid} top_levels={widget_state()}")


@pytest.fixture(autouse=True)
def _product_gui_test_log(request):
    log_event(f"SETUP {request.node.nodeid}")
    start = time.monotonic()
    yield
    log_event(
        f"TEARDOWN {request.node.nodeid} elapsed={time.monotonic() - start:.3f}s "
        f"top_levels={widget_state()}"
    )


@pytest.fixture()
def conn(tmp_path: Path, product_db_template: Path):
    db_path = tmp_path / "product_gui.sqlite3"
    log_event(f"DB_COPY {product_db_template} -> {db_path}")
    shutil.copyfile(product_db_template, db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


@pytest.fixture(scope="session")
def product_db_template(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("product_gui_template") / "template.sqlite3"
    log_event(f"DB_TEMPLATE_INIT {db_path}")
    init_schema(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    seed_product_gui_db(con)
    con.execute("PRAGMA wal_checkpoint(FULL)")
    con.close()
    log_event(f"DB_TEMPLATE_READY {db_path}")
    return db_path


@pytest.fixture()
def product_controller(qtbot, conn):
    log_event("CONTROLLER_CREATE")
    controller = ProductController(conn)
    view = controller.get_widget()
    qtbot.addWidget(view)
    view.resize(1200, 760)
    view.show()
    qtbot.waitExposed(view)
    wait_for_products(qtbot, controller)
    log_event(
        f"CONTROLLER_READY rows={controller.base_model.rowCount()} "
        f"total={controller._total_products} page={controller.view.lbl_page.text()!r}"
    )
    return controller


@pytest.fixture()
def product_view(product_controller):
    return product_controller.view


@pytest.fixture()
def product_repo(conn):
    return ProductsRepo(conn)


@pytest.fixture()
def message_log(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def record(kind):
        def inner(parent, title, text, *args, **kwargs):
            calls.append((kind, str(title), str(text)))
            log_event(f"MESSAGE {kind} title={title!r} text={text!r}")
            if kind == "question":
                return QMessageBox.StandardButton.Yes
            if kind == "warning":
                return QMessageBox.StandardButton.Yes
            return 0

        return inner

    monkeypatch.setattr(QMessageBox, "information", record("information"))
    monkeypatch.setattr(QMessageBox, "critical", record("critical"))
    monkeypatch.setattr(QMessageBox, "warning", record("warning"))
    monkeypatch.setattr(QMessageBox, "question", record("question"))
    return calls


def seed_product_gui_db(conn: sqlite3.Connection) -> None:
    log_event("SEED_START")
    repo = ProductsRepo(conn)
    uom_ids = {name: repo.add_uom(name) for name in [
        "Box",
        "Bottle",
        "Case",
        "Carton",
        "Kg",
        "Pack",
        "Piece",
        "Sheet",
        "Tablet",
    ]}

    for i in range(1, 116):
        pid = repo.create(
            name=f"Page Seed {i:03d}",
            description=f"bulk paging searchable row {i:03d}",
            category="Paging",
            min_stock_level=0,
        )
        repo.set_base_uom(pid, uom_ids["Piece"])

    samples = [
        {
            "name": "No UoM Product",
            "description": "legacy row without unit mapping",
            "category": "Legacy",
            "min_stock": 0,
            "base": None,
            "alts": [],
            "stock": None,
            "price": None,
        },
        {
            "name": "Normal Stock Bolt",
            "description": "has stock over minimum",
            "category": "Hardware",
            "min_stock": 5,
            "base": "Piece",
            "alts": [],
            "stock": (10, 1.25),
            "price": None,
        },
        {
            "name": "Long Description Ledger",
            "description": "This product has a long description used by the details panel so wrapping and notes stay visible.",
            "category": "",
            "min_stock": 0,
            "base": "Sheet",
            "alts": [],
            "stock": None,
            "price": None,
        },
        {
            "name": "Vitamin CAPS Mixed",
            "description": "Health bottle with tablet alternate",
            "category": "Health",
            "min_stock": 0,
            "base": "Bottle",
            "alts": [("Tablet", 0.01)],
            "stock": (0, 6.5),
            "price": 18.75,
        },
        {
            "name": "ielts advantage with answers",
            "description": "middle word answers reading guide",
            "category": "Books",
            "min_stock": 0,
            "base": "Piece",
            "alts": [],
            "stock": None,
            "price": None,
        },
        {
            "name": "Alpha Widget 123",
            "description": "left handed tool numeric 123",
            "category": "Tools",
            "min_stock": 10,
            "base": "Box",
            "alts": [("Piece", 0.01), ("Pack", 0.25)],
            "stock": (3, 4.5),
            "price": 25.5,
        },
    ]
    product_ids: dict[str, int] = {}
    for item in samples:
        pid = repo.create(
            name=item["name"],
            description=item["description"],
            category=item["category"] or None,
            min_stock_level=item["min_stock"],
        )
        product_ids[item["name"]] = pid
        if item["base"]:
            repo.set_base_uom(pid, uom_ids[item["base"]])
        for name, factor in item["alts"]:
            repo.add_alt_uom(pid, uom_ids[name], factor)
        if item["stock"]:
            qty, cost = item["stock"]
            conn.execute(
                """
                INSERT INTO stock_valuation_history(
                    product_id, valuation_date, quantity, unit_value, total_value, valuation_method
                )
                VALUES (?, '2026-01-01', ?, ?, ?, 'moving_average')
                """,
                (pid, qty, cost, qty * cost),
            )
        if item["price"] is not None:
            repo.set_manual_sale_price_base(pid, item["price"])
    conn.execute(
        "INSERT INTO vendors(name, contact_info, address) VALUES ('GUI Vendor', 'test', '')"
    )
    vendor_id = int(conn.execute("SELECT vendor_id FROM vendors WHERE name='GUI Vendor'").fetchone()[0])
    conn.execute(
        """
        INSERT INTO purchases(
            purchase_id, vendor_id, date, total_amount, payment_status, paid_amount
        )
        VALUES ('PGUI-001', ?, '2026-01-02', 45, 'paid', 45)
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items(
            purchase_id, product_id, quantity, uom_id, purchase_price, sale_price
        )
        VALUES ('PGUI-001', ?, 10, ?, 4.5, 25.5)
        """,
        (product_ids["Alpha Widget 123"], uom_ids["Box"]),
    )
    conn.commit()
    log_event("SEED_DONE products=121")


def wait_for_products(qtbot, controller: ProductController, min_rows: int = 1) -> None:
    log_event(f"WAIT_PRODUCTS min_rows={min_rows}")
    qtbot.waitUntil(lambda: controller.base_model.rowCount() >= min_rows, timeout=3000)
    qtbot.wait(20)
    log_event(f"WAIT_PRODUCTS_DONE rows={controller.base_model.rowCount()}")


def wait_for_search(qtbot, controller: ProductController, expected_total: int | None = None) -> None:
    log_event(f"WAIT_SEARCH text={controller.view.search.text()!r} expected_total={expected_total!r}")
    qtbot.wait(220)
    if expected_total is None:
        log_event(
            f"WAIT_SEARCH_DONE total={controller._total_products} rows={controller.view.table.model().rowCount()}"
        )
        return
    qtbot.waitUntil(lambda: controller._total_products == expected_total, timeout=3000)
    qtbot.wait(20)
    log_event(
        f"WAIT_SEARCH_DONE total={controller._total_products} rows={controller.view.table.model().rowCount()}"
    )


def table_text(view, row: int, column: int) -> str:
    model = view.table.model()
    return str(model.data(model.index(row, column), Qt.DisplayRole))


def all_table_text(view) -> list[list[str]]:
    model = view.table.model()
    return [
        [str(model.data(model.index(r, c), Qt.DisplayRole)) for c in range(model.columnCount())]
        for r in range(model.rowCount())
    ]


def find_row(view, text: str, column: int = 1) -> int:
    needle = text.lower()
    for row in range(view.table.model().rowCount()):
        if needle in table_text(view, row, column).lower():
            return row
    raise AssertionError(f"row not found: {text!r}")


def click_table_row(qtbot, view, row: int) -> None:
    log_event(f"TABLE_CLICK row={row}")
    idx = view.table.model().index(row, 0)
    rect = view.table.visualRect(idx)
    QTest.mouseClick(view.table.viewport(), Qt.LeftButton, pos=rect.center())
    qtbot.waitUntil(lambda: bool(view.table.selectionModel().selectedRows()), timeout=1000)
    selected = view.table.selectionModel().selectedRows()
    log_event(f"TABLE_CLICK_DONE selected_rows={[idx.row() for idx in selected]}")


def select_row_by_name(qtbot, view, name: str) -> int:
    row = find_row(view, name, 1)
    click_table_row(qtbot, view, row)
    return row


def type_search(qtbot, controller: ProductController, text: str, expected_total: int | None = None) -> None:
    view = controller.view
    log_event(f"TYPE_SEARCH {text!r}")
    view.search.setFocus()
    QTest.keyClick(view.search, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(view.search, Qt.Key_Backspace)
    QTest.keyClicks(view.search, text)
    wait_for_search(qtbot, controller, expected_total)


def clear_search(qtbot, controller: ProductController, expected_total: int = 121) -> None:
    view = controller.view
    log_event("CLEAR_SEARCH")
    view.search.setFocus()
    QTest.keyClick(view.search, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(view.search, Qt.Key_Backspace)
    wait_for_search(qtbot, controller, expected_total)


def summary_values(view) -> dict[str, str]:
    return {
        "Products": view.summary.val_total.text(),
        "Low Stock": view.summary.val_low_stock.text(),
        "Priced": view.summary.val_priced.text(),
        "With UoMs": view.summary.val_with_uoms.text(),
    }


def dialog_buttons(dialog: QDialog) -> QDialogButtonBox:
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    return buttons


def ok_button(dialog: QDialog):
    return dialog_buttons(dialog).button(QDialogButtonBox.Ok)


def cancel_button(dialog: QDialog):
    return dialog_buttons(dialog).button(QDialogButtonBox.Cancel)


def active_dialog(kind):
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, kind) and widget.isVisible():
            return widget
    return None


def wait_for_dialog(qtbot, kind):
    log_event(f"WAIT_DIALOG kind={kind.__name__} top_levels={widget_state()}")
    qtbot.waitUntil(lambda: active_dialog(kind) is not None, timeout=3000)
    dialog = active_dialog(kind)
    log_event(f"WAIT_DIALOG_DONE kind={kind.__name__} dialog={dialog!r}")
    return dialog


def fill_line_edit(edit: QLineEdit, text: str) -> None:
    log_event(f"FILL_LINE_EDIT widget={type(edit).__name__} text={text!r}")
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key_A, Qt.ControlModifier)
    if text == "":
        QTest.keyClick(edit, Qt.Key_Backspace)
        return
    QTest.keyClicks(edit, text)


@dataclass
class DialogResult:
    dialog: QDialog | None = None
    error: BaseException | None = None


def drive_product_form(qtbot, button, callback) -> ProductForm:
    result = DialogResult()

    def interact():
        dialog = None
        try:
            log_event("PRODUCT_FORM_INTERACT_START")
            dialog = wait_for_dialog(qtbot, ProductForm)
            result.dialog = dialog
            callback(dialog)
            log_event(f"PRODUCT_FORM_INTERACT_DONE visible={dialog.isVisible()}")
        except BaseException as exc:
            result.error = exc
            log_event(f"PRODUCT_FORM_CALLBACK_EXCEPTION {exc!r}\n{traceback.format_exc()}")
            if dialog is None:
                dialog = active_dialog(ProductForm)
            if dialog is not None:
                dialog.reject()

    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, interact)
    log_event(f"PRODUCT_FORM_BUTTON_CLICK text={button.text()!r}")
    QTest.mouseClick(button, Qt.LeftButton)
    log_event(f"PRODUCT_FORM_BUTTON_RETURN result={result.dialog!r}")
    if result.error is not None:
        raise result.error
    assert isinstance(result.dialog, ProductForm)
    return result.dialog


def drive_price_dialog(qtbot, button, callback) -> PriceDialog:
    result = DialogResult()

    def interact():
        dialog = None
        try:
            log_event("PRICE_DIALOG_INTERACT_START")
            dialog = wait_for_dialog(qtbot, PriceDialog)
            result.dialog = dialog
            callback(dialog)
            log_event(f"PRICE_DIALOG_INTERACT_DONE visible={dialog.isVisible()}")
        except BaseException as exc:
            result.error = exc
            log_event(f"PRICE_DIALOG_CALLBACK_EXCEPTION {exc!r}\n{traceback.format_exc()}")
            if dialog is None:
                dialog = active_dialog(PriceDialog)
            if dialog is not None:
                dialog.reject()

    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, interact)
    log_event(f"PRICE_DIALOG_BUTTON_CLICK text={button.text()!r}")
    QTest.mouseClick(button, Qt.LeftButton)
    log_event(f"PRICE_DIALOG_BUTTON_RETURN result={result.dialog!r}")
    if result.error is not None:
        raise result.error
    assert isinstance(result.dialog, PriceDialog)
    return result.dialog
