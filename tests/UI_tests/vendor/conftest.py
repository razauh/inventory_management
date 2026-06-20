from __future__ import annotations

import sqlite3
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
)

from inventory_management.database.schema import init_schema
from inventory_management.modules.vendor.bank_accounts_dialog import AccountEditDialog
from inventory_management.modules.vendor.controller import VendorController
from inventory_management.modules.vendor.form import VendorForm
from inventory_management.modules.vendor.payment_dialog import _VendorMoneyDialog


LOG_DIR = Path(__file__).resolve().parents[3] / ".logs"
LOG_PATH = LOG_DIR / "vendor_ui_tests.log"
FAIL_PATH = LOG_DIR / "vendor_ui_failures.log"


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
    LOG_PATH.write_text("vendor GUI test log\n", encoding="utf-8")
    FAIL_PATH.write_text("vendor GUI failure log\n", encoding="utf-8")


def pytest_runtest_logstart(nodeid, location):
    log_event(f"START {nodeid}")


def pytest_runtest_logreport(report):
    outcome = report.outcome.upper()
    if hasattr(report, "wasxfail"):
        outcome = "XPASS" if report.passed else "XFAIL"
    if report.when == "call" or report.failed:
        log_event(f"{outcome} {report.nodeid} phase={report.when} duration={report.duration:.3f}s")
    if report.failed:
        state = f"FAILED_STATE {report.nodeid} top_levels={widget_state()}\n"
        log_event(state.strip())
        with FAIL_PATH.open("a", encoding="utf-8") as handle:
            handle.write(state)
            longrepr = getattr(report, "longreprtext", None)
            if longrepr:
                handle.write(f"TRACEBACK {report.nodeid}\n{longrepr}\n")
            sections = getattr(report, "sections", None) or []
            for name, content in sections:
                if content:
                    handle.write(f"SECTION {report.nodeid} {name}\n{content}\n")


@pytest.fixture(autouse=True)
def _vendor_gui_log(request):
    log_event(f"SETUP {request.node.nodeid}")
    start = time.monotonic()
    yield
    log_event(
        f"TEARDOWN {request.node.nodeid} elapsed={time.monotonic() - start:.3f}s "
        f"top_levels={widget_state()}"
    )


