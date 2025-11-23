import pytest
import sqlite3

def test_db_integrity_base_uom_only(conn, ids):
    """Test that purchases must use the product base UoM (trigger enforcement)."""
    # Create a purchase
    conn.execute("""
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-FAIL', ?, '2023-01-01', 100, 'unpaid')
    """, (ids["vendor_id"],))
    
    # Try to insert item with non-base UoM (Box)
    # Assuming Widget A has Base=Piece, and we try Box (if defined)
    # We need to ensure Box is NOT base.
    # Seed data: Widget A -> Piece (Base). Box exists but not mapped to Widget A in seed?
    # Let's map Box to Widget A as non-base first
    conn.execute("""
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 0, 10)
    """, (ids["prod_A"], ids["uom_box"]))
    
    # Now try to purchase in Box
    with pytest.raises(sqlite3.IntegrityError, match="must use the product base UoM"):
        conn.execute("""
            INSERT INTO purchase_items (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price)
            VALUES ('PO-FAIL', ?, 1, ?, 100, 150)
        """, (ids["prod_A"], ids["uom_box"]))

def test_db_integrity_inventory_ref(conn, ids):
    """Test inventory transaction reference validation."""
    # Try to insert inventory txn with invalid reference
    with pytest.raises(sqlite3.IntegrityError, match="Purchase inventory must reference purchase_items"):
        conn.execute("""
            INSERT INTO inventory_transactions 
            (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date)
            VALUES (?, 10, ?, 'purchase', 'purchases', 'PO-FAKE', 999, '2023-01-01')
        """, (ids["prod_A"], ids["uom_piece"]))
