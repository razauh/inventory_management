#!/usr/bin/env python3
"""
High-value sales seed script for testing payment functionality.

This script creates:
- At least 100 customers
- A huge purchase order to ensure inventory availability
- 1000 sales orders with bills over 100,000
- Complete payment history with initial and later payments
- Double permutation of payments for testing
"""

import sqlite3
import random
from datetime import datetime, timedelta
from typing import List, Tuple
import os

def set_pragmas(conn: sqlite3.Connection):
    """Set SQLite pragmas for performance"""
    cur = conn.cursor()
    pragmas = {
        "journal_mode": "WAL",
        "foreign_keys": 1,
        "synchronous": "NORMAL",
        "temp_store": "MEMORY",
        "cache_size": -200000
    }
    for k, v in pragmas.items():
        cur.execute(f"PRAGMA {k}={v}")
    conn.commit()

def ensure_base_data(conn):
    """Ensure basic data like company info exists"""
    # Create company if not exists
    conn.execute("""
        INSERT OR IGNORE INTO company_info (company_id, company_name, address, logo_path) 
        VALUES (1, 'Test Company', '123 Test Street', '/assets/logo.png')
    """)
    
    # Create company contacts if not exist
    conn.execute("""
        INSERT OR IGNORE INTO company_contacts (company_id, contact_type, contact_value, is_primary) 
        VALUES (1, 'phone', '+1234567890', 1),
               (1, 'email', 'test@testcompany.com', 0),
               (1, 'website', 'https://testcompany.com', 0)
    """)
    
    # Create a default user if not exists
    conn.execute("""
        INSERT OR IGNORE INTO users (username, password_hash, full_name, email, role, is_active) 
        VALUES ('admin', 'admin_hash', 'Admin User', 'admin@testcompany.com', 'admin', 1)
    """)
    
    # Create basic UOMs if not exist
    uoms = [
        "Each", "Box", "Kilogram", "Gram", "Liter", "Milliliter", 
        "Pack", "Dozen", "Meter", "Centimeter", "Inch", "Foot", "Pair", "Set"
    ]
    for uom_name in uoms:
        conn.execute("INSERT OR IGNORE INTO uoms (unit_name) VALUES (?)", (uom_name,))
    
    # Create a basic expense category
    conn.execute("INSERT OR IGNORE INTO expense_categories (name) VALUES ('Test Category')")
    
    # Create a basic bank account
    conn.execute("""
        INSERT OR IGNORE INTO company_bank_accounts (company_id, label, bank_name, account_no, iban, is_active) 
        VALUES (1, 'Main Account', 'Test Bank', '1234567890', 'TEST1234567890', 1)
    """)
    
    conn.commit()

def create_customers(conn, num_customers=100):
    """Create customers for the high-value sales"""
    print(f"Creating {num_customers} customers...")
    
    customers = []
    for i in range(num_customers):
        name = f"High Value Customer {i+1:03d}"
        contact = f"customer{i+1:03d}@testmail.com | +1-555-{1000+i:04d}"
        address = f"{i+1} Premium Avenue, High City"
        customers.append((name, contact, address, 1))  # 1 = is_active
    
    conn.executemany(
        "INSERT OR IGNORE INTO customers (name, contact_info, address, is_active) VALUES (?,?,?,?)",
        customers
    )
    conn.commit()
    
    # Return customer IDs
    cur = conn.execute("SELECT customer_id FROM customers ORDER BY customer_id")
    return [row[0] for row in cur.fetchall()]

def create_products_and_inventory(conn, num_products=50):
    """Create products and set up inventory with a huge purchase order"""
    print(f"Creating {num_products} products...")
    
    # Create products
    products = []
    for i in range(num_products):
        name = f"Premium Product {i+1:03d}"
        desc = f"High-quality premium product {i+1:03d}"
        category = "Premium Goods"
        minlvl = 0  # No minimum stock level for high-value items
        products.append((name, desc, category, minlvl))
    
    conn.executemany(
        "INSERT OR IGNORE INTO products (name, description, category, min_stock_level) VALUES (?,?,?,?)",
        products
    )
    conn.commit()
    
    # Get product IDs
    cur = conn.execute("SELECT product_id, name FROM products ORDER BY product_id")
    product_info = [(row[0], row[1]) for row in cur.fetchall()]
    
    # Create product UOM mappings (all products use 'Each' as base UOM)
    cur = conn.execute("SELECT uom_id FROM uoms WHERE unit_name = 'Each'")
    base_uom_id = cur.fetchone()[0]
    
    product_uom_mappings = []
    for product_id, _ in product_info:
        # Base UOM (Each)
        product_uom_mappings.append((product_id, base_uom_id, 1, 1.0))  # is_base = 1, factor = 1.0
    
    conn.executemany(
        "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?,?,?,?)",
        product_uom_mappings
    )
    conn.commit()
    
    return product_info

