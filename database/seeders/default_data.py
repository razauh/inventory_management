from ...utils.auth import hash_password

def seed(conn):
    # if no users exist, create admin/admin and a demo cashier
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    if row and row["n"] == 0:
        conn.execute("""
            INSERT INTO users(username, password_hash, full_name, email, role, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, ("admin", hash_password("admin"), "Administrator", "admin@example.com", "admin"))
        conn.execute("""
            INSERT INTO users(username, password_hash, full_name, email, role, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, ("cashier", hash_password("cashier"), "Cashier User", "cashier@example.com", "user"))
        conn.commit()
