#!/usr/bin/env python3
"""
Bulk seeding script to generate 500 sales orders with at least 50 products each
and permutations of all payment methods.
"""

import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

def seed_bulk_sales(db_path: str = "data/myshop.db"):
    """
    Create 500 sales orders with at least 50 products each and permutations of payment methods.
    """
    # Resolve database path relative to project root
    script_dir = Path(__file__).parent  # This is database/seeders/
    project_root = script_dir.parent.parent  # This is the project root
    db_file = project_root / db_path  # This should be project_root/data/myshop.db

    if not db_file.exists():
        print(f"Database file not found: {db_file}")
        return

    print("Connecting to database...")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        print("Starting creation of bulk sales orders...")
        
        # Ensure there are enough products in the database
        product_count = cur.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if product_count < 100:  # Need at least 100 products to make 500 SOs with 50+ products each
            print(f"Warning: Only {product_count} products found. There might not be enough for 500 SOs with 50+ products each.")
        
        # Get all products
        all_products = cur.execute("SELECT product_id, name FROM products").fetchall()
        if len(all_products) == 0:
            print("No products found in database. Please seed products first.")
            return

        print(f"Found {len(all_products)} products to use in sales orders.")

        # Get or create some customers
        customer_rows = cur.execute("SELECT customer_id FROM customers").fetchall()
        
        if len(customer_rows) == 0:
            print("No customers found, creating 50 default customers...")
            for i in range(50):
                cur.execute(
                    "INSERT INTO customers (name, contact_info, address, is_active) VALUES (?, ?, ?, 1)",
                    (f"Customer {i+1:03d}", f"customer{i+1:03d}@mail.test | +92-30{i%10}-{2000000+i:07d}", f"{i+1} Customer Avenue, City")
                )
            conn.commit()
            customer_rows = cur.execute("SELECT customer_id FROM customers").fetchall()
        
        print(f"Using {len(customer_rows)} customers for sales orders.")

        # Get or create users
        user_rows = cur.execute("SELECT user_id FROM users").fetchall()
        if len(user_rows) == 0:
            print("No users found, creating a default user...")
            from utils.auth import hash_password
            cur.execute(
                "INSERT INTO users (username, password_hash, full_name, email, role, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                ("admin", hash_password("admin"), "Administrator", "admin@example.com", "admin")
            )
            conn.commit()
            user_id = cur.lastrowid
        else:
            user_id = user_rows[0]["user_id"]
        
        print(f"Using user_id: {user_id} for sales orders.")

        # Get base UOMs for products
        print("Fetching base UOMs for products...")
        product_uoms = {}
        for product_row in all_products:
            product_id = product_row["product_id"]
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
                    print(f"Warning: No UOM found for product {product_id}.")
        
        # Payment methods - according to CHECK constraint: 'Cash','Bank Transfer','Card','Cheque','Cash Deposit','Other'
        payment_methods = ["Cash", "Bank Transfer", "Card", "Cheque", "Cash Deposit", "Other"]
        print(f"Using payment methods: {payment_methods}")

        # Create 500 sales orders
        print("Creating 500 sales orders with at least 50 products each...")
        
        start_number = 10  # Start from SO20251128-0010
        base_date = datetime.now().date()  # Use today's date
        base_date_str = base_date.strftime("%Y%m%d")
        
        total_amount_for_all_sales = 0.0
        total_products_in_all_sales = 0
        
        for i in range(500):
            # Generate SO ID in format SO20251128-xxx starting from 010
            so_number = f"{start_number + i:04d}"
            so_id = f"SO{base_date_str}-{so_number}"
            
            # Select a random customer
            customer_id = random.choice(customer_rows)["customer_id"]
            
            # Use today's date for all SOs
            so_date = base_date.strftime("%Y-%m-%d")
            
            # Select random products for this SO (at least 50)
            num_products = random.randint(50, min(100, len(all_products)))  # Between 50-100 products or all products if fewer
            selected_products = random.sample(all_products, num_products)
            
            # Select payment method
            payment_method = random.choice(payment_methods)
            
            # Determine payment status (paid, partial, unpaid)
            payment_status_options = ["paid", "partial", "unpaid"]
            payment_status = random.choice(payment_status_options)
            
            # For partial payments, only pay a percentage initially
            total_amount = 0.0
            sales_items = []
            
            for j, product_row in enumerate(selected_products):
                product_id = product_row["product_id"]
                
                # Generate random quantity and price
                quantity = random.randint(1, 10)  # Random quantity between 1-10
                unit_price = round(random.uniform(5.0, 500.0), 2)  # Random price between 5-500
                item_discount = round(random.uniform(0.0, 50.0), 2) if random.random() > 0.7 else 0.0  # 30% chance of discount
                
                item_total = quantity * (unit_price - item_discount)
                total_amount += item_total
                
                # Add to sales items
                sales_items.append({
                    "product_id": product_id,
                    "uom_id": product_uoms.get(product_id, 1),  # Use 1 as default if not found
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "item_discount": item_discount
                })
            
            # Calculate initial payment amount based on payment status
            if payment_status == "paid":
                initial_payment = total_amount
            elif payment_status == "partial":
                # Pay 30-80% of the total amount
                initial_payment = total_amount * random.uniform(0.3, 0.8)
            else:  # unpaid
                initial_payment = 0.0
            
            # Create the sales header
            cur.execute("""
                INSERT INTO sales
                (sale_id, customer_id, date, total_amount, order_discount, payment_status, 
                 paid_amount, advance_payment_applied, notes, created_by, doc_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sale')
            """, (
                so_id,
                customer_id,
                so_date,
                total_amount,
                0,  # order_discount
                "unpaid",  # Initially unpaid, will be updated by triggers when payments are recorded
                0,  # paid_amount initially 0, will be updated by triggers
                0,  # advance_payment_applied
                f"Bulk seeded sales order #{i+1}",
                user_id
            ))
            
            # Create the sales items
            for item in sales_items:
                cur.execute("""
                    INSERT INTO sale_items
                    (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    so_id,
                    item["product_id"],
                    item["quantity"],
                    item["uom_id"],
                    item["unit_price"],
                    item["item_discount"]
                ))
            
            # Create inventory transactions for the sale
            for j, item in enumerate(sales_items):
                # Get the item_id of the sale item
                item_row = cur.execute("""
                    SELECT item_id FROM sale_items
                    WHERE sale_id = ? AND product_id = ? AND uom_id = ?
                    ORDER BY item_id DESC LIMIT 1
                """, (so_id, item["product_id"], item["uom_id"])).fetchone()
                
                if item_row:
                    item_id = item_row["item_id"]
                    
                    cur.execute("""
                        INSERT INTO inventory_transactions
                        (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id,
                         date, posted_at, txn_seq, notes, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item["product_id"],
                        item["quantity"],
                        item["uom_id"],
                        'sale',
                        'sales',
                        so_id,
                        item_id,
                        so_date,
                        datetime.now().isoformat(),
                        j,  # txn_seq
                        f"Sale transaction for {so_id}",
                        user_id
                    ))
            
            # Record initial payment if applicable
            if initial_payment > 0:
                # Determine bank account for certain payment methods
                bank_account_id = None
                instrument_no = None
                instrument_type = "other"
                
                if payment_method in ["Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit"]:
                    # Get a bank account
                    bank_row = cur.execute("SELECT account_id FROM company_bank_accounts LIMIT 1").fetchone()
                    if bank_row:
                        bank_account_id = bank_row["account_id"]
                        instrument_no = f"INST{random.randint(100000, 999999)}"
                        
                        if payment_method == "Bank Transfer":
                            instrument_type = "online"
                        elif payment_method in ["Cheque", "Cross Cheque"]:
                            instrument_type = "cross_cheque"
                        elif payment_method == "Cash Deposit":
                            instrument_type = "cash_deposit"
                
                # Record the payment
                cur.execute("""
                    INSERT INTO sale_payments
                    (sale_id, date, amount, method, bank_account_id, instrument_type,
                     instrument_no, clearing_state, notes, created_by, overpayment_converted, converted_to_credit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'cleared', ?, ?, 0, 0)
                """, (
                    so_id,
                    so_date,
                    initial_payment,
                    payment_method,
                    bank_account_id,
                    instrument_type,
                    instrument_no,
                    f"Initial payment for SO {so_id}",
                    user_id
                ))
            
            total_amount_for_all_sales += total_amount
            total_products_in_all_sales += len(sales_items)
            
            if (i + 1) % 50 == 0:
                print(f"Created {i+1}/500 sales orders...")
                conn.commit()  # Commit periodically to avoid memory issues
        
        # Final commit
        conn.commit()
        
        print(f"\nSuccessfully created 500 sales orders with:")
        print(f"- At least 50 products per order (total: {total_products_in_all_sales} products across all SOs)")
        print(f"- Permutations of payment methods: {payment_methods}")
        print(f"- Total value of all sales: {total_amount_for_all_sales}")
        print("The sales orders should now be visible in your application!")

    except Exception as e:
        print(f"Error creating bulk sales orders: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    seed_bulk_sales()