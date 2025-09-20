# inventory_management/database/repositories/products_repo.py
from dataclasses import dataclass
from typing import Optional, Dict, List
import sqlite3
from contextlib import contextmanager


class DomainError(Exception):
    """Domain-level error the controller/UI can surface (toast/snackbar)."""
    pass


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
        # Use Row for named access; we normalize to dicts where we claim to return dicts.
        self.conn.row_factory = sqlite3.Row

    # ---------------------------- TX helper ----------------------------

    @contextmanager
    def _immediate_tx(self):
        """
        Start an IMMEDIATE transaction (write lock once first write happens),
        commit on success, rollback on error.
        """
        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    # ---------------------------- Products ----------------------------

    def list_products(self) -> list[Product]:
        rows = self.conn.execute(
            "SELECT product_id, name, description, category, min_stock_level "
            "FROM products "
            "ORDER BY product_id DESC"
        ).fetchall()
        return [Product(**r) for r in rows]

    def get(self, product_id: int) -> Product | None:
        r = self.conn.execute(
            "SELECT product_id, name, description, category, min_stock_level "
            "FROM products WHERE product_id=?",
            (product_id,),
        ).fetchone()
        return Product(**r) if r else None

    def create(
        self,
        name: str,
        description: str | None,
        category: str | None,
        min_stock_level: float,
    ) -> int:
        with self._immediate_tx():
            cur = self.conn.execute(
                "INSERT INTO products(name, description, category, min_stock_level) "
                "VALUES (?, ?, ?, ?)",
                (name, description, category, min_stock_level),
            )
            return int(cur.lastrowid)

    def update(
        self,
        product_id: int,
        name: str,
        description: str | None,
        category: str | None,
        min_stock_level: float,
    ) -> None:
        with self._immediate_tx():
            self.conn.execute(
                "UPDATE products "
                "SET name=?, description=?, category=?, min_stock_level=? "
                "WHERE product_id=?",
                (name, description, category, min_stock_level, product_id),
            )

    def _product_is_referenced(self, product_id: int) -> bool:
        """
        Check common referencing tables that do NOT have ON DELETE CASCADE.
        If any reference exists, deletion would either fail or orphan business data.
        """
        checks = [
            ("SELECT 1 FROM product_uoms          WHERE product_id=? LIMIT 1",),
            ("SELECT 1 FROM purchase_items        WHERE product_id=? LIMIT 1",),
            ("SELECT 1 FROM sale_items            WHERE product_id=? LIMIT 1",),
            ("SELECT 1 FROM inventory_transactions WHERE product_id=? LIMIT 1",),
        ]
        for (sql,) in checks:
            if self.conn.execute(sql, (product_id,)).fetchone():
                return True
        return False

    def deactivate(self, product_id: int) -> None:
        """
        Soft-delete if the schema has products.is_active. If the column is not present,
        raise a clear DomainError so the caller can advise to run migrations.
        """
        # Detect column presence once per call (cheap, pragma is fast for SQLite)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(products)").fetchall()}
        if "is_active" not in cols:
            raise DomainError(
                "Soft delete not available: products.is_active is missing in schema. "
                "Add the column or use safe hard delete on unused products."
            )
        with self._immediate_tx():
            self.conn.execute("UPDATE products SET is_active=0 WHERE product_id=?", (product_id,))

    def delete(self, product_id: int) -> None:
        """
        Safer delete: disallow if referenced anywhere important to avoid orphans.
        Prefer using deactivate() if your schema includes products.is_active.
        """
        if self._product_is_referenced(product_id):
            raise DomainError(
                "Cannot delete product: it is referenced by transactions or mappings. "
                "Consider archiving (soft delete) instead."
            )
        with self._immediate_tx():
            self.conn.execute("DELETE FROM products WHERE product_id=?", (product_id,))

    # ---------------------------- UOMs & product_uoms ----------------------------

    def list_uoms(self) -> List[Dict]:
        cur = self.conn.execute(
            "SELECT uom_id, unit_name FROM uoms ORDER BY unit_name"
        )
        return [dict(r) for r in cur.fetchall()]

    def add_uom(self, unit_name: str) -> int:
        """
        Concurrency-safe attach-or-return existing UoM by name.
        - Attempts INSERT (unique on unit_name recommended).
        - Uses SELECT changes() to see if a row was inserted.
        - If not inserted (already existed), fetch its id.
        """
        with self._immediate_tx():
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO uoms(unit_name) VALUES (?)", (unit_name,)
            )
            # Detect whether this INSERT actually inserted a new row.
            changed = int(self.conn.execute("SELECT changes()").fetchone()[0] or 0)
            if changed > 0:
                # We did insert; return the id we just created (do not trust lastrowid after IGNORE unless changed > 0).
                # cur.lastrowid is valid for the statement that changed rows.
                return int(cur.lastrowid)
            # Already existed — fetch id deterministically within the same tx.
            row = self.conn.execute(
                "SELECT uom_id FROM uoms WHERE unit_name=?",
                (unit_name,),
            ).fetchone()
            if not row:
                # Extremely unlikely due to the tx + unique constraint, but guard anyway.
                raise DomainError("Failed to resolve UoM ID for existing unit.")
            return int(row["uom_id"])

    def product_uoms(self, product_id: int) -> List[Dict]:
        cur = self.conn.execute(
            """
            SELECT
              pu.product_uom_id, pu.product_id, u.uom_id, u.unit_name,
              pu.is_base, CAST(pu.factor_to_base AS REAL) AS factor_to_base
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id=?
            ORDER BY pu.is_base DESC, u.unit_name
            """,
            (product_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_product_uoms(self, product_id: int) -> List[Dict]:
        """Expose all UoMs for a product with factors (base-first)."""
        cur = self.conn.execute(
            """
            SELECT
              pu.product_id, pu.uom_id, pu.is_base,
              CAST(pu.factor_to_base AS REAL) AS factor_to_base,
              u.unit_name
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id = ?
            ORDER BY pu.is_base DESC, u.unit_name
            """,
            (product_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_base_uom(self, product_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            """
            SELECT u.uom_id, u.unit_name
            FROM product_uoms pu
            JOIN uoms u ON u.uom_id = pu.uom_id
            WHERE pu.product_id=? AND pu.is_base=1
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_base_uom(self, product_id: int, uom_id: int) -> None:
        with self._immediate_tx():
            self.conn.execute("UPDATE product_uoms SET is_base=0 WHERE product_id=?", (product_id,))
            self.conn.execute(
                """
                INSERT INTO product_uoms(product_id,uom_id,is_base,factor_to_base)
                VALUES (?, ?, 1, 1)
                ON CONFLICT(product_id,uom_id)
                DO UPDATE SET is_base=1, factor_to_base=1
                """,
                (product_id, uom_id),
            )

    def add_alt_uom(self, product_id: int, uom_id: int, factor_to_base: float) -> None:
        with self._immediate_tx():
            self.conn.execute(
                """
                INSERT INTO product_uoms(product_id,uom_id,is_base,factor_to_base)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(product_id,uom_id)
                DO UPDATE SET is_base=excluded.is_base,
                              factor_to_base=excluded.factor_to_base
                """,
                (product_id, uom_id, factor_to_base),
            )

    def remove_alt_uom(self, product_uom_id: int) -> None:
        with self._immediate_tx():
            self.conn.execute("DELETE FROM product_uoms WHERE product_uom_id=?", (product_uom_id,))

    def uom_by_id(self, uom_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT uom_id, unit_name FROM uoms WHERE uom_id=?", (uom_id,)
        ).fetchone()
        return dict(row) if row else None

    # ---------------- Latest prices & stock in BASE UoM ----------------

    def latest_prices_base(self, product_id: int) -> dict:
        """
        Returns per-unit prices in BASE UoM: {"cost": purchase_price, "sale": sale_price, "date": <str|None>}
        taken from the most recent purchase item for this product. If none, zeros.
        Assumes purchases.date is stored as ISO 'YYYY-MM-DD'.
        """
        row = self.conn.execute(
            """
            SELECT pi.purchase_price, pi.sale_price, pi.uom_id, p.date
            FROM purchase_items pi
            JOIN purchases p ON p.purchase_id = pi.purchase_id
            WHERE pi.product_id = ?
            ORDER BY p.date DESC, pi.item_id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        if not row:
            return {"cost": 0.0, "sale": 0.0, "date": None}

        frow = self.conn.execute(
            "SELECT CAST(factor_to_base AS REAL) AS f "
            "FROM product_uoms WHERE product_id=? AND uom_id=?",
            (product_id, row["uom_id"]),
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
            (product_id,),
        ).fetchone()
        return float(r["q"]) if r else 0.0
