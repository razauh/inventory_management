#!/usr/bin/env python3
"""
Seed script to create a single massive purchase order with all products at 1000 quantity each.
Useful for testing the application without manually creating purchase orders.
"""

import sqlite3
import random
from datetime import datetime
from pathlib import Path


def create_massive_po(db_path: str = "data/myshop.db"):
    """
    Create a single massive purchase order with all available products at 1000 quantity each.
    """
    # Resolve database path relative to project root (parent of database directory)
    script_dir = Path(__file__).parent  # This is database/seeders/
    project_root = script_dir.parent.parent  # This is the project root
    db_file = project_root / db_path  # This should be project_root/data/myshop.db

    if not db_file.exists():
        print(f"Database file not found: {db_file}")
        return

    print("Connecting to database...")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    cur = conn.cursor()

    try:
        print("Starting creation of massive purchase order...")

        # Get all products
        print("Fetching products...")
        products = cur.execute("SELECT product_id, name FROM products").fetchall()
        
        if not products:
            print("No products found in database. Please seed products first.")
            return

        print(f"Found {len(products)} products to include in the purchase order.")

        # Get or create a vendor
        vendor_row = cur.execute("SELECT vendor_id FROM vendors LIMIT 1").fetchone()
        if not vendor_row:
            print("No vendor found, creating a default vendor...")
            cur.execute(
                "INSERT INTO vendors (name, contact_info, address) VALUES (?, ?, ?)",
                ("Default Supplier", "supplier@example.com | +1-555-0000", "123 Supply Street")
            )
            vendor_id = cur.lastrowid
            conn.commit()
        else:
            vendor_id = vendor_row["vendor_id"]

        # Get or create a default user
        user_row = cur.execute("SELECT user_id FROM users LIMIT 1").fetchone()
        if not user_row:
            print("No user found, creating a default user...")
            # Create a default admin user with a simple password hash
            # Using the same approach as in default_data.py
            from utils.auth import hash_password
            cur.execute(
                "INSERT INTO users (username, password_hash, full_name, email, role, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                ("admin", hash_password("admin"), "Administrator", "admin@example.com", "admin")
            )
            user_id = cur.lastrowid
            conn.commit()
        else:
            user_id = user_row["user_id"]

        # Get base UOMs for products
        print("Fetching base UOMs for products...")
        product_uoms = {}
        for product_id, _ in products:
            # Get base UOM for this product
            uom_row = cur.execute(
                "SELECT uom_id FROM product_uoms WHERE product_id = ? AND is_base = 1 LIMIT 1",
                (product_id,)
            ).fetchone()
            
            if uom_row:
                product_uoms[product_id] = uom_row["uom_id"]
            else:
                # If no base UOM found, use the first UOM for this product
                alt_uom_row = cur.execute(
                    "SELECT uom_id FROM product_uoms WHERE product_id = ? LIMIT 1",
                    (product_id,)
                ).fetchone()
                
                if alt_uom_row:
                    product_uoms[product_id] = alt_uom_row["uom_id"]
                else:
                    print(f"Warning: No UOM found for product {product_id}. Skipping this product.")
                    continue

        # Generate unique purchase ID
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        purchase_id = f"MASSIVE_PO_{current_time}"
        
        print(f"Creating massive purchase order: {purchase_id}")
        print(f"Number of products to include: {len(product_uoms)}")

        # Create purchase header
        total_amount = 0.0
        purchase_items = []

        for product_id in product_uoms:
            # Get product details to generate appropriate pricing
            product_row = cur.execute(
                "SELECT name FROM products WHERE product_id = ?", (product_id,)
            ).fetchone()
            product_name = product_row["name"]

            # Use a fixed quantity of 1000 for each product
            quantity = 1000

            # Generate realistic pricing based on product name or random values
            # Using a simple method to generate different prices for different products
            base_price = (hash(product_name) % 1000) + 10  # Random price between 10 and 1010
            purchase_price = round(base_price, 2)
            sale_price = round(purchase_price * 1.2, 2)  # 20% markup
            item_discount = 0.0  # No discount for simplicity

            item_total = quantity * (purchase_price - item_discount)
            total_amount += item_total

            purchase_items.append((
                purchase_id, 
                product_id, 
                quantity, 
                product_uoms[product_id], 
                purchase_price, 
                sale_price, 
                item_discount
            ))

        # Insert purchase header
        purchase_date = datetime.now().strftime("%Y-%m-%d")
        cur.execute("""
            INSERT INTO purchases
            (purchase_id, vendor_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, notes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            purchase_id, 
            vendor_id, 
            purchase_date, 
            total_amount, 
            0,  # order_discount
            'unpaid', 
            0,  # paid_amount 
            0,  # advance_payment_applied
            f"Massive PO with all products at 1000 units each", 
            user_id
        ))

        # Insert purchase items
        print(f"Inserting {len(purchase_items)} purchase items...")
        cur.executemany("""
            INSERT INTO purchase_items
            (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, purchase_items)

        # Create inventory transactions for the purchase
        print("Creating inventory transactions...")
        for i, (po_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount) in enumerate(purchase_items):
            # Get the item_id of the purchase item
            item_row = cur.execute("""
                SELECT item_id FROM purchase_items
                WHERE purchase_id = ? AND product_id = ? AND uom_id = ?
                ORDER BY item_id DESC LIMIT 1
            """, (po_id, product_id, uom_id)).fetchone()
            item_id = item_row["item_id"]

            cur.execute("""
                INSERT INTO inventory_transactions
                (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id,
                 date, posted_at, txn_seq, notes, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id, 
                quantity, 
                uom_id, 
                'purchase', 
                'purchases', 
                po_id,
                item_id, 
                purchase_date, 
                datetime.now().isoformat(), 
                i,  # txn_seq
                f"Massive PO inventory for {po_id}", 
                user_id
            ))

        conn.commit()
        
        print(f"\nSuccessfully created massive purchase order '{purchase_id}' with:")
        print(f"- {len(purchase_items)} line items")
        print(f"- 1000 units of each product")
        print(f"- Total amount: {total_amount}")
        print("The PO should now be visible in your application!")

    except Exception as e:
        print(f"Error creating massive purchase order: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    create_massive_po()