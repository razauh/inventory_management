from __future__ import annotations

import sqlite3
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton, QTabWidget

from modules.backup_restore import service
from modules.backup_restore.controller import BackupRestoreController
from modules.backup_restore.service import purge_transactional_data
from modules.backup_restore.views import PurgeConfirmationDialog


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "live.db"
    conn = _connect(db_path)
    conn.executescript(
        """
        CREATE TABLE products(product_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE product_uoms(product_uom_id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER);
        CREATE TABLE uoms(uom_id INTEGER PRIMARY KEY AUTOINCREMENT, unit_name TEXT);
        CREATE TABLE product_sale_prices(price_id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER);
        CREATE TABLE vendors(vendor_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE vendor_bank_accounts(vendor_bank_account_id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER);
        CREATE TABLE customers(customer_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE expense_categories(category_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE company_info(company_id INTEGER PRIMARY KEY, company_name TEXT);
        CREATE TABLE company_contacts(contact_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER);
        CREATE TABLE company_bank_accounts(account_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER);
        CREATE TABLE users(user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT);
        CREATE TABLE audit_logs(log_id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT);
        CREATE TABLE error_logs(error_id INTEGER PRIMARY KEY AUTOINCREMENT, error_type TEXT);
        CREATE TABLE accounting_rule_audit_events(audit_event_id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE accounting_rule_audit_reviews(review_id INTEGER PRIMARY KEY AUTOINCREMENT, audit_event_id INTEGER REFERENCES accounting_rule_audit_events(audit_event_id) ON DELETE CASCADE);

        CREATE TABLE purchases(purchase_id TEXT PRIMARY KEY);
        CREATE TABLE sales(sale_id TEXT PRIMARY KEY);
        CREATE TABLE sales_document_sequences(namespace TEXT, document_date TEXT, last_value INTEGER);
        CREATE TABLE expenses(expense_id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER);
        CREATE TABLE sale_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT REFERENCES sales(sale_id) ON DELETE CASCADE);
        CREATE TABLE purchase_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id TEXT REFERENCES purchases(purchase_id) ON DELETE CASCADE);
        CREATE TABLE inventory_transactions(transaction_id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE purchase_return_snapshots(transaction_id INTEGER PRIMARY KEY REFERENCES inventory_transactions(transaction_id) ON DELETE CASCADE);
        CREATE TABLE sale_return_snapshots(transaction_id INTEGER PRIMARY KEY REFERENCES inventory_transactions(transaction_id) ON DELETE CASCADE);
        CREATE TABLE stock_valuation_history(valuation_id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE valuation_dirty(product_id INTEGER PRIMARY KEY);
        CREATE TABLE sale_payments(payment_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT REFERENCES sales(sale_id) ON DELETE CASCADE);
        CREATE TABLE sale_payment_state_reversals(reversal_id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER REFERENCES sale_payments(payment_id) ON DELETE CASCADE);
        CREATE TABLE purchase_payments(payment_id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id TEXT REFERENCES purchases(purchase_id) ON DELETE CASCADE);
        CREATE TABLE purchase_refunds(refund_id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id TEXT REFERENCES purchases(purchase_id) ON DELETE CASCADE);
        CREATE TABLE customer_advances(tx_id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE vendor_advances(tx_id INTEGER PRIMARY KEY AUTOINCREMENT);
        """
    )
    for table in (
        "products", "product_uoms", "uoms", "product_sale_prices", "vendors",
        "vendor_bank_accounts", "customers", "expense_categories",
        "company_contacts", "company_bank_accounts", "users", "audit_logs", "error_logs",
    ):
        conn.execute(f"INSERT INTO {table} DEFAULT VALUES")
    conn.execute("INSERT INTO company_info(company_id, company_name) VALUES (1, 'Company')")
    conn.executescript(
        """
        INSERT INTO purchases(purchase_id) VALUES ('P-1');
        INSERT INTO sales(sale_id) VALUES ('S-1');
        INSERT INTO sales_document_sequences VALUES ('sale', '2026-06-20', 1);
        INSERT INTO expenses(category_id) VALUES (1);
        INSERT INTO sale_items(sale_id) VALUES ('S-1');
        INSERT INTO purchase_items(purchase_id) VALUES ('P-1');
        INSERT INTO inventory_transactions DEFAULT VALUES;
        INSERT INTO purchase_return_snapshots(transaction_id) VALUES (1);
        INSERT INTO sale_return_snapshots(transaction_id) VALUES (1);
        INSERT INTO stock_valuation_history DEFAULT VALUES;
        INSERT INTO valuation_dirty(product_id) VALUES (1);
        INSERT INTO sale_payments(sale_id) VALUES ('S-1');
        INSERT INTO sale_payment_state_reversals(payment_id) VALUES (1);
        INSERT INTO purchase_payments(purchase_id) VALUES ('P-1');
        INSERT INTO purchase_refunds(purchase_id) VALUES ('P-1');
        INSERT INTO customer_advances DEFAULT VALUES;
        INSERT INTO vendor_advances DEFAULT VALUES;
        INSERT INTO accounting_rule_audit_events DEFAULT VALUES;
        INSERT INTO accounting_rule_audit_reviews(audit_event_id) VALUES (1);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _count(db_path: Path, table: str) -> int:
    conn = _connect(db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_purge_removes_activity_and_keeps_master_data(tmp_path):
    db_path = _make_db(tmp_path)

    counts = purge_transactional_data(str(db_path))

    for table in service.PURGE_COUNT_TABLES:
        assert _count(db_path, table) == 0
        assert counts[table] == 1
    for table in (
        "products", "product_uoms", "uoms", "product_sale_prices", "vendors",
        "vendor_bank_accounts", "customers", "expense_categories", "company_info",
        "company_contacts", "company_bank_accounts", "users", "audit_logs", "error_logs",
    ):
        assert _count(db_path, table) == 1
    conn = _connect(db_path)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_purge_rolls_back_when_delete_step_fails(tmp_path):
    db_path = _make_db(tmp_path)
    conn = _connect(db_path)
    conn.execute(
        "CREATE TRIGGER fail_sales_delete BEFORE DELETE ON sales BEGIN SELECT RAISE(ABORT, 'stop purge'); END;"
    )
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="stop purge"):
        purge_transactional_data(str(db_path))

    assert _count(db_path, "expenses") == 1
    assert _count(db_path, "sales") == 1


def test_backup_failure_blocks_purge(tmp_path):
    db_path = _make_db(tmp_path)
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("x")

    with pytest.raises(FileExistsError):
        purge_transactional_data(str(db_path), backup_path=str(not_a_dir / "backup.imsdb"))

    assert _count(db_path, "expenses") == 1


def test_purge_confirmation_requires_exact_phrase_and_backup_path(qtbot):
    dlg = PurgeConfirmationDialog()
    qtbot.addWidget(dlg)

    assert dlg._purge_btn.isEnabled() is False
    dlg._confirm_edit.setText("purge data")
    assert dlg._purge_btn.isEnabled() is False
    dlg._confirm_edit.setText("PURGE DATA")
    assert dlg._purge_btn.isEnabled() is True
    dlg._backup_edit.setText("")
    assert dlg._purge_btn.isEnabled() is False
    dlg._backup_check.setChecked(False)
    assert dlg._purge_btn.isEnabled() is True


def test_backup_restore_window_shows_purge_data_tab(qtbot):
    controller = BackupRestoreController(settings_org="TestOrg", settings_app="PurgeTab")
    widget = controller.get_widget()
    qtbot.addWidget(widget)

    tabs = widget.findChild(QTabWidget)
    assert tabs is not None
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Backup / Restore", "Purge Data"]
    assert any(button.text() == "Purge Data…" for button in widget.findChildren(QPushButton))
