# inventory_management/tests/inventory.py
from __future__ import annotations

import csv
from datetime import date, timedelta

import pytest
from PySide6.QtCore import Qt, QDate
from PySide6.QtTest import QTest

# SUT imports
from inventory_management.database.repositories.inventory_repo import InventoryRepo
from inventory_management.modules.inventory.model import TransactionsTableModel
from inventory_management.modules.inventory.transactions import TransactionsView
from inventory_management.modules.inventory.stock_valuation import StockValuationWidget
from inventory_management.modules.inventory.controller import InventoryController


# ---------------------------
# Schema-aware helpers
# ---------------------------

def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (table,),
    ).fetchone()
    return row is not None

def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r[1] == col for r in rows)

def _mk_uom(conn, unit_name="Each"):
    row = conn.execute("SELECT uom_id FROM uoms WHERE unit_name=?", (unit_name,)).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute("INSERT INTO uoms(unit_name) VALUES (?)", (unit_name,))
    return int(cur.lastrowid)

def _mk_product(conn, name="Test Product", uom_id=None):
    """
    Insert a product using whatever column your schema actually has.
    Supports:
      - products(name)
      - products(name, uom_id)
      - products(name, default_uom_id)

    We try to set the product's *base/default* UoM to the provided uom_id so that
    product_uoms triggers that verify base/non-base consistency are satisfied.
    """
    row = conn.execute("SELECT product_id FROM products WHERE name=?", (name,)).fetchone()
    if row:
        return int(row[0])

    has_uom_id = _has_column(conn, "products", "uom_id")
    has_default_uom_id = _has_column(conn, "products", "default_uom_id")

    if uom_id is None and (has_uom_id or has_default_uom_id):
        uom_id = _mk_uom(conn, "Each")

    if has_default_uom_id:
        cur = conn.execute(
            "INSERT INTO products(name, default_uom_id) VALUES (?, ?)",
            (name, uom_id),
        )
    elif has_uom_id:
        cur = conn.execute(
            "INSERT INTO products(name, uom_id) VALUES (?, ?)",
            (name, uom_id),
        )
    else:
        cur = conn.execute("INSERT INTO products(name) VALUES (?)", (name,))
    return int(cur.lastrowid)

