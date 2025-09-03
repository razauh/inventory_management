"""
Tests for the sales module.

This suite covers the table models, repository operations, payment
validations, and return form UI logic.  The goal is to provide
equivalent coverage to the purchase/vendor test suites by exercising
creation, editing, deletion, search and aggregation flows, as well as
edge cases (quotations vs sales, payment method rules, return
calculations, overshoot guards, refund caps, and payload shapes).

Many tests use in-memory SQLite databases to isolate state from the
shared test database.  Where possible the repo logic is exercised
directly, while the return form UI tests use stubbed repo methods
instead of a full database.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem, QMessageBox

from inventory_management.modules.sales.model import SalesTableModel, SaleItemsModel
from inventory_management.database.repositories.sales_repo import (
    SalesRepo,
    SaleHeader,
    SaleItem,
)
from inventory_management.database.repositories.sale_payments_repo import SalePaymentsRepo
from inventory_management.modules.sales.return_form import SaleReturnForm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(schema_sql: str) -> sqlite3.Connection:
    """
    Create an in-memory SQLite database and apply the provided schema.
    Returns a connection with row_factory set.
    """
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    con.executescript(schema_sql)
    return con


def _simple_schema() -> str:
    """
    Returns a minimal schema for sales, customers, items, products, uoms,
    inventory transactions, sale_detailed_totals and sale_payments.  Used
    by repo tests below.
    """
    return """
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL
);
CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  name TEXT
);
CREATE TABLE uoms (
  uom_id INTEGER PRIMARY KEY,
  unit_name TEXT
);
CREATE TABLE sales (
  sale_id TEXT PRIMARY KEY,
  customer_id INTEGER,
  date TEXT,
  total_amount REAL,
  order_discount REAL,
  payment_status TEXT,
  paid_amount REAL,
  advance_payment_applied REAL,
  notes TEXT,
  created_by INTEGER,
  source_type TEXT,
  source_id TEXT,
  doc_type TEXT DEFAULT 'sale',
  quotation_status TEXT,
  expiry_date TEXT
);
CREATE TABLE sale_items (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id TEXT,
  product_id INTEGER,
  quantity REAL,
  uom_id INTEGER,
  unit_price REAL,
  item_discount REAL
);
CREATE TABLE inventory_transactions (
  transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER,
  quantity REAL,
  uom_id INTEGER,
  transaction_type TEXT,
  reference_table TEXT,
  reference_id TEXT,
  reference_item_id INTEGER,
  date TEXT,
  notes TEXT,
  created_by INTEGER
);
-- view for sale totals used by get_sale_totals
CREATE TABLE sale_detailed_totals (
  sale_id TEXT PRIMARY KEY,
  subtotal_before_order_discount REAL,
  calculated_total_amount REAL
);
-- payments table; triggers not required here for test logic
CREATE TABLE sale_payments (
  payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id TEXT,
  date TEXT,
  amount REAL,
  method TEXT,
  bank_account_id INTEGER,
  instrument_type TEXT,
  instrument_no TEXT,
  instrument_date TEXT,
  deposited_date TEXT,
  cleared_date TEXT,
  clearing_state TEXT,
  ref_no TEXT,
  notes TEXT,
  created_by INTEGER
);
"""


# ---------------------------------------------------------------------------
# Suite G – Sales table models
# ---------------------------------------------------------------------------


def test_g1_sales_table_model_status_logic() -> None:
    """
    G1: SalesTableModel should derive statuses for non-quotation rows and
    use explicit statuses for quotations.  It should also compute
    paid_total = paid_amount + advance_payment_applied and format money.
    """
    from inventory_management.utils.helpers import fmt_money

    # Create rows as sqlite3.Row-like dicts
    Row = dict  # simple dict suffices for model
    rows = [
        # paid sale: paid_amount + advance >= total
        Row(
            sale_id="S1",
            date="2025-01-01",
            customer_name="Alice",
            total_amount=100.0,
            order_discount=0.0,
            paid_amount=80.0,
            advance_payment_applied=20.0,
            payment_status="",
            notes=None,
        ),
        # partial sale: paid+advance < total
        Row(
            sale_id="S2",
            date="2025-01-02",
            customer_name="Bob",
            total_amount=200.0,
            order_discount=0.0,
            paid_amount=50.0,
            advance_payment_applied=50.0,
            payment_status="",
            notes=None,
        ),
        # unpaid sale
        Row(
            sale_id="S3",
            date="2025-01-03",
            customer_name="Carol",
            total_amount=150.0,
            order_discount=0.0,
            paid_amount=0.0,
            advance_payment_applied=0.0,
            payment_status="",
            notes=None,
        ),
        # quotation: status should use existing payment_status (e.g., 'draft')
        Row(
            sale_id="Q1",
            date="2025-01-04",
            customer_name="Dave",
            total_amount=50.0,
            order_discount=0.0,
            paid_amount=0.0,
            advance_payment_applied=0.0,
            payment_status="unpaid",
            notes=None,
        ),
    ]
    # Mark last row as a quotation by giving it a quotation marker in payment_status.
    # The SalesTableModel treats certain statuses (draft/sent/accepted/expired/cancelled)
    # as quotations and bypasses computed status.  Setting payment_status to "draft"
    # ensures the last row is treated as a quotation without modifying doc_type.
    rows[-1]["payment_status"] = "draft"
    model = SalesTableModel(rows)
    # Row count
    assert model.rowCount() == 4
    # Check status logic and paid_total formatting
    def _get_display(r: int, c: int) -> Any:
        return model.data(model.index(r, c), Qt.DisplayRole)

    # Column indices: 0=SO, 3=Total, 4=Paid, 5=Status
    # Row 0: paid
    # Paid column: paid_total = 80 + 20 = 100
    assert _get_display(0, 4) == fmt_money(100.0)
    assert _get_display(0, 5).lower() == "paid"
    # Row 1: partial
    assert _get_display(1, 5).lower() == "partial"
    # Row 2: unpaid
    assert _get_display(2, 5).lower() == "unpaid"
    # Row 3: quotation retains existing payment_status ('draft')
    assert _get_display(3, 5) == "draft"


def test_g2_sale_items_model_line_total() -> None:
    """
    G2: SaleItemsModel should compute line total = qty × (unit_price – item_discount)
    and format money correctly.
    """
    from inventory_management.utils.helpers import fmt_money

    Row = dict
    rows = [
        Row(
            item_id=1,
            sale_id="S1",
            product_id=1,
            product_name="Widget",
            quantity=2.0,
            uom_id=1,
            unit_name="pcs",
            unit_price=50.0,
            item_discount=5.0,
        ),
        Row(
            item_id=2,
            sale_id="S1",
            product_id=2,
            product_name="Gadget",
            quantity=1.0,
            uom_id=1,
            unit_name="pcs",
            unit_price=20.0,
            item_discount=0.0,
        ),
    ]
    model = SaleItemsModel(rows)
    assert model.rowCount() == 2
    # Line total column index 5 (0-based) for display (ItemID, Product, Qty, Unit Price, Discount, Line Total)
    lt1 = model.data(model.index(0, 5), Qt.DisplayRole)
    lt2 = model.data(model.index(1, 5), Qt.DisplayRole)
    # line totals: (2*(50-5))=90 and (1*(20-0))=20
    assert lt1 == fmt_money(90.0)
    assert lt2 == fmt_money(20.0)


# ---------------------------------------------------------------------------
# Suite H – SalesRepo (sales & quotations)
# ---------------------------------------------------------------------------


def test_h1_list_and_search_sales() -> None:
    """
    H1: list_sales() returns only real SALES; search_sales() filters by query,
    date and doc_type correctly.
    """
    con = _make_db(_simple_schema())
    # Seed customers and products
    con.execute("INSERT INTO customers(name) VALUES ('Alice')")
    con.execute("INSERT INTO customers(name) VALUES ('Bob')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('S1', 1, '2025-01-01', 100.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('Q1', 2, '2025-01-02', 50.0, 0.0, 'unpaid', 0.0, 0.0, 'quotation')")
    repo = SalesRepo(con)
    sales = repo.list_sales()
    assert len(sales) == 1 and sales[0]["sale_id"] == "S1"
    # search_sales default doc_type='sale' should exclude quotation
    res = repo.search_sales(query="S", date=None)
    assert all(r["sale_id"].startswith("S") for r in res)
    # search for quotation by doc_type
    res_q = repo.search_sales(query="Q", date=None, doc_type="quotation")
    assert len(res_q) == 1 and res_q[0]["sale_id"] == "Q1"
    # search by customer name substring
    res2 = repo.search_sales(query="Alice")
    assert len(res2) == 1 and res2[0]["sale_id"] == "S1"
    # search by date
    res3 = repo.search_sales(date="2025-01-02")
    assert len(res3) == 0  # default doc_type='sale' excludes quotation on that date


def test_h2_create_and_update_sale() -> None:
    """
    H2: create_sale inserts header, items and inventory; update_sale rebuilds
    items and inventory and raises if editing a non-sale row.
    """
    con = _make_db(_simple_schema())
    # Seed supporting tables
    con.executemany("INSERT INTO customers(name) VALUES (?)", [("Cust",),])
    con.executemany("INSERT INTO products(product_id, name) VALUES (?,?)", [(1, "Widget"),])
    con.executemany("INSERT INTO uoms(uom_id, unit_name) VALUES (?,?)", [(1, "pcs"),])
    repo = SalesRepo(con)
    # Create sale header and items
    header = SaleHeader(
        sale_id="S1", customer_id=1, date="2025-01-10", total_amount=100.0,
        order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
        advance_payment_applied=0.0, notes=None, created_by=None
    )
    items = [SaleItem(item_id=None, sale_id="", product_id=1, quantity=2.0, uom_id=1, unit_price=25.0, item_discount=0.0)]
    repo.create_sale(header, items)
    # Verify sale and item rows
    row = con.execute("SELECT * FROM sales WHERE sale_id='S1'").fetchone()
    assert row["total_amount"] == 100.0
    it = con.execute("SELECT * FROM sale_items WHERE sale_id='S1'").fetchone()
    assert it is not None and it["product_id"] == 1
    inv = con.execute("SELECT * FROM inventory_transactions WHERE reference_id='S1'").fetchone()
    assert inv is not None and inv["transaction_type"] == "sale"
    # Update sale: change total and quantity
    header2 = SaleHeader(
        sale_id="S1", customer_id=1, date="2025-01-11", total_amount=200.0,
        order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
        advance_payment_applied=0.0, notes="updated", created_by=None
    )
    items2 = [SaleItem(item_id=None, sale_id="", product_id=1, quantity=4.0, uom_id=1, unit_price=50.0, item_discount=0.0)]
    repo.update_sale(header2, items2)
    # After update, sale row should reflect new total and notes
    row2 = con.execute("SELECT * FROM sales WHERE sale_id='S1'").fetchone()
    assert row2["total_amount"] == 200.0 and row2["notes"] == "updated"
    # Items should be rebuilt: exactly one item with quantity=4.0
    items_rows = con.execute("SELECT * FROM sale_items WHERE sale_id='S1'").fetchall()
    assert len(items_rows) == 1 and items_rows[0]["quantity"] == 4.0
    # Inventory rows should be rebuilt: one row with quantity=4.0
    inv_rows = con.execute("SELECT * FROM inventory_transactions WHERE reference_id='S1'").fetchall()
    assert len(inv_rows) == 1 and inv_rows[0]["quantity"] == 4.0
    # Attempt update on nonexistent/quotation should raise
    with pytest.raises(ValueError):
        bad_header = SaleHeader(
            sale_id="NOPE", customer_id=1, date="2025-01-12", total_amount=10.0,
            order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
            advance_payment_applied=0.0, notes=None, created_by=None
        )
        repo.update_sale(bad_header, [])


def test_h3_delete_sale() -> None:
    """
    H3: delete_sale removes sale header, items and inventory rows.
    """
    con = _make_db(_simple_schema())
    con.execute("INSERT INTO customers(name) VALUES ('Zed')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('S1', 1, '2025-01-01', 50.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')")
    con.execute("INSERT INTO sale_items(sale_id, product_id, quantity, uom_id, unit_price, item_discount)"
                " VALUES ('S1', 1, 1.0, 1, 50.0, 0.0)")
    con.execute("INSERT INTO inventory_transactions(product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date, notes, created_by)"
                " VALUES (1, 1.0, 1, 'sale', 'sales', 'S1', 1, '2025-01-01', NULL, NULL)")
    repo = SalesRepo(con)
    repo.delete_sale("S1")
    assert con.execute("SELECT * FROM sales WHERE sale_id='S1'").fetchone() is None
    assert con.execute("SELECT * FROM sale_items WHERE sale_id='S1'").fetchone() is None
    assert con.execute("SELECT * FROM inventory_transactions WHERE reference_id='S1'").fetchone() is None


def test_h4_quotation_crud_and_conversion() -> None:
    """
    H4: create_quotation inserts quotation header and items with zeroed payment fields;
    update_quotation rebuilds items and keeps payment fields zero; convert_quotation_to_sale
    copies items, posts inventory, and marks quotation as accepted.
    """
    con = _make_db(_simple_schema())
    # Seed customers/products/uoms
    con.execute("INSERT INTO customers(name) VALUES ('Cust')")
    con.execute("INSERT INTO products(product_id, name) VALUES (1, 'Widget')")
    con.execute("INSERT INTO uoms(uom_id, unit_name) VALUES (1, 'pcs')")
    repo = SalesRepo(con)
    # Create quotation
    q_header = SaleHeader(
        sale_id="Q1", customer_id=1, date="2025-01-01", total_amount=50.0,
        order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
        advance_payment_applied=0.0, notes="quote", created_by=1
    )
    q_items = [SaleItem(item_id=None, sale_id="", product_id=1, quantity=1.0, uom_id=1, unit_price=50.0, item_discount=0.0)]
    repo.create_quotation(q_header, q_items)
    # Header should have doc_type='quotation' and zero payment fields
    h = con.execute("SELECT * FROM sales WHERE sale_id='Q1'").fetchone()
    assert h["doc_type"] == "quotation" and h["paid_amount"] == 0.0 and h["payment_status"] == "unpaid"
    # Items inserted with no inventory
    assert con.execute("SELECT COUNT(*) FROM sale_items WHERE sale_id='Q1'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM inventory_transactions WHERE reference_id='Q1'").fetchone()[0] == 0
    # Update quotation: modify quantity and totals
    q_header_updated = SaleHeader(
        sale_id="Q1", customer_id=1, date="2025-01-02", total_amount=80.0,
        order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
        advance_payment_applied=0.0, notes="updated", created_by=1
    )
    q_items2 = [SaleItem(item_id=None, sale_id="", product_id=1, quantity=2.0, uom_id=1, unit_price=40.0, item_discount=0.0)]
    repo.update_quotation(q_header_updated, q_items2, quotation_status="sent", expiry_date="2025-02-01")
    h2 = con.execute("SELECT * FROM sales WHERE sale_id='Q1'").fetchone()
    assert h2["quotation_status"] == "sent" and h2["expiry_date"] == "2025-02-01"
    # Items count and quantity updated
    items_after = con.execute("SELECT * FROM sale_items WHERE sale_id='Q1'").fetchall()
    assert len(items_after) == 1 and items_after[0]["quantity"] == 2.0
    # Attempt to update a non-quotation should raise
    with pytest.raises(ValueError):
        bad_header = SaleHeader(
            sale_id="BAD", customer_id=1, date="2025-01-03", total_amount=10.0,
            order_discount=0.0, payment_status="unpaid", paid_amount=0.0,
            advance_payment_applied=0.0, notes=None, created_by=1
        )
        repo.update_quotation(bad_header, [])
    # Convert to sale
    # Prepopulate sale_detailed_totals for correct proration; else uses header total
    con.execute("INSERT INTO sale_detailed_totals(sale_id, subtotal_before_order_discount, calculated_total_amount)"
                " VALUES ('Q1', 80.0, 80.0)")
    repo.convert_quotation_to_sale(qo_id="Q1", new_so_id="S2", date="2025-01-10", created_by=2)
    # New sale row
    so = con.execute("SELECT * FROM sales WHERE sale_id='S2'").fetchone()
    assert so is not None and so["doc_type"] == "sale" and so["source_id"] == "Q1"
    # Inventory rows posted for sale
    assert con.execute("SELECT COUNT(*) FROM inventory_transactions WHERE reference_id='S2'").fetchone()[0] > 0
    # Original quotation marked accepted
    assert con.execute("SELECT quotation_status FROM sales WHERE sale_id='Q1'").fetchone()[0] == "accepted"


def test_h5_sale_return_and_totals() -> None:
    """
    H5: record_return inserts sale_return inventory rows and sale_return_totals
    aggregates quantity and value correctly.
    """
    con = _make_db(_simple_schema())
    # Seed base data
    con.execute("INSERT INTO customers(name) VALUES ('F')")
    con.execute("INSERT INTO products(product_id, name) VALUES (1, 'P')")
    con.execute("INSERT INTO uoms(uom_id, unit_name) VALUES (1, 'pc')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('S1', 1, '2025-01-01', 100.0, 0.0, 'unpaid', 100.0, 0.0, 'sale')")
    con.execute("INSERT INTO sale_items(sale_id, product_id, quantity, uom_id, unit_price, item_discount)"
                " VALUES ('S1', 1, 4.0, 1, 25.0, 0.0)")
    repo = SalesRepo(con)
    # Record return: 1 unit returned
    repo.record_return(sid='S1', date='2025-01-05', created_by=None,
                       lines=[{"item_id": 1, "product_id": 1, "uom_id": 1, "qty_return": 1.0}],
                       notes=None)
    # There should be one inventory sale_return
    inv = con.execute("SELECT * FROM inventory_transactions WHERE reference_id='S1' AND transaction_type='sale_return'").fetchone()
    assert inv is not None and inv["quantity"] == 1.0
    # sale_return_totals
    totals = repo.sale_return_totals('S1')
    # Net line price: unit_price-item_discount = 25; 1 returned → qty=1, value=25
    assert totals["qty"] == 1.0 and totals["value"] == 25.0


def test_h6_get_sale_totals() -> None:
    """
    H6: get_sale_totals returns subtotals from view or zeros when missing.
    """
    con = _make_db(_simple_schema())
    repo = SalesRepo(con)
    # When not present, returns zeros
    res = repo.get_sale_totals('NOPE')
    assert res == {"net_subtotal": 0.0, "total_after_od": 0.0}
    # Insert into view
    con.execute("INSERT INTO sale_detailed_totals(sale_id, subtotal_before_order_discount, calculated_total_amount)"
                " VALUES ('S1', 80.0, 100.0)")
    res2 = repo.get_sale_totals('S1')
    assert res2["net_subtotal"] == 80.0 and res2["total_after_od"] == 100.0


# ---------------------------------------------------------------------------
# Suite I – SalePaymentsRepo
# ---------------------------------------------------------------------------


def test_i1_payment_method_validations() -> None:
    """
    I1: _normalize_and_validate enforces per-method rules.
    """
    tmpfd, db_path = tempfile.mkstemp()
    os.close(tmpfd)
    repo = SalePaymentsRepo(db_path)
    # Cash: positive amount, no bank, instrument_type=other, instrument_no optional
    ok = repo._normalize_and_validate(method='Cash', amount=10, bank_account_id=None, instrument_type='other', instrument_no=None)
    assert ok == ('Cash', 10.0, None, 'other', None)
    # Cash negative OK (refund)
    ok2 = repo._normalize_and_validate(method='Cash', amount=-5.0, bank_account_id=None, instrument_type='other', instrument_no=None)
    assert ok2[1] == -5.0
    # Cash zero invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cash', amount=0, bank_account_id=None, instrument_type='other', instrument_no=None)
    # Cash referencing bank invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cash', amount=10, bank_account_id=1, instrument_type='other', instrument_no=None)
    # Bank Transfer: positive amount, requires bank_account_id and instrument_no and itype=online
    ok_bt = repo._normalize_and_validate(method='Bank Transfer', amount=50, bank_account_id=1, instrument_type='online', instrument_no='ref123')
    assert ok_bt == ('Bank Transfer', 50.0, 1, 'online', 'ref123')
    # Negative or zero amount invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Bank Transfer', amount=0, bank_account_id=1, instrument_type='online', instrument_no='ref')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Bank Transfer', amount=-1, bank_account_id=1, instrument_type='online', instrument_no='ref')
    # Missing bank_account_id invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Bank Transfer', amount=10, bank_account_id=None, instrument_type='online', instrument_no='ref')
    # Missing instrument_no invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Bank Transfer', amount=10, bank_account_id=1, instrument_type='online', instrument_no=None)
    # Wrong instrument type invalid
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Bank Transfer', amount=10, bank_account_id=1, instrument_type='other', instrument_no='ref')
    # Cheque validations
    ok_ck = repo._normalize_and_validate(method='Cheque', amount=20, bank_account_id=1, instrument_type='cross_cheque', instrument_no='ch123')
    assert ok_ck == ('Cheque', 20.0, 1, 'cross_cheque', 'ch123')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cheque', amount=-5, bank_account_id=1, instrument_type='cross_cheque', instrument_no='ch123')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cheque', amount=10, bank_account_id=None, instrument_type='cross_cheque', instrument_no='ch')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cheque', amount=10, bank_account_id=1, instrument_type='other', instrument_no='ch')
    # Cash Deposit validations
    ok_cd = repo._normalize_and_validate(method='Cash Deposit', amount=30, bank_account_id=1, instrument_type='cash_deposit', instrument_no='slip1')
    assert ok_cd[3] == 'cash_deposit'
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cash Deposit', amount=0, bank_account_id=1, instrument_type='cash_deposit', instrument_no='slip')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cash Deposit', amount=10, bank_account_id=None, instrument_type='cash_deposit', instrument_no='slip')
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Cash Deposit', amount=10, bank_account_id=1, instrument_type='other', instrument_no='slip')
    # Card/Other: must be positive
    ok_card = repo._normalize_and_validate(method='Card', amount=5, bank_account_id=None, instrument_type='other', instrument_no=None)
    assert ok_card[0] == 'Card'
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Card', amount=0, bank_account_id=None, instrument_type='other', instrument_no=None)
    # Unknown method
    with pytest.raises(ValueError):
        repo._normalize_and_validate(method='Crypto', amount=10, bank_account_id=None, instrument_type='other', instrument_no=None)


def test_i2_record_payment_and_constraints() -> None:
    """
    I2: record_payment inserts receipts and DB triggers should update paid_amount and payment_status.
    The repository accepts payments only for sales.  In this simplified test
    harness we verify that payments on a real sale update the header via a
    trigger.  We do not assert a failure on quotations because our temporary
    schema does not implement that DB constraint.
    """
    # Build DB with minimal triggers: we'll enforce doc_type and paid_amount via Python checks
    schema = _simple_schema() + """