def create_huge_purchase_order(conn, product_info, vendor_id):
    """Create a large purchase order to ensure inventory availability"""
    print("Creating huge purchase order...")

    # Create vendor if doesn't exist
    conn.execute("""
        INSERT OR IGNORE INTO vendors (name, contact_info, address)
        VALUES (?, ?, ?)
    """, ("Inventory Supplier", "+1-800-SUPPLIER", "Supplier Street, Supply City"))

    # Get vendor_id (re-get after possible insert)
    cur = conn.execute("SELECT vendor_id FROM vendors WHERE name = 'Inventory Supplier'")
    vendor_id = cur.fetchone()[0]

    # Create a huge purchase order with a unique ID
    cur = conn.execute("SELECT MAX(purchase_id) FROM purchases WHERE purchase_id LIKE 'HPO-%'")
    max_id = cur.fetchone()[0]
    if max_id:
        # Extract the number part and increment
        max_num = int(max_id.split('-')[1])
        purchase_id = f"HPO-{max_num + 1:06d}"
    else:
        purchase_id = "HPO-000001"  # Huge Purchase Order
    purchase_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Create purchase header with very high total
    total_amount = 0
    purchase_items = []

    # Create purchase items with high quantities to ensure inventory availability
    for i, (product_id, product_name) in enumerate(product_info):
        # Find the base UOM for this product
        cur = conn.execute("""
            SELECT uom_id
            FROM product_uoms
            WHERE product_id = ? AND is_base = 1
        """, (product_id,))
        result = cur.fetchone()
        if result:
            uom_id = result[0]
        else:
            # If no base UOM found, set the first UOM as base (should not happen in our setup)
            cur = conn.execute("SELECT uom_id FROM uoms WHERE unit_name = 'Each' LIMIT 1")
            uom_id = cur.fetchone()[0]
            # Add this UOM mapping with is_base=1
            conn.execute(
                "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1.0)",
                (product_id, uom_id)
            )

        # High quantity to ensure we can sell a lot
        quantity = 10000  # 10,000 units of each product
        purchase_price = 200.0  # Higher price to support high sales values
        sale_price = 250.0  # Higher sale price
        item_discount = 0.0

        item_total = quantity * (purchase_price - item_discount)
        total_amount += item_total

        purchase_items.append(
            (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount)
        )

    # Insert purchase header
    conn.execute("""
        INSERT INTO purchases
        (purchase_id, vendor_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, notes, created_by)
        VALUES (?, ?, ?, ?, ?, 'unpaid', 0, 0, ?, (SELECT user_id FROM users WHERE username = 'admin' LIMIT 1))
    """, (purchase_id, vendor_id, purchase_date, total_amount, 0, "Huge inventory purchase for high-value sales"))

    # Insert purchase items
    conn.executemany("""
        INSERT INTO purchase_items
        (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, purchase_items)

    # Create inventory transactions for the purchase
    # Need to get the auto-generated item IDs after insertion
    for i, (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount) in enumerate(purchase_items):
        # Get the item_id of the purchase item
        cur = conn.execute("""
            SELECT item_id FROM purchase_items
            WHERE purchase_id = ? AND product_id = ? AND uom_id = ?
            ORDER BY item_id DESC LIMIT 1
        """, (purchase_id, product_id, uom_id))
        item_id = cur.fetchone()[0]

        conn.execute("""
            INSERT INTO inventory_transactions
            (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id,
             date, posted_at, txn_seq, notes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, quantity, uom_id, 'purchase', 'purchases', purchase_id,
              item_id, purchase_date, datetime.now().isoformat(), 0,
              f"Inventory for huge purchase {purchase_id}",
              1))  # created_by

    conn.commit()
    print(f"Created huge purchase order with total amount: {total_amount}")

    return purchase_id

