import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from inventory_management.database.schema import SQL
from inventory_management.modules.vendor.bank_accounts_dialog import (
    AccountEditDialog,
    VendorBankAccountsDialog,
)


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Toast Vendor', 'Test')"
    ).lastrowid
    primary_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Primary', 'Bank A', '111', 1, 1)
        """,
        (vendor_id,),
    ).lastrowid
    secondary_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Secondary', 'Bank B', '222', 0, 1)
        """,
        (vendor_id,),
    ).lastrowid
    inactive_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_primary, is_active
        ) VALUES (?, 'Inactive', 'Bank C', '333', 0, 0)
        """,
        (vendor_id,),
    ).lastrowid
    conn.commit()
    return conn, int(vendor_id), int(primary_id), int(secondary_id), int(inactive_id)


def _dialog(qtbot):
    conn, vendor_id, primary_id, secondary_id, inactive_id = _make_db()
    dlg = VendorBankAccountsDialog(conn=conn, vendor_id=vendor_id)
    qtbot.addWidget(dlg)
    return dlg, conn, primary_id, secondary_id, inactive_id


def _select_account(dialog, account_id):
    for row in range(dialog.tbl.rowCount()):
        item = dialog.tbl.item(row, 0)
        if item and int(item.data(Qt.UserRole)) == account_id:
            dialog.tbl.selectRow(row)
            return
    raise AssertionError(f"Account row not found: {account_id}")


def test_stale_edit_account_uses_toast_not_blocking_warning(qtbot, monkeypatch):
    dlg, conn, primary_id, _secondary_id, _inactive_id = _dialog(qtbot)
    _select_account(dlg, primary_id)
    conn.execute(
        "DELETE FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (primary_id,),
    )
    conn.commit()
    warnings = []
    toasts = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(
        "inventory_management.modules.vendor.bank_accounts_dialog.uih.info",
        lambda *args, **kwargs: toasts.append(args),
    )

    dlg._edit()

    assert warnings == []
    assert toasts
    assert toasts[0][1:] == ("Not found", "Account not found.")


def test_stale_make_primary_uses_toast_not_blocking_warning(qtbot, monkeypatch):
    dlg, conn, _primary_id, secondary_id, _inactive_id = _dialog(qtbot)
    _select_account(dlg, secondary_id)
    conn.execute(
        "DELETE FROM vendor_bank_accounts WHERE vendor_bank_account_id = ?",
        (secondary_id,),
    )
    conn.commit()
    warnings = []
    toasts = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(
        "inventory_management.modules.vendor.bank_accounts_dialog.uih.info",
        lambda *args, **kwargs: toasts.append(args),
    )

    dlg._make_primary()

    assert warnings == []
    assert toasts
    assert toasts[0][1:] == ("Not found", "Account not found.")


def test_account_label_validation_stays_blocking(qtbot, monkeypatch):
    dlg = AccountEditDialog()
    qtbot.addWidget(dlg)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))

    dlg.accept()

    assert warnings
    assert warnings[0][1:] == ("Required", "Label is required.")
    assert dlg.payload() is None


def test_deactivate_account_confirmation_stays_blocking(qtbot, monkeypatch):
    dlg, _conn, _primary_id, secondary_id, _inactive_id = _dialog(qtbot)
    _select_account(dlg, secondary_id)
    questions = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: questions.append(args) or QMessageBox.No,
    )

    dlg._toggle_active()

    assert questions
    assert questions[0][1] == "Deactivate account?"


def test_inactive_make_primary_rejection_stays_blocking(qtbot, monkeypatch):
    dlg, _conn, _primary_id, _secondary_id, inactive_id = _dialog(qtbot)
    _select_account(dlg, inactive_id)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))

    dlg._make_primary()

    assert warnings
    assert warnings[0][1:] == ("Inactive", "Activate this account before making it primary.")