CREATE TRIGGER tr_sale_payments_insert AFTER INSERT ON sale_payments BEGIN
  UPDATE sales SET
    paid_amount = paid_amount + NEW.amount,
    payment_status = CASE WHEN paid_amount + NEW.amount + advance_payment_applied >= total_amount THEN 'paid'
                          WHEN paid_amount + NEW.amount + advance_payment_applied > 0 THEN 'partial'
                          ELSE 'unpaid' END
  WHERE sale_id = NEW.sale_id;
END;
"""
    con = _make_db(schema)
    # Seed a sale and a quotation
    con.execute("INSERT INTO customers(name) VALUES ('X')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('S1', 1, '2025-01-01', 100.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('Q1', 1, '2025-01-02', 80.0, 0.0, 'unpaid', 0.0, 0.0, 'quotation')")
    # Write DB to temp file because SalePaymentsRepo expects a file path
    fd, tmpdb = tempfile.mkstemp()
    os.close(fd)
    b = sqlite3.connect(tmpdb)
    for line in con.iterdump():
        if line.startswith('BEGIN'):
            continue
        b.execute(line)
    b.commit()
    b.close()
    repo = SalePaymentsRepo(tmpdb)
    # Record payment on sale should succeed and update paid_amount
    res_id = repo.record_payment(sale_id='S1', amount=50.0, method='Cash', date='2025-01-03', bank_account_id=None, instrument_type='other', instrument_no=None)
    assert res_id == 1  # first payment id
    # After insertion, paid_amount and payment_status updated
    c = sqlite3.connect(tmpdb)
    c.row_factory = sqlite3.Row
    h = c.execute("SELECT paid_amount, payment_status FROM sales WHERE sale_id='S1'").fetchone()
    assert h['paid_amount'] == 50.0 and h['payment_status'] == 'partial'
    c.close()
    # Recording a payment against a quotation is ignored in real DB via triggers,
    # but our minimal schema does not enforce this.  We therefore call it to
    # ensure it does not crash; however we make no assertion about its effect.
    repo.record_payment(sale_id='Q1', amount=10.0, method='Cash', date='2025-01-04', bank_account_id=None, instrument_type='other', instrument_no=None)


def test_i3_update_clearing_state_and_list() -> None:
    """
    I3: update_clearing_state should update clearing_state, dates and listing functions should order payments chronologically.
    """
    # Minimal DB schema for clearing tests
    schema = _simple_schema() + """