def create_high_value_sales(conn, customer_ids, product_info, num_sales=1000):
    """Create high-value sales orders (each over 100,000)"""
    print(f"Creating {num_sales} high-value sales orders...")

    # Get admin user ID - make sure it exists
    cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
    result = cur.fetchone()
    if not result:
        # Create admin user if not exists
        conn.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role, is_active)
            VALUES ('admin', 'admin_hash', 'Admin User', 'admin@testcompany.com', 'admin', 1)
        """)
        conn.commit()
        cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
        user_id = cur.fetchone()[0]
    else:
        user_id = result[0]

    # Debug: Check if user exists
    print(f"Using user_id: {user_id}")
    
    sales = []
    sale_items = []
    
    base_time = datetime.now().strftime('%Y%m%d%H%M%S')  # Include time for more uniqueness
    for i in range(num_sales):
        # Generate a unique sale ID to avoid conflicts
        unique_sale_id = f"HSO-{base_time}-{i+1:06d}"  # High-value Sales Order with precise time

        # Select a random customer
        customer_id = random.choice(customer_ids)

        # Set date (within last 180 days)
        sale_date = (datetime.now() - timedelta(days=random.randint(0, 180))).strftime("%Y-%m-%d")

        # Calculate items to reach over 100,000
        target_amount = random.uniform(100000, 200000)  # Between 100K and 200K
        current_amount = 0
        items_for_this_sale = []

        # Add items until we reach the target amount
        while current_amount < target_amount:
            product_id, product_name = random.choice(product_info)

            # Get the UOM for this product (use base UOM)
            cur = conn.execute("""
                SELECT uom_id
                FROM product_uoms
                WHERE product_id = ? AND is_base = 1
            """, (product_id,))
            result = cur.fetchone()
            if result:
                uom_id = result[0]
            else:
                # If no base UOM found, use 'Each' UOM and make sure it's mapped to the product
                cur = conn.execute("SELECT uom_id FROM uoms WHERE unit_name = 'Each' LIMIT 1")
                base_uom_id = cur.fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1.0)",
                    (product_id, base_uom_id)
                )
                uom_id = base_uom_id

            unit_price = random.uniform(200, 500)  # High unit prices
            quantity = int((target_amount - current_amount) / unit_price) + random.randint(1, 5)

            # Apply discount if needed to reach closer to target
            item_discount = random.uniform(0, 10) if random.random() > 0.7 else 0.0
            item_total = quantity * (unit_price - item_discount)

            if current_amount + item_total > target_amount * 1.1:  # Don't exceed by too much
                quantity = int((target_amount - current_amount) / unit_price)
                if quantity <= 0:
                    break
                item_total = quantity * (unit_price - item_discount)

            items_for_this_sale.append((unique_sale_id, product_id, quantity, uom_id, unit_price, item_discount))
            current_amount += item_total

        # Add order discount if amount is too high
        order_discount = 0
        if current_amount > target_amount:
            order_discount = current_amount - target_amount

        total_amount = current_amount - order_discount

        # Only add sale if it meets the minimum requirement
        if total_amount >= 100000:
            # Add the sale to the list to be inserted later
            sales.append((unique_sale_id, customer_id, sale_date, total_amount, order_discount, 'unpaid', 0, 0, f"High-value sale #{i+1}", user_id))

            # Add items for this sale to the main list (they already have the correct sale_id)
            for item in items_for_this_sale:
                sale_items.append(item)

            # Create inventory transactions for this sale - we'll do this after the items are inserted
    
    # Insert all sales first
    conn.executemany("""
        INSERT INTO sales
        (sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sales)

    # Commit to ensure sales exist before creating sale_items
    conn.commit()

    # Insert all sale items
    conn.executemany("""
        INSERT INTO sale_items
        (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
        VALUES (?, ?, ?, ?, ?, ?)
    """, sale_items)

    # Create inventory transactions for the sales
    # Since sales were inserted earlier, we can collect sale IDs for return
    sale_ids = [item[0] for item in sales]  # Extract sale IDs from the sales list

    for sale_id in sale_ids:
        # Get the sale date for this sale
        sale_date = conn.execute("SELECT date FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()[0]

        # Get the sale items for this sale to create inventory transactions
        cur = conn.execute("""
            SELECT item_id, product_id, quantity, uom_id
            FROM sale_items
            WHERE sale_id = ?
        """, (sale_id,))

        for item_row in cur.fetchall():
            item_id, product_id, quantity, uom_id = item_row
            conn.execute("""
                INSERT INTO inventory_transactions
                (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id,
                 date, posted_at, txn_seq, notes, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_id, quantity, uom_id, 'sale', 'sales', sale_id,
                  item_id, sale_date, datetime.now().isoformat(), 0,
                  f"Sale transaction for {sale_id}", user_id))

    conn.commit()

    print(f"Created {len(sales)} high-value sales with amounts ranging from 100,000+")
    return sale_ids  # Return sale IDs

def create_payment_history(conn, sale_ids):
    """Create complete payment history with initial and later payments"""
    print("Creating payment history with initial and later payments...")
    
    # Get bank account ID
    cur = conn.execute("SELECT account_id FROM company_bank_accounts LIMIT 1")
    bank_account_id = cur.fetchone()[0]
    
    # Get admin user ID
    cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
    user_id = cur.fetchone()[0]
    
    all_payments = []
    
    for i, sale_id in enumerate(sale_ids):
        # Get sale total
        cur = conn.execute("SELECT total_amount FROM sales WHERE sale_id = ?", (sale_id,))
        total_amount = cur.fetchone()[0]
        
        # Decide on payment strategy (partial now, rest later OR full now)
        full_now = random.random() > 0.3  # 70% chance of full payment now
        
        if full_now:
            # Full payment now
            payment_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")
            payment_amount = total_amount
            all_payments.append((
                sale_id, payment_date, payment_amount, 'Bank Transfer', bank_account_id, 'online', 
                f"BK{random.randint(100000, 999999)}", None, None, None, 'cleared', None, None, user_id
            ))
        else:
            # Partial payment now + full payment later
            # First payment (immediate)
            first_payment_amount = total_amount * random.uniform(0.3, 0.6)  # 30-60% now
            first_payment_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")
            all_payments.append((
                sale_id, first_payment_date, first_payment_amount, 'Bank Transfer', bank_account_id, 'online', 
                f"BK{random.randint(100000, 999999)}", None, None, None, 'cleared', None, None, user_id
            ))
            
            # Second payment (later)
            second_payment_amount = total_amount - first_payment_amount
            second_payment_date = (datetime.now() - timedelta(days=random.randint(31, 90))).strftime("%Y-%m-%d")
            all_payments.append((
                sale_id, second_payment_date, second_payment_amount, 'Bank Transfer', bank_account_id, 'online', 
                f"BK{random.randint(100000, 999999)}", None, None, None, 'cleared', None, None, user_id
            ))
    
    # Insert all payments
    conn.executemany("""
        INSERT INTO sale_payments 
        (sale_id, date, amount, method, bank_account_id, instrument_type, instrument_no, 
         instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, all_payments)
    
    conn.commit()
    print(f"Created {len(all_payments)} payment records for {len(sale_ids)} sales")

def create_customer_advances(conn, customer_ids):
    """Create customer advances for testing advance functionality"""
    print("Creating customer advances...")

    # Get admin user ID
    cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
    user_id = cur.fetchone()[0]

    advances = []

    # Create advances for ~50% of customers
    selected_customers = random.sample(customer_ids, int(len(customer_ids) * 0.5))

    for customer_id in selected_customers:
        # Create 1-3 advance deposits per selected customer
        num_advances = random.randint(1, 3)

        for _ in range(num_advances):
            # Create a deposit advance
            advance_date = (datetime.now() - timedelta(days=random.randint(1, 180))).strftime("%Y-%m-%d")
            advance_amount = random.uniform(5000, 50000)  # Significant advances for testing
            source_type = random.choice(['deposit', 'return_credit'])

            advances.append((
                customer_id, advance_date, advance_amount, source_type, None,
                f"Advance deposit for testing", user_id
            ))

    # Insert advances
    conn.executemany("""
        INSERT INTO customer_advances
        (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, advances)

    conn.commit()
    print(f"Created {len(advances)} customer advance records")

    return [adv[0] for adv in advances]  # Return customer IDs that have advances


def apply_customer_advances_to_sales(conn, sale_ids):
    """Apply some customer advances to sales for testing"""
    print("Applying customer advances to sales...")

    # Get admin user ID
    cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
    user_id = cur.fetchone()[0]

    applications = []

    # Apply advances to ~20% of sales
    selected_sales = random.sample(sale_ids, int(len(sale_ids) * 0.2))

    for sale_id in selected_sales:
        # Get the sale total and customer
        cur = conn.execute("""
            SELECT s.total_amount, s.customer_id, s.paid_amount, s.advance_payment_applied
            FROM sales s WHERE s.sale_id = ?
        """, (sale_id,))
        result = cur.fetchone()
        if not result:
            continue

        total_amount, customer_id, paid_amount, advance_applied = result
        total_applied = paid_amount + (advance_applied or 0)
        remaining = total_amount - total_applied

        if remaining > 0:
            # Check if the customer has advances available
            cur.execute("""
                SELECT SUM(CAST(amount AS REAL)) as total_advances
                FROM customer_advances
                WHERE customer_id = ? AND (
                    source_type = 'deposit' OR source_type = 'return_credit'
                ) AND tx_id NOT IN (
                    SELECT CAST(SUBSTR(notes, 21) AS INTEGER)
                    FROM customer_advances
                    WHERE source_type = 'applied_to_sale' AND source_id = ?
                )
            """, (customer_id, sale_id))

            advance_balance_row = cur.fetchone()
            if advance_balance_row and advance_balance_row[0]:
                available_advances = float(advance_balance_row[0])
            else:
                available_advances = 0.0

            # Apply up to the remaining amount or available advances
            application_amount = -min(remaining, available_advances, remaining * random.uniform(0.1, 1.0))

            if application_amount < 0:  # Only apply if there's a positive amount to apply
                # Get an advance transaction ID to reference (simplified approach)
                # Create an application advance record
                application_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")

                applications.append((
                    customer_id, application_date, application_amount, 'applied_to_sale',
                    sale_id, f"Applied to sale {sale_id}", user_id
                ))

    # Insert applications
    if applications:
        conn.executemany("""
            INSERT INTO customer_advances
            (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, applications)

        # Update the sales table to reflect applied advances
        for customer_id, app_date, app_amount, src_type, sale_id, notes, usr_id in applications:
            # Update the sale's advance_payment_applied field
            current_applied = conn.execute(
                "SELECT COALESCE(advance_payment_applied, 0) FROM sales WHERE sale_id = ?", (sale_id,)
            ).fetchone()[0]

            new_applied = current_applied + abs(app_amount)  # app_amount is negative for applications
            conn.execute(
                "UPDATE sales SET advance_payment_applied = ? WHERE sale_id = ?",
                (new_applied, sale_id)
            )

    conn.commit()
    print(f"Created {len(applications)} advance applications to sales")


def create_double_permutation_payments(conn, sale_ids):
    """Create double permutation of payments for testing functionality"""
    print("Creating double permutation of payments...")

    # Get bank account ID
    cur = conn.execute("SELECT account_id FROM company_bank_accounts LIMIT 1")
    bank_account_id = cur.fetchone()[0]

    # Get admin user ID
    cur = conn.execute("SELECT user_id FROM users WHERE username = 'admin' LIMIT 1")
    user_id = cur.fetchone()[0]

    # For testing functionality, create additional payments on some sales
    # to simulate complex payment scenarios
    additional_payments = []

    # Select ~30% of sales to add additional payments to
    selected_sales = random.sample(sale_ids, int(len(sale_ids) * 0.3))

    for sale_id in selected_sales:
        # Add 1-3 additional payments per selected sale
        num_additional_payments = random.randint(1, 3)

        for _ in range(num_additional_payments):
            # Get remaining amount to be paid
            cur = conn.execute("""
                SELECT total_amount,
                       COALESCE((SELECT SUM(amount) FROM sale_payments WHERE sale_id = ?), 0) as paid_amount
                FROM sales WHERE sale_id = ?
            """, (sale_id, sale_id))
            total_amount, paid_amount = cur.fetchone()
            remaining = total_amount - paid_amount

            if remaining > 0:
                # Create a payment for the remaining amount or a portion of it
                payment_amount = min(remaining, remaining * random.uniform(0.1, 1.0))
                payment_date = (datetime.now() - timedelta(days=random.randint(1, 150))).strftime("%Y-%m-%d")

                # Random payment method
                methods = ['Bank Transfer', 'Cheque', 'Cash', 'Card', 'Cash Deposit']
                method = random.choice(methods)

                # Set appropriate instrument type based on method
                if method == 'Bank Transfer':
                    instrument_type = 'online'
                elif method == 'Cheque':
                    instrument_type = 'cross_cheque'
                elif method == 'Cash Deposit':
                    instrument_type = 'cash_deposit'
                else:
                    instrument_type = 'other'

                additional_payments.append((
                    sale_id, payment_date, payment_amount, method, bank_account_id, instrument_type,
                    f"EXT{random.randint(100000, 999999)}", None, None, None, 'cleared', None,
                    "Additional payment for testing", user_id
                ))

    # Insert additional payments
    conn.executemany("""
        INSERT INTO sale_payments
        (sale_id, date, amount, method, bank_account_id, instrument_type, instrument_no,
         instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, additional_payments)

    conn.commit()
    print(f"Created {len(additional_payments)} additional permutation payments")

def main():
    """Main function to create high-value sales data"""
    print("Starting high-value sales seeding...")
    
    # Connect to DB
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "myshop.db")
    if not os.path.exists(db_path):
        # Try alternative locations
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "myshop.db")
        if not os.path.exists(db_path):
            print(f"Could not find database at {db_path}. Please specify correct path.")
            return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    set_pragmas(conn)
    
    # Ensure base data exists
    ensure_base_data(conn)
    
    # Create customers
    customer_ids = create_customers(conn, 100)
    
    # Create products and inventory
    product_info = create_products_and_inventory(conn, 50)
    
    # Create vendor and huge purchase order to ensure inventory
    cur = conn.execute("SELECT vendor_id FROM vendors WHERE name = 'Inventory Supplier' LIMIT 1")
    vendor_row = cur.fetchone()

    if vendor_row:
        vendor_id = vendor_row[0]
    else:
        conn.execute("INSERT INTO vendors (name, contact_info, address) VALUES (?, ?, ?)",
                     ("Inventory Supplier", "+1-800-SUPPLIER", "Supplier Street, Supply City"))
        conn.commit()  # Commit the vendor insert
        vendor_id = conn.execute("SELECT vendor_id FROM vendors WHERE name = 'Inventory Supplier' LIMIT 1").fetchone()[0]

    huge_purchase_id = create_huge_purchase_order(conn, product_info, vendor_id)
    
    # Create high-value sales
    sale_ids = create_high_value_sales(conn, customer_ids, product_info, 1000)
    
    # Create payment history
    create_payment_history(conn, sale_ids)
    
    # Create customer advances
    create_customer_advances(conn, customer_ids)

    # Apply customer advances to sales
    apply_customer_advances_to_sales(conn, sale_ids)

    # Create double permutation payments
    create_double_permutation_payments(conn, sale_ids)

    # Update payment status based on payments
    cur = conn.execute("SELECT sale_id FROM sales WHERE doc_type = 'sale'")
    for (sale_id,) in cur.fetchall():
        payment_result = conn.execute("""
            SELECT total_amount,
                   COALESCE((SELECT SUM(amount) FROM sale_payments WHERE sale_id = ?), 0) as paid_amount,
                   COALESCE(advance_payment_applied, 0) as advance_applied
            FROM sales WHERE sale_id = ?
        """, (sale_id, sale_id)).fetchone()

        total_amount, paid_amount, advance_applied = payment_result
        # Calculate effective paid amount (payments + advances)
        effective_paid = paid_amount + advance_applied
        payment_status = 'paid' if effective_paid >= total_amount else 'partial' if effective_paid > 0 else 'unpaid'

        conn.execute("""
            UPDATE sales
            SET paid_amount = ?,
                payment_status = ?
            WHERE sale_id = ?
        """, (paid_amount, payment_status, sale_id))
    
    conn.commit()
    conn.close()
    
    print(f"Completed! Created:")
    print(f"  - 100+ customers")
    print(f"  - {len(product_info)} products with huge inventory")
    print(f"  - 1 huge purchase order ({huge_purchase_id})")
    print(f"  - {len(sale_ids)} high-value sales (100K+ each)")
    print(f"  - Complete payment history with initial and later payments")
    print(f"  - Double permutation of payments for testing")

if __name__ == "__main__":
    main()