def _ensure_prod_uom(conn, product_id: int, uom_id: int):
    """
    Ensure a Product↔UoM mapping exists in product_uoms that satisfies common
    base-UoM triggers:

      - factor_to_base = 1.0  (or conversion_factor/factor = 1.0)
      - is_base = 1           (or is_default / is_primary = 1)

    If the table doesn't exist, nothing is done.
    """
    if not _table_exists(conn, "product_uoms"):
        return  # nothing to do

    exists = conn.execute(
        "SELECT 1 FROM product_uoms WHERE product_id=? AND uom_id=? LIMIT 1",
        (product_id, uom_id),
    ).fetchone()
    if exists:
        return

    cols_info = conn.execute("PRAGMA table_info(product_uoms)").fetchall()
    col_names = {r[1] for r in cols_info}

    cols = ["product_id", "uom_id"]
    vals = [int(product_id), int(uom_id)]

    # ---- factor column(s): prefer factor_to_base if present ----
    if "factor_to_base" in col_names:
        cols.append("factor_to_base")
        vals.append(1.0)
    elif "conversion_factor" in col_names:
        cols.append("conversion_factor")
        vals.append(1.0)
    elif "factor" in col_names:
        cols.append("factor")
        vals.append(1.0)

    # ---- base/default flag(s): prefer is_base if present ----
    if "is_base" in col_names:
        cols.append("is_base")
        vals.append(1)
    elif "is_default" in col_names:
        cols.append("is_default")
        vals.append(1)
    elif "is_primary" in col_names:
        cols.append("is_primary")
        vals.append(1)

    placeholders = ", ".join(["?"] * len(cols))
    conn.execute(
        f"INSERT INTO product_uoms({', '.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )

def _seed_txn(
    conn,
    *,
    product_id: int,
    uom_id: int | None,
    qty: float,
    dte: str,
    txn_type="adjustment",
    notes=None,
):
    """
    Insert into inventory_transactions using the columns we saw:
      quantity, transaction_type, date (+ product_id/uom_id).
    Ensure product↔uom mapping exists first (if product_uoms table exists).
    """
    # Make sure mapping exists for triggers that enforce it
    if uom_id is not None:
        _ensure_prod_uom(conn, product_id, uom_id)

    has_uom_id = _has_column(conn, "inventory_transactions", "uom_id")
    cols = ["product_id", "quantity", "transaction_type", "date", "notes"]
    vals = [product_id, float(qty), txn_type, dte, notes]
    placeholders = "?, ?, ?, ?, ?"

    if has_uom_id:
        cols.insert(1, "uom_id")
        vals.insert(1, (None if uom_id is None else int(uom_id)))
        placeholders = "?, ?, ?, ?, ?, ?"

    cur = conn.execute(
        f"INSERT INTO inventory_transactions({', '.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )
    return int(cur.lastrowid)

def _today(n=0):
    return (date.today() + timedelta(days=n)).strftime("%Y-%m-%d")


# ============================================================
# A) Repository tests: inventory_repo.py
# ============================================================

def test_repo_recent_transactions_order_and_columns(conn):
    repo = InventoryRepo(conn)
    uom = _mk_uom(conn, "Each")
    p1 = _mk_product(conn, "Alpha", uom)
    p2 = _mk_product(conn, "Beta", uom)

    id1 = _seed_txn(conn, product_id=p1, uom_id=uom, qty=5,  dte=_today(-2), notes="t1")
    id2 = _seed_txn(conn, product_id=p2, uom_id=uom, qty=-2, dte=_today(-1), notes="t2")
    id3 = _seed_txn(conn, product_id=p1, uom_id=uom, qty=3,  dte=_today(0),  notes="t3")

    rows = repo.recent_transactions(limit=50)
    assert len(rows) >= 3

    # newest first
    got_ids = [r.get("transaction_id") for r in rows[:3]]
    assert got_ids == [id3, id2, id1]

    # model-expected keys present
    r = rows[0]
    for k in ("transaction_id", "date", "transaction_type", "product", "quantity", "unit_name", "notes"):
        assert k in r

def test_repo_recent_transactions_limit_guard(conn):
    repo = InventoryRepo(conn)
    uom = _mk_uom(conn, "Each")
    p = _mk_product(conn, "Gamma", uom)
    for i in range(10):
        _seed_txn(conn, product_id=p, uom_id=uom, qty=i+1, dte=_today(-i))

    for lim, expect_max in [(50, 10), (100, 10), (500, 10), (999, 10), ("abc", 10), (None, 10)]:
        rows = repo.recent_transactions(limit=lim)
        assert len(rows) <= expect_max

def test_repo_find_transactions_filters_matrix(conn):
    repo = InventoryRepo(conn)
    uom = _mk_uom(conn, "Each")
    p1 = _mk_product(conn, "Prod-1", uom)
    p2 = _mk_product(conn, "Prod-2", uom)

    d0 = _today(-2)
    d1 = _today(-1)
    d2 = _today(0)
    _seed_txn(conn, product_id=p1, uom_id=uom, qty=1, dte=d0, notes="p1-d0")
    _seed_txn(conn, product_id=p1, uom_id=uom, qty=2, dte=d1, notes="p1-d1")
    _seed_txn(conn, product_id=p2, uom_id=uom, qty=3, dte=d2, notes="p2-d2")

    # only product
    rows = repo.find_transactions(product_id=p1, limit=100)
    assert rows and all(r["product"] == "Prod-1" for r in rows)

    # only from
    rows = repo.find_transactions(date_from=d1, limit=100)
    assert rows and all(r["date"] >= d1 for r in rows)

    # only to
    rows = repo.find_transactions(date_to=d1, limit=100)
    assert rows and all(r["date"] <= d1 for r in rows)

    # range + product
    rows = repo.find_transactions(date_from=d0, date_to=d1, product_id=p1, limit=100)
    assert rows and all((r["product"] == "Prod-1") and (d0 <= r["date"] <= d1) for r in rows)


def test_repo_stock_on_hand_complete_and_none(conn):
    repo = InventoryRepo(conn)
    uom = _mk_uom(conn, "Each")
    p = _mk_product(conn, "Valued Prod", uom)

    # build a connection-local v_stock_on_hand regardless of schema
    conn.execute("DROP VIEW IF EXISTS v_stock_on_hand")

    # detect how to get uom_name
    has_prod_uom_id = _has_column(conn, "products", "uom_id")
    has_prod_def_uom = _has_column(conn, "products", "default_uom_id")

    if has_prod_uom_id:
        uom_join = "JOIN uoms ON uoms.uom_id = products.uom_id"
    elif has_prod_def_uom:
        uom_join = "JOIN uoms ON uoms.uom_id = products.default_uom_id"
    else:
        uom_join = "LEFT JOIN uoms ON 1=0"  # ensures NULL, we’ll use COALESCE

    conn.execute(
        f"""
        CREATE VIEW v_stock_on_hand AS
        SELECT
            products.product_id              AS product_id,
            products.name                    AS product_name,
            COALESCE(uoms.unit_name, 'Each') AS uom_name,
            12.5                              AS on_hand_qty,
            2.00                              AS unit_value,
            25.00                             AS total_value
        FROM products
        {uom_join}
        """
    )

    rec = repo.stock_on_hand(p)
    assert rec is not None
    assert rec["product_id"] == p
    assert abs(float(rec["on_hand_qty"]) - 12.5) < 1e-6
    assert abs(float(rec["unit_value"]) - 2.00) < 1e-6
    assert abs(float(rec["total_value"]) - 25.00) < 1e-6

    # product that doesn't exist
    rec2 = repo.stock_on_hand(999999)
    assert rec2 is None


# ============================================================
# B) Model tests: TransactionsTableModel tolerance
# ============================================================

def test_model_renders_new_schema_and_legacy_keys():
    # New/expected keys
    new_rows = [{
        "transaction_id": 10, "date": "2024-06-01", "transaction_type": "adjustment",
        "product": "Alpha", "quantity": 5.0, "unit_name": "Each", "notes": "ok"
    }]
    m1 = TransactionsTableModel(new_rows)
    assert m1.rowCount() == 1
    assert m1.index(0, 0).data() == 10
    assert m1.index(0, 3).data() == "Alpha"
    assert m1.index(0, 4).data() == "5"

    # Legacy keys tolerated (id/type/qty/uom)
    legacy_rows = [{
        "id": 22, "date": "2024-06-02", "type": "adjustment",
        "product": "Beta", "qty": -3, "uom": "Each", "notes": None
    }]
    m2 = TransactionsTableModel(legacy_rows)
    assert m2.rowCount() == 1
    assert m2.index(0, 0).data() == 22
    assert m2.index(0, 3).data() == "Beta"
    assert m2.index(0, 4).data() == "-3"

def test_model_replace_and_alignment():
    m = TransactionsTableModel([])
    assert m.rowCount() == 0
    m.replace([{
        "transaction_id": 1, "date": "2024-01-01", "transaction_type": "adjustment",
        "product": "P", "quantity": 1.25, "unit_name": "Each", "notes": ""
    }])
    assert m.rowCount() == 1
    # header alignment (ID, Qty right-aligned)
    assert m.headerData(0, Qt.Horizontal, Qt.TextAlignmentRole) == int(Qt.AlignRight | Qt.AlignVCenter)
    assert m.headerData(4, Qt.Horizontal, Qt.TextAlignmentRole) == int(Qt.AlignRight | Qt.AlignVCenter)


# ============================================================
# C) Controller wiring: tabs exist & recent loads
# ============================================================

def test_inventory_controller_builds_three_tabs_and_recent_loads(qtbot, conn):
    # Seed one txn so recent tab shows something
    uom = _mk_uom(conn, "Each")
    p = _mk_product(conn, "CTRL-Prod", uom)
    _seed_txn(conn, product_id=p, uom_id=uom, qty=2, dte=_today(0), notes="controller")

    c = InventoryController(conn, current_user=None)
    qtbot.addWidget(c.get_widget())
    w = c.get_widget()

    # confirm 3 tabs
    from PySide6.QtWidgets import QTabWidget
    tab = w.findChild(QTabWidget)
    assert tab is not None
    assert tab.count() >= 3
    assert tab.tabText(0).lower().startswith("adjustments")
    assert tab.tabText(1).lower().startswith("transactions")
    assert tab.tabText(2).lower().startswith("stock valuation")

    # recent table should have rows
    tv = c.view.tbl_recent
    assert tv.model() is not None
    assert tv.model().rowCount() >= 1


# ============================================================
# D) TransactionsView: defaults, filters, export
# ============================================================

def test_transactions_view_defaults_today_and_limit(qtbot, conn):
    v = TransactionsView(conn)
    qtbot.addWidget(v)
    # From/To default to today (not 1900)
    assert v.date_from.date() == QDate.currentDate()
    assert v.date_to.date() == QDate.currentDate()
    # Limit default 100
    assert v.limit_value == 100

def test_transactions_view_filters_and_reload(qtbot, conn):
    uom = _mk_uom(conn, "Each")
    p1 = _mk_product(conn, "TV-P1", uom)
    p2 = _mk_product(conn, "TV-P2", uom)
    _seed_txn(conn, product_id=p1, uom_id=uom, qty=1, dte=_today(-1))
    _seed_txn(conn, product_id=p2, uom_id=uom, qty=2, dte=_today(0))

    v = TransactionsView(conn)
    qtbot.addWidget(v)

    # Widen date range so yesterday's row is included (default is today→today)
    v.date_from.setDate(QDate.currentDate().addDays(-30))
    v.date_to.setDate(QDate.currentDate())

    # product filter = p1
    idx = v.cmb_product.findData(p1)
    assert idx >= 0
    v.cmb_product.setCurrentIndex(idx)
    v._reload()
    assert v.tbl_txn.model().rowCount() >= 1
    # ensure only P1 appears
    prods = [v.tbl_txn.model().index(r, 3).data() for r in range(v.tbl_txn.model().rowCount())]
    assert all(p == "TV-P1" for p in prods)

    # date range filter to exclude all (future only)
    v.date_from.setDate(QDate.currentDate().addDays(1))
    v.date_to.setDate(QDate.currentDate().addDays(2))
    v._reload()
    assert v.tbl_txn.model().rowCount() == 0

def test_transactions_view_export_csv(qtbot, conn, tmp_path, monkeypatch):
    uom = _mk_uom(conn, "Each")
    p = _mk_product(conn, "CSV-P", uom)
    _seed_txn(conn, product_id=p, uom_id=uom, qty=3.5, dte=_today(0), notes="csv")

    v = TransactionsView(conn)
    qtbot.addWidget(v)
    v._reload()

    out = tmp_path / "tx.csv"
    monkeypatch.setattr(
        "inventory_management.modules.inventory.transactions.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), "CSV Files (*.csv)")
    )
    v._on_export_csv()
    assert out.exists()
    txt = out.read_text(encoding="utf-8").strip().splitlines()
    assert txt and txt[0].lower().startswith("id,")  # header
    assert any("CSV-P" in line for line in txt[1:])  # data row present


# ============================================================
# E) StockValuationWidget: product load & snapshot
# ============================================================

def test_stock_valuation_loads_products_and_snapshot(qtbot, conn):
    uom = _mk_uom(conn, "Each")
    p = _mk_product(conn, "SV-Prod", uom)

    # Build a temp v_stock_on_hand view compatible with your schema
    conn.execute("DROP VIEW IF EXISTS v_stock_on_hand")

    has_prod_uom_id = _has_column(conn, "products", "uom_id")
    has_prod_def_uom = _has_column(conn, "products", "default_uom_id")

    if has_prod_uom_id:
        uom_join = "JOIN uoms ON uoms.uom_id = products.uom_id"
    elif has_prod_def_uom:
        uom_join = "JOIN uoms ON uoms.uom_id = products.default_uom_id"
    else:
        uom_join = "LEFT JOIN uoms ON 1=0"  # uom_name will be NULL -> COALESCE

    conn.execute(
        f"""
        CREATE VIEW v_stock_on_hand AS
        SELECT
            products.product_id              AS product_id,
            products.name                    AS product_name,
            COALESCE(uoms.unit_name, 'Each') AS uom_name,
            7.0                              AS on_hand_qty,
            3.00                             AS unit_value,
            21.00                            AS total_value
        FROM products
        {uom_join}
        """
    )

    w = StockValuationWidget(conn)
    qtbot.addWidget(w)

    # First item must be "(Select…)" -> None
    assert w.cmb_product.count() >= 1
    assert w.cmb_product.itemData(0) is None

    # choose our product and refresh
    idx = w.cmb_product.findData(p)
    assert idx >= 0
    w.cmb_product.setCurrentIndex(idx)
    w._refresh_clicked()

    # Read labels
    on_hand = w.val_on_hand.text()
    unit = w.val_unit_value.text()
    total = w.val_total_value.text()
    assert "7.00" in on_hand
    assert unit == "3.00"
    assert total == "21.00"