CREATE TABLE company_bank_accounts (
  bank_account_id INTEGER PRIMARY KEY,
  bank_name TEXT
);
"""
    con = _make_db(schema)
    con.execute("INSERT INTO customers(name) VALUES ('Y')")
    con.execute("INSERT INTO sales(sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, doc_type)"
                " VALUES ('S1', 1, '2025-01-01', 100.0, 0.0, 'unpaid', 0.0, 0.0, 'sale')")
    con.execute("INSERT INTO company_bank_accounts(bank_name) VALUES ('Bank1')")
    # Write DB to temp file
    fd, tmpdb = tempfile.mkstemp(); os.close(fd)
    b = sqlite3.connect(tmpdb)
    for line in con.iterdump():
        if line.startswith('BEGIN'):
            continue
        b.execute(line)
    b.commit(); b.close()
    repo = SalePaymentsRepo(tmpdb)
    # Insert pending cheque payment
    pid = repo.record_payment(sale_id='S1', amount=30.0, method='Cheque', date='2025-01-02', bank_account_id=1, instrument_type='cross_cheque', instrument_no='chk001')
    # Initially clearing_state should be default (pending) and no cleared_date
    conn = sqlite3.connect(tmpdb)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT clearing_state, cleared_date FROM sale_payments WHERE payment_id=?", (pid,)).fetchone()
    assert row['clearing_state'] == 'pending' and row['cleared_date'] is None
    # Update to cleared.  The update_clearing_state API requires specifying the clearing_state
    # string and optional date fields.  We set clearing_state='cleared' and provide the
    # cleared_date.  (deposit and instrument dates remain None.)
    repo.update_clearing_state(payment_id=pid, clearing_state='cleared', cleared_date='2025-01-05')
    row2 = conn.execute("SELECT clearing_state, cleared_date FROM sale_payments WHERE payment_id=?", (pid,)).fetchone()
    assert row2['clearing_state'] == 'cleared' and row2['cleared_date'] == '2025-01-05'
    # Add another payment to test ordering
    repo.record_payment(sale_id='S1', amount=20.0, method='Cash', date='2025-01-03', bank_account_id=None, instrument_type='other', instrument_no=None)
    # list_by_sale should return in date order ascending
    lst = repo.list_by_sale('S1')
    dates = [p['date'] for p in lst]
    assert dates == sorted(dates)
    # list_by_customer should include all and be sorted similarly
    lst2 = repo.list_by_customer(1)
    dates2 = [p['date'] for p in lst2]
    assert dates2 == sorted(dates2)
    conn.close()


# ---------------------------------------------------------------------------
# Suite J – Sale return UI
# ---------------------------------------------------------------------------


def test_j1_search_and_quick_mode(qtbot: pytest.fixture) -> None:
    """
    J1: _search() should return only real sales (not quotations) and quick mode
    hides search UI and primes the sale.
    """
    # Stub repo with search_sales
    class StubRepo:
        def __init__(self):
            self.called_query = None

        def search_sales(self, query: str = "", date: Optional[str] = None, *, doc_type: str = "sale") -> list[dict]:
            """Return sample sales filtered by doc_type.  The real repo performs this filtering."""
            data = [
                {
                    "sale_id": "S1",
                    "date": "2025-01-01",
                    "customer_name": "Cust",
                    "total_amount": 100.0,
                    "paid_amount": 50.0,
                    "doc_type": "sale",
                    "payment_status": "partial",
                },
                {
                    "sale_id": "Q1",
                    "date": "2025-01-02",
                    "customer_name": "Cust2",
                    "total_amount": 80.0,
                    "paid_amount": 0.0,
                    "doc_type": "quotation",
                    "payment_status": "unpaid",
                },
            ]
            return [r for r in data if r.get("doc_type", "sale") == doc_type]

        def get_header(self, sid: str) -> dict:
            """Return a minimal sale header used when search_sales yields nothing."""
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 100.0,
                "paid_amount": 50.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }

        # Provide list_items so that quick mode can load at least one item
        def list_items(self, sid: str) -> list[dict]:
            return [
                {
                    "item_id": 1,
                    "product_name": "Demo",
                    "quantity": 1.0,
                    "unit_price": 10.0,
                    "item_discount": 0.0,
                    "uom_id": 1,
                    "product_id": 1,
                }
            ]

        # Provide sale totals to support proration when loading items
        def get_sale_totals(self, sale_id: str) -> dict:
            return {"net_subtotal": 10.0, "total_after_od": 10.0}

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    # Trigger search
    form.edt_q.setText("S")
    form._search()
    # Only sale row should appear in tbl_sales (filtered by _is_sale_row)
    assert form.tbl_sales.rowCount() == 1
    assert form.tbl_sales.item(0, 0).text() == "S1"
    # Quick mode: construct with sale_id
    form2 = SaleReturnForm(repo=repo, sale_id="S1")
    # Quick mode should preload the selected sale: verify _selected_sid and that items have loaded
    assert form2._selected_sid == "S1"
    # There should be at least one item row for the primed sale
    assert form2.tbl_items.rowCount() > 0


def test_j2_return_amount_calculation_and_proration(qtbot: pytest.fixture) -> None:
    """
    J2: Verify returned value computation after proration.
    returned_value = sum(qty_return * (unit_price - item_discount)) * (total_after_od / net_subtotal)
    """
    # Stub repo returning sale totals and items
    class StubRepo:
        def search_sales(self, query: str = "", date: Optional[str] = None, *, doc_type: str = "sale") -> list[dict]:
            return []
        def list_items(self, sid: str) -> list[dict]:
            # Two items: price 50 with discount 10, qty sold 2; price 20 no discount, qty sold 1
            return [
                {"item_id": 1, "product_name": "A", "quantity": 2.0, "unit_price": 50.0, "item_discount": 10.0, "uom_id": 1, "product_id": 1},
                {"item_id": 2, "product_name": "B", "quantity": 1.0, "unit_price": 20.0, "item_discount": 0.0, "uom_id": 1, "product_id": 2},
            ]
        def get_sale_totals(self, sale_id: str) -> dict:
            return {"net_subtotal": 110.0, "total_after_od": 100.0}  # order discount 10
        def get_header(self, sid: str) -> dict:
            # Return a minimal sale header used by _prime_with_sale_id when search_sales
            # yields no rows.  Provide sale_id, date, total_amount, paid_amount and doc_type.
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 110.0,
                "paid_amount": 60.0,
                "doc_type": "sale",
                "order_discount": 10.0,
            }

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    # Prime sale with id S1 (quick mode) to load items
    form._prime_with_sale_id("S1")
    # For each row, set qty return: 1 for first, 1 for second
    for r in range(form.tbl_items.rowCount()):
        qty_return_item = "1"
        item = QTableWidgetItem(qty_return_item)
        form.tbl_items.setItem(r, 4, item)
    # Recalculate totals
    form._recalc()
    # Compute expected returned value
    # line net = (2*(50-10) + 1*(20-0)) = 80 + 20 = 100, but we return only 1 each → 40 + 20 = 60
    # proration factor = total_after_od / net_subtotal = 100 / 110 ≈ 0.90909; returned_value = 60 * 0.90909 = 54.545...
    expected = 60.0 * (100.0 / 110.0)
    assert pytest.approx(form._refund_amount) == expected


def test_j3_overshoot_guard(qtbot: pytest.fixture) -> None:
    """
    J3: Setting qty_return greater than sold should mark row as over and ignore it in totals.
    """
    class StubRepo:
        def search_sales(self, *args, **kwargs):
            return []
        def list_items(self, sid):
            return [
                {"item_id": 1, "product_name": "A", "quantity": 2.0, "unit_price": 50.0, "item_discount": 0.0, "uom_id": 1, "product_id": 1},
            ]
        def get_sale_totals(self, sale_id):
            return {"net_subtotal": 100.0, "total_after_od": 100.0}
        def get_header(self, sid):
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 100.0,
                "paid_amount": 0.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    form._prime_with_sale_id("S1")
    # Set qty_return to 3 which exceeds sold quantity 2
    item = QTableWidgetItem("3")
    form.tbl_items.setItem(0, 4, item)
    form._recalc()
    # The cell should be red (over flag) and refund amount should be zero
    assert form.tbl_items.item(0, 4).background().color().red() > 200
    assert form._refund_amount == 0.0


def test_j4_refund_logic_and_caps(qtbot: pytest.fixture) -> None:
    """
    J4: Refund checkbox enables spin and caps cash refund at min(returned_value, paid_amount).
    When paid_amount is zero, refund remains disabled and cash refund zero.
    """
    class StubRepo:
        def search_sales(self, *args, **kwargs):
            return []
        def list_items(self, sid):
            return [
                {"item_id": 1, "product_name": "A", "quantity": 1.0, "unit_price": 50.0, "item_discount": 0.0, "uom_id": 1, "product_id": 1},
            ]
        def get_sale_totals(self, sale_id):
            return {"net_subtotal": 50.0, "total_after_od": 50.0}
        def get_header(self, sid):
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 50.0,
                "paid_amount": 30.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    form._prime_with_sale_id("S1")
    # Set return quantity 1
    form.tbl_items.setItem(0, 4, QTableWidgetItem("1"))
    form._recalc()
    # Without checking the refund box, the spinner should be enabled when there was a payment
    # and auto-set to the cap (min(returned_value, paid_amount)).  Here, returned_value=50, paid=30 → cap=30.
    assert form.spin_cash.isEnabled() is True
    assert form.spin_cash.value() == 30.0
    # Check label cap text includes the correct maximum
    cap_text = form.lbl_cash_cap.text()
    assert "max" in cap_text and "30" in cap_text  # cap equal to paid amount because returned_value >= paid
    # Toggle refund to enable spin
    form.chk_refund.setChecked(True)
    form._on_refund_toggle(True)
    assert form.spin_cash.isEnabled()
    # Cap should be <= returned_value and paid_amount; refund_value = 50, paid=30 → cap=30
    assert form.spin_cash.maximum() == 30.0
    # Changing cash value below cap updates note; set to 20
    form.spin_cash.setValue(20.0)
    form._on_cash_changed(20.0)
    assert "Paying" in form.lbl_note.text()
    # When paid_amount=0, spinner should remain disabled and zero even after toggling refund
    class StubRepo2(StubRepo):
        def get_header(self, sid):
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 50.0,
                "paid_amount": 0.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }
    form2 = SaleReturnForm(repo=StubRepo2())
    form2._prime_with_sale_id("S1")
    form2.tbl_items.setItem(0, 4, QTableWidgetItem("1"))
    form2._recalc()
    form2.chk_refund.setChecked(True)
    form2._on_refund_toggle(True)
    assert form2.spin_cash.isEnabled() is False
    assert form2.spin_cash.value() == 0.0


def test_j5_return_all_toggle(qtbot: pytest.fixture) -> None:
    """
    J5: Toggling return-all should populate qty_return equal to qty sold for all lines and update totals.
    """
    class StubRepo:
        def search_sales(self, *args, **kwargs): return []
        def list_items(self, sid):
            return [
                {"item_id": 1, "product_name": "A", "quantity": 2.0, "unit_price": 10.0, "item_discount": 0.0, "uom_id": 1, "product_id": 1},
                {"item_id": 2, "product_name": "B", "quantity": 3.0, "unit_price": 20.0, "item_discount": 0.0, "uom_id": 1, "product_id": 2},
            ]
        def get_sale_totals(self, sale_id): return {"net_subtotal": 80.0, "total_after_od": 80.0}
        def get_header(self, sid):
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 80.0,
                "paid_amount": 0.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    form._prime_with_sale_id("S1")
    # Toggle return all
    form.chk_return_all.setChecked(True)
    form._toggle_return_all(True)
    # Each qty_return cell should equal qty sold
    for r in range(form.tbl_items.rowCount()):
        sold = float(form.tbl_items.item(r, 2).text())
        qty_return = float(form.tbl_items.item(r, 4).text())
        assert qty_return == sold
    # Refund amount equals sum(qty*unit_net) * factor (factor=1 here)
    expected = (2*10.0 + 3*20.0)  # 2*10 + 3*20 = 80
    assert pytest.approx(form._refund_amount) == expected


def test_j6_payload_shape(qtbot: pytest.fixture) -> None:
    """
    J6: get_payload() after adjustments returns proper structure.
    """
    class StubRepo:
        def search_sales(self, *args, **kwargs): return []
        def list_items(self, sid):
            return [
                {"item_id": 1, "product_name": "A", "quantity": 2.0, "unit_price": 10.0, "item_discount": 0.0, "uom_id": 1, "product_id": 1},
            ]
        def get_sale_totals(self, sale_id): return {"net_subtotal": 20.0, "total_after_od": 20.0}
        def get_header(self, sid):
            return {
                "sale_id": sid,
                "date": "2025-01-01",
                "total_amount": 20.0,
                "paid_amount": 5.0,
                "doc_type": "sale",
                "order_discount": 0.0,
            }

    repo = StubRepo()
    form = SaleReturnForm(repo=repo)
    form._prime_with_sale_id("S1")
    # Set qty_return 1 and enable refund
    form.tbl_items.setItem(0, 4, QTableWidgetItem("1"))
    form._recalc()
    form.chk_refund.setChecked(True)
    form._on_refund_toggle(True)
    form.spin_cash.setValue(5.0)
    form._on_cash_changed(5.0)
    payload = form.get_payload()
    assert payload is not None
    assert payload["sale_id"] == "S1"
    assert payload["lines"] == [{"item_id": 1, "qty_return": 1.0}]
    assert payload["refund_now"] is True
    # refund_amount equals refund amount after proration (here 10) and cash_refund_now equals spin value
    assert payload["refund_amount"] == form._refund_amount
    assert payload["cash_refund_now"] == 5.0
