from dataclasses import dataclass
from typing import Optional
import sqlite3

@dataclass
class Product:
    product_id: int | None
    name: str
    description: str | None
    category: str | None
    min_stock_level: float

class ProductsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_roles_table()  # NEW
        
    def _ensure_roles_table(self):
        # Separates which UoMs can be used for Sales vs Purchases per product
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS product_uom_roles (
            product_id INTEGER NOT NULL,
            uom_id INTEGER NOT NULL,
            for_sales INTEGER NOT NULL DEFAULT 0 CHECK(for_sales IN (0,1)),
            for_purchases INTEGER NOT NULL DEFAULT 0 CHECK(for_purchases IN (0,1)),
            PRIMARY KEY (product_id, uom_id),
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE,
            FOREIGN KEY(uom_id) REFERENCES uoms(uom_id)
        );
        """)
        
    # ---------------- Products ----------------
    def list_products(self) -> list[Product]:
        rows = self.conn.execute(
            "SELECT product_id, name, description, category, min_stock_level FROM products ORDER BY product_id DESC"
        ).fetchall()
        return [Product(**r) for r in rows]
        
    def get(self, product_id: int) -> Product | None:
        r = self.conn.execute(
            "SELECT product_id, name, description, category, min_stock_level FROM products WHERE product_id=?",
            (product_id,)
        ).fetchone()
        return Product(**r) if r else None
        
    def create(self, name: str, description: str | None, category: str | None, min_stock_level: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO products(name, description, category, min_stock_level) VALUES (?, ?, ?, ?)",
            (name, description, category, min_stock_level)
        )
        self.conn.commit()
        return int(cur.lastrowid)
        
    def update(self, product_id: int, name: str, description: str | None, category: str | None, min_stock_level: float):
        self.conn.execute(
            "UPDATE products SET name=?, description=?, category=?, min_stock_level=? WHERE product_id=?",
            (name, description, category, min_stock_level, product_id)
        )
        self.conn.commit()
        
    def delete(self, product_id: int):
        self.conn.execute("DELETE FROM products WHERE product_id=?", (product_id,))
        self.conn.commit()
        
    # ---------------- UOMs & product_uoms ----------------
    def list_uoms(self) -> list[dict]:
        return self.conn.execute("SELECT uom_id, unit_name FROM uoms ORDER BY unit_name").fetchall()
        
    def add_uom(self, unit_name: str) -> int:
        cur = self.conn.execute("INSERT OR IGNORE INTO uoms(unit_name) VALUES (?)", (unit_name,))
        self.conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        return int(self.conn.execute("SELECT uom_id FROM uoms WHERE unit_name=?", (unit_name,)).fetchone()["uom_id"])
        
    def product_uoms(self, product_id: int) -> list[dict]:
        return self.conn.execute("""
            SELECT pu.product_uom_id, pu.product_id, u.uom_id, u.unit_name,
                   pu.is_base, CAST(pu.factor_to_base AS REAL) AS factor_to_base
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id=?
            ORDER BY pu.is_base DESC, u.unit_name
        """, (product_id,)).fetchall()

    def list_product_uoms(self, product_id: int) -> list[dict]:
        """Expose all UoMs for a product with factors (base-first)."""
        return self.conn.execute("""
            SELECT pu.product_id, pu.uom_id, pu.is_base,
                   CAST(pu.factor_to_base AS REAL) AS factor_to_base,
                   u.unit_name
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id = ?
            ORDER BY pu.is_base DESC, u.unit_name
        """, (product_id,)).fetchall()
        
    def get_base_uom(self, product_id: int) -> dict | None:
        return self.conn.execute("""
            SELECT u.uom_id, u.unit_name
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id=? AND pu.is_base=1
            LIMIT 1
        """, (product_id,)).fetchone()
        
    def set_base_uom(self, product_id: int, uom_id: int):
        self.conn.execute("UPDATE product_uoms SET is_base=0 WHERE product_id=?", (product_id,))
        self.conn.execute("""
            INSERT INTO product_uoms(product_id,uom_id,is_base,factor_to_base)
            VALUES (?, ?, 1, 1)
            ON CONFLICT(product_id,uom_id) DO UPDATE SET is_base=1, factor_to_base=1
        """, (product_id, uom_id))
        self.conn.commit()
        
    def add_alt_uom(self, product_id: int, uom_id: int, factor_to_base: float):
        self.conn.execute("""
            INSERT INTO product_uoms(product_id,uom_id,is_base,factor_to_base)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(product_id,uom_id) DO UPDATE SET is_base=excluded.is_base, factor_to_base=excluded.factor_to_base
        """, (product_id, uom_id, factor_to_base))
        self.conn.commit()
        
    def remove_alt_uom(self, product_uom_id: int):
        self.conn.execute("DELETE FROM product_uoms WHERE product_uom_id=?", (product_uom_id,))
        self.conn.commit()
        
    def uom_by_id(self, uom_id: int) -> dict | None:
        return self.conn.execute("SELECT uom_id, unit_name FROM uoms WHERE uom_id=?", (uom_id,)).fetchone()
        
    # ---------------- Roles per flow (Sales vs Purchases) ----------------
    def roles_map(self, product_id: int) -> dict[int, dict]:
        rows = self.conn.execute("""
            SELECT uom_id, for_sales, for_purchases
            FROM product_uom_roles WHERE product_id=?
        """, (product_id,)).fetchall()
        out = {r["uom_id"]: {"for_sales": int(r["for_sales"]), "for_purchases": int(r["for_purchases"])} for r in rows}
        return out
        
    def upsert_roles(self, product_id: int, roles: dict[int, tuple[bool, bool]]):
        for uom_id, (fs, fp) in roles.items():
            self.conn.execute("""
                INSERT INTO product_uom_roles(product_id, uom_id, for_sales, for_purchases)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(product_id,uom_id)
                DO UPDATE SET for_sales=excluded.for_sales, for_purchases=excluded.for_purchases
            """, (product_id, uom_id, 1 if fs else 0, 1 if fp else 0))
        self.conn.commit()

    # ---------------- Latest prices & stock in BASE UoM ----------------
    def latest_prices_base(self, product_id: int) -> dict:
        """
        Returns per-unit prices in BASE UoM: {"cost": purchase_price, "sale": sale_price, "date": <str|None>}
        taken from the most recent purchase item for this product. If none, zeros.
        """
        row = self.conn.execute("""
            SELECT pi.purchase_price, pi.sale_price, pi.uom_id, p.date
            FROM purchase_items pi
            JOIN purchases p ON p.purchase_id = pi.purchase_id
            WHERE pi.product_id = ?
            ORDER BY DATE(p.date) DESC, pi.item_id DESC
            LIMIT 1
        """, (product_id,)).fetchone()
        if not row:
            return {"cost": 0.0, "sale": 0.0, "date": None}
        frow = self.conn.execute(
            "SELECT CAST(factor_to_base AS REAL) AS f FROM product_uoms WHERE product_id=? AND uom_id=?",
            (product_id, row["uom_id"])
        ).fetchone()
        f = float(frow["f"]) if frow else 1.0
        return {
            "cost": float(row["purchase_price"]) / f,
            "sale": float(row["sale_price"]) / f,
            "date": row["date"],
        }

    def on_hand_base(self, product_id: int) -> float:
        r = self.conn.execute(
            "SELECT CAST(qty_in_base AS REAL) AS q FROM v_stock_on_hand WHERE product_id=?",
            (product_id,)
        ).fetchone()
        return float(r["q"]) if r else 0.0
