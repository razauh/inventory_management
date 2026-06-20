from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QPushButton, QTabWidget, QTableView

from inventory_management.modules.vendor.payment_history_view import _VendorHistoryDialog

from .conftest import drive_dialog, select_vendor_by_name, vendor_id_by_name


def history_dialog_snapshot(dialog: _VendorHistoryDialog) -> str:
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    tables = []
    for table in dialog.findChildren(QTableView):
        model = table.model()
        headers = []
        rows = []
        if model is not None:
            headers = [
                str(model.headerData(col, Qt.Horizontal, Qt.DisplayRole))
                for col in range(model.columnCount())
            ]
            for row in range(min(model.rowCount(), 5)):
                rows.append([
                    str(model.data(model.index(row, col), Qt.DisplayRole))
                    for col in range(model.columnCount())
                ])
        tables.append({"headers": headers, "rows": rows, "row_count": model.rowCount() if model else None})
    return f"title={dialog.windowTitle()!r} visible={dialog.isVisible()} labels={labels!r} tables={tables!r}"


def history_table_models(dialog: _VendorHistoryDialog):
    tx_model = None
    totals_model = None
    other_models = []
    for table in dialog.findChildren(QTableView):
        model = table.model()
        headers = {
            str(model.headerData(col, Qt.Horizontal, Qt.DisplayRole))
            for col in range(model.columnCount())
        }
        if {"Date", "Type"}.issubset(headers):
            tx_model = model
        elif {"Cash Paid", "Credit Notes"}.issubset(headers):
            totals_model = model
        else:
            other_models.append(model)
    if tx_model is None and len(other_models) == 1:
        tx_model = other_models[0]
    return tx_model, totals_model


def test_vendor_history_requires_selected_vendor(qtbot, vendor_controller, message_log):
    view = vendor_controller.view
    view.table.clearSelection()

    QTest.mouseClick(view.btn_history, Qt.LeftButton)
    qtbot.wait(50)

    assert any(call[1] == "Select" and "select a vendor" in call[2] for call in message_log)


def test_history_dialog_empty_state_and_tabs(qtbot, vendor_controller, conn):
    vendor_id = vendor_id_by_name(conn, "No Account Vendor 500")
    history = vendor_controller.build_vendor_statement(vendor_id)
    dialog = _VendorHistoryDialog(vendor_id=vendor_id, history=history, vendor_display="No Account Vendor 500")
    qtbot.addWidget(dialog)
    dialog.show()

    tabs = dialog.findChild(QTabWidget)
    tx_model, totals_model = history_table_models(dialog)
    assert "Vendor History" in dialog.windowTitle(), history_dialog_snapshot(dialog)
    assert tabs.count() == 2, history_dialog_snapshot(dialog)
    assert tx_model is not None, history_dialog_snapshot(dialog)
    assert totals_model is not None, history_dialog_snapshot(dialog)
    assert tx_model.rowCount() == 0, history_dialog_snapshot(dialog)

    tabs.setCurrentIndex(1)
    assert tabs.currentIndex() == 1
    QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close), Qt.LeftButton)
    assert not dialog.isVisible()


def test_history_dialog_shows_transactions_and_totals(qtbot, vendor_controller, conn):
    vendor_id = vendor_id_by_name(conn, "History Vendor")
    history = vendor_controller.build_vendor_statement(vendor_id)
    dialog = _VendorHistoryDialog(vendor_id=vendor_id, history=history, vendor_display="History Vendor")
    qtbot.addWidget(dialog)
    dialog.show()

    tx_model, totals_model = history_table_models(dialog)

    assert tx_model is not None, history_dialog_snapshot(dialog)
    assert totals_model is not None, history_dialog_snapshot(dialog)
    assert tx_model.rowCount() >= 3, history_dialog_snapshot(dialog)
    rendered = " ".join(str(tx_model.data(tx_model.index(r, c), Qt.DisplayRole)) for r in range(tx_model.rowCount()) for c in range(tx_model.columnCount()))
    assert "Purchase" in rendered, history_dialog_snapshot(dialog)
    assert "Cash Payment" in rendered, history_dialog_snapshot(dialog)
    assert "Credit Note" in rendered, history_dialog_snapshot(dialog)
    assert totals_model.rowCount() > 0, history_dialog_snapshot(dialog)


def test_history_toolbar_flow_opens_and_closes_dialog(qtbot, vendor_controller, monkeypatch):
    view = vendor_controller.view
    select_vendor_by_name(qtbot, vendor_controller, "History Vendor")
    printed = []
    monkeypatch.setattr(_VendorHistoryDialog, "_on_print", lambda self: printed.append(self.windowTitle()))

    def interact(dialog):
        assert "History Vendor" in dialog.windowTitle()
        print_buttons = [b for b in dialog.findChildren(QPushButton) if "Print" in b.text()]
        assert print_buttons
        QTest.mouseClick(print_buttons[0], Qt.LeftButton)
        assert printed == [dialog.windowTitle()]
        QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close), Qt.LeftButton)

    drive_dialog(qtbot, view.btn_history, _VendorHistoryDialog, interact)


def test_history_truncation_note_appears_when_row_limit_exceeded(qtbot):
    rows = [
        {"date": "2026-01-01", "type": "Purchase", "doc_id": f"PO-{i}", "amount": 1, "amount_effect": 1, "balance_after": i}
        for i in range(_VendorHistoryDialog.MAX_VISIBLE_ROWS + 5)
    ]
    history = {
        "rows": rows,
        "totals": {},
        "opening_payable": 0,
        "opening_credit": 0,
        "closing_balance": 0,
        "period": {},
    }
    dialog = _VendorHistoryDialog(vendor_id=1, history=history, vendor_display="Many Rows")
    qtbot.addWidget(dialog)
    dialog.show()

    visible_text = " ".join(w.text() for w in dialog.findChildren(QLabel))
    assert dialog.findChildren(QTableView)[0].model().rowCount() == _VendorHistoryDialog.MAX_VISIBLE_ROWS
    assert f"Showing first {_VendorHistoryDialog.MAX_VISIBLE_ROWS} rows" in visible_text