@pytest.fixture(scope="session")
def vendor_db_template(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("vendor_gui_template") / "template.sqlite3"
    log_event(f"DB_TEMPLATE_INIT {db_path}")
    init_schema(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    seed_vendor_gui_db(con)
    con.execute("PRAGMA wal_checkpoint(FULL)")
    con.close()
    log_event(f"DB_TEMPLATE_READY {db_path}")
    return db_path


@pytest.fixture()
def conn(tmp_path: Path, vendor_db_template: Path):
    db_path = tmp_path / "vendor_gui.sqlite3"
    shutil.copyfile(vendor_db_template, db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


@pytest.fixture()
def vendor_controller(qtbot, conn):
    controller = VendorController(conn)
    view = controller.get_widget()
    qtbot.addWidget(view)
    view.resize(1280, 760)
    view.show()
    qtbot.waitExposed(view)
    wait_for_vendors(qtbot, controller)
    log_event(
        f"CONTROLLER_READY rows={controller.base_model.rowCount()} "
        f"total={controller._total_vendors} page={controller.view.lbl_page.text()!r}"
    )
    return controller


@pytest.fixture()
def vendor_view(vendor_controller):
    return vendor_controller.view


@pytest.fixture()
def message_log(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def record(kind):
        def inner(parent, title, text, *args, **kwargs):
            calls.append((kind, str(title), str(text)))
            log_event(f"MESSAGE {kind} title={title!r} text={text!r}")
            if kind in {"question", "warning"}:
                return QMessageBox.StandardButton.Yes
            return QMessageBox.StandardButton.Ok

        return inner

    monkeypatch.setattr(QMessageBox, "information", record("information"))
    monkeypatch.setattr(QMessageBox, "critical", record("critical"))
    monkeypatch.setattr(QMessageBox, "warning", record("warning"))
    monkeypatch.setattr(QMessageBox, "question", record("question"))
    return calls


def seed_vendor_gui_db(conn: sqlite3.Connection) -> None:
    log_event("SEED_START")
    conn.execute(
        "INSERT INTO company_info(company_id, company_name) VALUES (1, 'Vendor GUI Test Company')"
    )
    conn.execute(
        """
        INSERT INTO company_bank_accounts(label, bank_name, account_no, is_active)
        VALUES ('Main Checking', 'Company Bank', '9876543210', 1)
        """
    )
    vendor_ids: dict[str, int] = {}
    samples = [
        ("No Account Vendor 500", "nocontact@example.test", None),
        ("Primary Account Vendor", "primary phone 111", "North Market Road"),
        ("Multi Account Vendor", "multi phone 222", "South Warehouse Lane"),
        ("Inactive Account Vendor", "inactive phone 333", "Dormant Street"),
        ("Advance Vendor", "advance phone 444", "Credit Avenue"),
        ("Open Purchase Vendor", "purchase phone 555", "Payable Road"),
        ("History Vendor", "history phone 666", "Ledger Plaza"),
        ("Mixed CASE Vendor", "Case Contact", "Case Address"),
        ("Numeric Vendor 12345", "Numeric Contact 777", "Block 12345"),
        ("Long Notes Vendor", "Long contact text " * 8, "Long address text " * 8),
    ]
    for i in range(1, 116):
        samples.append((f"Page Vendor {i:03d}", f"page contact {i:03d}", f"page address {i:03d}"))
    for name, contact, address in samples:
        vendor_ids[name] = int(
            conn.execute(
                "INSERT INTO vendors(name, contact_info, address) VALUES (?, ?, ?)",
                (name, contact, address),
            ).lastrowid
        )

    primary_vendor = vendor_ids["Primary Account Vendor"]
    multi_vendor = vendor_ids["Multi Account Vendor"]
    inactive_vendor = vendor_ids["Inactive Account Vendor"]
    advance_vendor = vendor_ids["Advance Vendor"]
    open_vendor = vendor_ids["Open Purchase Vendor"]
    history_vendor = vendor_ids["History Vendor"]

    conn.execute(
        """
        INSERT INTO vendor_bank_accounts(
            vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
        ) VALUES (?, 'Primary AP', 'Vendor Bank', '1111222233334444', 'PK36SCBL0000001123456702', 'R111', 1, 1)
        """,
        (primary_vendor,),
    )
    conn.execute(
        """
        INSERT INTO vendor_bank_accounts(
            vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
        ) VALUES (?, 'Main', 'Alpha Bank', '5555666677778888', 'PK36SCBL0000001123456703', 'R222', 1, 1)
        """,
        (multi_vendor,),
    )
    conn.execute(
        """
        INSERT INTO vendor_bank_accounts(
            vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
        ) VALUES (?, 'Backup', 'Beta Bank', '9999000011112222', 'PK36SCBL0000001123456704', 'R333', 0, 1)
        """,
        (multi_vendor,),
    )
    conn.execute(
        """
        INSERT INTO vendor_bank_accounts(
            vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
        ) VALUES (?, 'Inactive', 'Closed Bank', '123400009999', NULL, 'R444', 0, 0)
        """,
        (inactive_vendor,),
    )
    conn.execute(
        """
        INSERT INTO vendor_bank_accounts(
            vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
        ) VALUES (?, 'Advance Account', 'Advance Bank', '121212121212', NULL, 'R555', 1, 1)
        """,
        (advance_vendor,),
    )

    conn.execute(
        "INSERT INTO vendor_advances(vendor_id, tx_date, amount, source_type, notes) VALUES (?, '2026-01-03', 250.0, 'deposit', 'seed credit')",
        (advance_vendor,),
    )
    conn.execute(
        "INSERT INTO purchases(purchase_id, vendor_id, date, total_amount, paid_amount, payment_status) VALUES ('PO-GUI-001', ?, '2026-01-05', 120.0, 0.0, 'unpaid')",
        (open_vendor,),
    )
    conn.execute(
        "INSERT INTO purchases(purchase_id, vendor_id, date, total_amount, paid_amount, payment_status) VALUES ('PO-GUI-002', ?, '2026-01-06', 80.0, 0.0, 'unpaid')",
        (open_vendor,),
    )
    conn.execute(
        "INSERT INTO purchases(purchase_id, vendor_id, date, total_amount, paid_amount, payment_status) VALUES ('PO-HIST-001', ?, '2026-01-02', 70.0, 0.0, 'unpaid')",
        (history_vendor,),
    )
    conn.execute(
        "INSERT INTO purchase_payments(purchase_id, date, amount, method, clearing_state) VALUES ('PO-HIST-001', '2026-01-03', 20.0, 'Cash', 'cleared')"
    )
    conn.execute(
        "INSERT INTO vendor_advances(vendor_id, tx_date, amount, source_type, notes) VALUES (?, '2026-01-04', 15.0, 'deposit', 'history credit')",
        (history_vendor,),
    )
    conn.commit()
    log_event(f"SEED_DONE vendors={len(samples)}")


def wait_for_vendors(qtbot, controller: VendorController, min_rows: int = 1) -> None:
    qtbot.waitUntil(lambda: controller.base_model.rowCount() >= min_rows, timeout=3000)
    qtbot.wait(180)


def wait_for_search(qtbot, controller: VendorController, expected_total: int | None = None) -> None:
    qtbot.wait(260)
    if expected_total is not None:
        qtbot.waitUntil(lambda: controller._total_vendors == expected_total, timeout=3000)
    qtbot.wait(30)


def table_text(view, row: int, column: int) -> str:
    model = view.table.model()
    return str(model.data(model.index(row, column), Qt.DisplayRole))


def account_text(view, row: int, column: int) -> str:
    model = view.accounts_table.model()
    return str(model.data(model.index(row, column), Qt.DisplayRole))


def find_row(view, text: str, column: int = 1) -> int:
    needle = text.lower()
    for row in range(view.table.model().rowCount()):
        if needle in table_text(view, row, column).lower():
            return row
    raise AssertionError(f"row not found: {text!r}")


def click_table_row(qtbot, table, row: int) -> None:
    idx = table.model().index(row, 0)
    rect = table.visualRect(idx)
    QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=rect.center())
    qtbot.waitUntil(lambda: bool(table.selectionModel().selectedRows()), timeout=1000)


def select_vendor_by_name(qtbot, controller: VendorController, name: str) -> int:
    type_search(qtbot, controller, name, expected_total=1)
    row = find_row(controller.view, name, 1)
    click_table_row(qtbot, controller.view.table, row)
    qtbot.wait(180)
    return row


def select_account_row(qtbot, view, row: int = 0) -> None:
    click_table_row(qtbot, view.accounts_table, row)
    qtbot.wait(120)


def type_search(qtbot, controller: VendorController, text: str, expected_total: int | None = None) -> None:
    view = controller.view
    view.search.setFocus()
    view.search.setText(text)
    wait_for_search(qtbot, controller, expected_total)


def clear_search(qtbot, controller: VendorController, expected_total: int = 125) -> None:
    type_search(qtbot, controller, "", expected_total=expected_total)


def fill_line_edit(edit: QLineEdit, text: str) -> None:
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(edit, Qt.Key_Backspace)
    if text:
        QTest.keyClicks(edit, text)


def fill_plain_text(edit: QPlainTextEdit, text: str) -> None:
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(edit, Qt.Key_Backspace)
    if text:
        QTest.keyClicks(edit, text)


def set_combo_text(combo: QComboBox, text: str) -> None:
    idx = combo.findText(text)
    assert idx >= 0, f"combo text not found: {text!r}"
    combo.setCurrentIndex(idx)


def dialog_buttons(dialog: QDialog) -> QDialogButtonBox:
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    return buttons


def ok_button(dialog: QDialog):
    button = dialog_buttons(dialog).button(QDialogButtonBox.Ok)
    if button is None:
        button = dialog_buttons(dialog).button(QDialogButtonBox.Save)
    assert button is not None
    return button


def cancel_button(dialog: QDialog):
    button = dialog_buttons(dialog).button(QDialogButtonBox.Cancel)
    assert button is not None
    return button


def active_dialog(kind=None, title: str | None = None):
    for widget in QApplication.topLevelWidgets():
        if kind is not None and not isinstance(widget, kind):
            continue
        if title is not None and widget.windowTitle() != title:
            continue
        if widget.isVisible():
            return widget
    return None


def wait_for_dialog(qtbot, kind=None, title: str | None = None):
    qtbot.waitUntil(lambda: active_dialog(kind, title) is not None, timeout=3000)
    return active_dialog(kind, title)


@dataclass
class DialogResult:
    dialog: QDialog | None = None
    error: BaseException | None = None


def drive_dialog(qtbot, button, kind, callback, *, title: str | None = None):
    result = DialogResult()

    def interact():
        dialog = None
        try:
            dialog = wait_for_dialog(qtbot, kind, title)
            result.dialog = dialog
            callback(dialog)
        except BaseException as exc:
            result.error = exc
            log_event(f"DIALOG_CALLBACK_EXCEPTION {exc!r}\n{traceback.format_exc()}")
            if dialog is None:
                dialog = active_dialog(kind, title)
            if dialog is not None:
                dialog.reject()

    QTimer.singleShot(0, interact)
    QTest.mouseClick(button, Qt.LeftButton)
    if result.error is not None:
        raise result.error
    assert result.dialog is not None
    return result.dialog


def drive_vendor_form(qtbot, button, callback) -> VendorForm:
    return drive_dialog(qtbot, button, VendorForm, callback)


def drive_account_edit(qtbot, button, callback) -> AccountEditDialog:
    return drive_dialog(qtbot, button, AccountEditDialog, callback)


def drive_money_dialog(qtbot, button, callback) -> _VendorMoneyDialog:
    return drive_dialog(qtbot, button, _VendorMoneyDialog, callback)


def fill_valid_vendor_form(dialog: VendorForm, name: str = "GUI Added Vendor") -> None:
    fill_line_edit(dialog.name, name)
    fill_plain_text(dialog.contact, "GUI contact")
    fill_plain_text(dialog.addr, "GUI address")


def fill_valid_account_dialog(dialog: AccountEditDialog, label: str = "GUI Account") -> None:
    fill_line_edit(dialog.txt_label, label)
    fill_line_edit(dialog.txt_bank, "GUI Bank")
    fill_line_edit(dialog.txt_acc, "123456789012")
    fill_line_edit(dialog.txt_iban, "PK36SCBL0000001123456709")
    fill_line_edit(dialog.txt_rout, "ROUT9")


def vendor_id_by_name(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT vendor_id FROM vendors WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["vendor_id"])


def cell_text(table, row: int, column: int) -> str:
    item = table.item(row, column)
    return "" if item is None else item.text()
