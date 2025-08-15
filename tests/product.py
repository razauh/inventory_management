import os
import sqlite3
import tempfile
import pytest

from inventory_management.database.schema import init_schema
from inventory_management.database.repositories.products_repo import ProductsRepo

@pytest.fixture()
def conn():
    # Use a real temp file to ensure triggers/views behave like production.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        init_schema(tmp.name)
        c = sqlite3.connect(tmp.name)
        c.execute("PRAGMA foreign_keys=ON;")
        yield c
    finally:
        try:
            c.close()
        except Exception:
            pass
        os.unlink(tmp.name)

def test_add_product_with_base_and_alt(conn):
    repo = ProductsRepo(conn)
    pid = repo.add_product(
        name="Cloth Roll",
        description="Grey cloth",
        category="Textiles",
        min_stock_level=5,
        base_uom_name="Bundle",
        sale_alt_uoms=[("Yard", 90)],
    )
    assert isinstance(pid, int)

    # Verify row appears in listing
    rows = repo.list_products()
    assert any(r.name == "Cloth Roll" and r.base_uom == "Bundle" and r.alt_uoms_count == 1 for r in rows)

    base, alts = repo.get_product_uoms(pid)
    assert base == "Bundle"
    assert ("Yard", 90.0) in alts

def test_duplicate_name_blocked(conn):
    repo = ProductsRepo(conn)
    repo.add_product("ItemA", None, None, 0, "Piece", [])
    with pytest.raises(ValueError):
        repo.add_product("ItemA", None, None, 0, "Piece", [])

def test_alt_cannot_equal_base(conn):
    repo = ProductsRepo(conn)
    with pytest.raises(ValueError):
        repo.add_product("ItemB", None, None, 0, "Piece", [("Piece", 2)])

def test_alt_factor_must_be_positive(conn):
    repo = ProductsRepo(conn)
    with pytest.raises(ValueError):
        repo.add_product("ItemC", None, None, 0, "Piece", [("Box", 0)])

def test_edit_delete_not_allowed(conn):
    repo = ProductsRepo(conn)
    repo.add_product("ItemD", None, None, 0, "Piece", [])
    with pytest.raises(PermissionError):
        repo.update_product()
    with pytest.raises(PermissionError):
        repo.delete_product(1)

def test_schema_enforces_purchase_base_only(conn):
    """
    Proves current schema blocks purchase_items in a non-base UOM.
    """
    repo = ProductsRepo(conn)
    pid = repo.add_product("ItemE", None, None, 0, "Bundle", [("Yard", 90)])

    # create vendor + purchase header
    cur = conn.execute("INSERT INTO vendors(name, contact_info) VALUES(?,?)", ("V1", "x"))
    vendor_id = cur.lastrowid
    conn.execute(
        "INSERT INTO purchases(purchase_id, vendor_id, date, total_amount, payment_status) VALUES(?,?,?,?,?)",
        ("P-1", vendor_id, "2025-08-01", 0, "unpaid"),
    )

    # get uoms
    base_uom_id = conn.execute("""
        SELECT u.uom_id FROM product_uoms pu
        JOIN uoms u ON u.uom_id = pu.uom_id
        WHERE pu.product_id=? AND pu.is_base=1
    """, (pid,)).fetchone()[0]
    alt_uom_id = conn.execute("""
        SELECT u.uom_id FROM product_uoms pu
        JOIN uoms u ON u.uom_id = pu.uom_id
        WHERE pu.product_id=? AND pu.is_base=0
        LIMIT 1
    """, (pid,)).fetchone()[0]

    # Base UOM purchase should succeed
    conn.execute("""
        INSERT INTO purchase_items(purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount)
        VALUES (?,?,?,?,?,?,?)
    """, ("P-1", pid, 1, base_uom_id, 100, 120, 0))

    # Non-base UOM purchase should fail by trigger
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO purchase_items(purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount)
            VALUES (?,?,?,?,?,?,?)
        """, ("P-1", pid, 1, alt_uom_id, 100, 120, 0))
