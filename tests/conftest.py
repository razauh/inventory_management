# inventory_management/tests/conftest.py
# ---------------------------------------------------------------------
# Ground rules:
# - pytest-qt owns QApplication (use qapp/qtbot fixtures)
# - Reuse the shared SQLite DB: data/myshop.db
# - Seed once per session using tests/seed_common.sql (idempotent)
# - For every test: BEGIN; ... ROLLBACK; to avoid cross-test contamination
# - conn.row_factory = sqlite3.Row, PRAGMA foreign_keys=ON
# - Provide handy ids + current_user fixtures
# - Silence benign Qt signal warnings
# ---------------------------------------------------------------------

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

import pytest
from PySide6 import QtCore

# ---------- Paths ----------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH      = PROJECT_ROOT / "data" / "myshop.db"
SEED_SQL     = PROJECT_ROOT / "tests" / "seed_common.sql"


# ---------- Qt: let pytest-qt own the app ----------
@pytest.fixture(scope="session")
def app(qapp):  # alias to match code that expects an `app` fixture
    return qapp


# ---------- Silence benign Qt warnings ----------
_BENIGN_QT_PATTERNS = [
    r"^QObject::connect: .* already connected",
    r"^QObject::disconnect: Unexpected null parameter",
    r"^QBasicTimer::stop: Failed\. Platform timer not running\.",
]

@pytest.fixture(autouse=True, scope="session")
def _silence_benign_qt():
    """Filter common harmless Qt messages during tests."""
    original = QtCore.qInstallMessageHandler(None)
    rx = [re.compile(p) for p in _BENIGN_QT_PATTERNS]

    def handler(msg_type, context, message):
        text = str(message)
        for r in rx:
            if r.search(text):
                return  # swallow benign messages
        # pass everything else through the default handler
        QtCore.qInstallMessageHandler(None)
        try:
            QtCore.qDebug(message)
        finally:
            QtCore.qInstallMessageHandler(handler)

    QtCore.qInstallMessageHandler(handler)
    try:
        yield
    finally:
        QtCore.qInstallMessageHandler(original)


# ---------- Seed shared DB once per session ----------
@pytest.fixture(scope="session", autouse=True)
def _apply_common_seed():
    """
    Run the idempotent seed once per test session against the shared DB.
    Assumes schema already exists in data/myshop.db.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Expected shared DB at {DB_PATH!s}.\n"
            "Create it with your normal schema/migrations, then re-run tests."
        )

    con = sqlite3.connect(DB_PATH)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;")
        sql = SEED_SQL.read_text(encoding="utf-8")
        con.executescript(sql)
        con.commit()
    finally:
        con.close()


# ---------- Per-test connection with transaction rollback ----------
@pytest.fixture()
def conn():
    """
    Connect to the shared DB, start a transaction, and rollback after each test.
    Keeps tests isolated while reusing stable IDs/names.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("BEGIN;")  # start test-local transaction
    try:
        yield con
        con.rollback()
    finally:
        con.close()


# ---------- Handy lookups ----------
@pytest.fixture()
def ids(conn: sqlite3.Connection) -> dict:
    """Common IDs/names used throughout the UI tests."""
    def one(sql: str, *p):
        r = conn.execute(sql, p).fetchone()
        return None if r is None else (r[0] if not isinstance(r, sqlite3.Row) else list(r)[0])

    vendor_id = one("SELECT vendor_id FROM vendors WHERE name='Vendor X' LIMIT 1")
    v_primary = conn.execute(
        "SELECT vendor_bank_account_id FROM vendor_bank_accounts "
        "WHERE vendor_id=? AND is_primary=1",
        (vendor_id,)
    ).fetchone()
    company_meezan = one("SELECT account_id FROM company_bank_accounts WHERE label='Meezan — Current' LIMIT 1")
    company_hbl    = one("SELECT account_id FROM company_bank_accounts WHERE label='HBL — Current' LIMIT 1")
    return {
        "vendor_id": vendor_id,
        "vendor_primary_vba": (None if v_primary is None else int(v_primary[0])),
        "company_meezan": company_meezan,
        "company_hbl": company_hbl,
        "uom_piece": one("SELECT uom_id FROM uoms WHERE unit_name='Piece'"),
        "uom_box":   one("SELECT uom_id FROM uoms WHERE unit_name='Box'"),
        "prod_A": one("SELECT product_id FROM products WHERE name='Widget A'"),
        "prod_B": one("SELECT product_id FROM products WHERE name='Widget B'"),
        "user_ops": one("SELECT user_id FROM users WHERE username='ops' LIMIT 1"),
    }


# ---------- Optional: simple current_user dict ----------
@pytest.fixture()
def current_user(ids: dict) -> Optional[dict]:
    if ids.get("user_ops"):
        return {"user_id": int(ids["user_ops"]), "username": "ops", "role": "admin"}
    return None
