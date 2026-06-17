from __future__ import annotations

import sqlite3
from dataclasses import dataclass


DEFAULT_PRODUCT_LOOKUP_LIMIT = 75


@dataclass(frozen=True)
class ProductLookupItem:
    product_id: int
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} (ID: {self.product_id})"


_search_cache: dict[tuple[int, str, int], list[ProductLookupItem]] = {}
_exact_cache: dict[tuple[int, str], list[int]] = {}


def _conn_key(conn: sqlite3.Connection | object) -> int:
    return id(conn)


def invalidate_product_lookup_cache(conn: sqlite3.Connection | object | None = None) -> None:
    if conn is None:
        _search_cache.clear()
        _exact_cache.clear()
        return

    key = _conn_key(conn)
    for cache in (_search_cache, _exact_cache):
        for cache_key in list(cache):
            if cache_key[0] == key:
                del cache[cache_key]


def search_products(
    conn: sqlite3.Connection | object,
    text: str | None = None,
    *,
    limit: int = DEFAULT_PRODUCT_LOOKUP_LIMIT,
) -> list[ProductLookupItem]:
    term = (text or "").strip().lower()
    capped_limit = max(1, int(limit))
    cache_key = (_conn_key(conn), term, capped_limit)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    params: list[object] = []
    where_sql = ""
    order_sql = "ORDER BY name, product_id"
    if term:
        pattern = f"%{term}%"
        prefix = f"{term}%"
        where_sql = "WHERE LOWER(name) LIKE ? OR CAST(product_id AS TEXT) LIKE ?"
        order_sql = """
            ORDER BY
                CASE
                    WHEN CAST(product_id AS TEXT) = ? THEN 0
                    WHEN LOWER(name) = ? THEN 1
                    WHEN LOWER(name) LIKE ? THEN 2
                    ELSE 3
                END,
                name,
                product_id
        """
        params.extend([pattern, pattern, term, term, prefix])

    rows = conn.execute(
        f"""
        SELECT product_id, name
        FROM products
        {where_sql}
        {order_sql}
        LIMIT ?
        """,
        [*params, capped_limit],
    ).fetchall()

    items = [
        ProductLookupItem(
            product_id=int(row["product_id"] if hasattr(row, "keys") else row[0]),
            name=str(row["name"] if hasattr(row, "keys") else row[1]),
        )
        for row in rows
    ]
    _search_cache[cache_key] = items
    return items


def product_ids_by_exact_name(conn: sqlite3.Connection | object, name: str) -> list[int]:
    term = (name or "").strip().lower()
    if not term:
        return []

    cache_key = (_conn_key(conn), term)
    cached = _exact_cache.get(cache_key)
    if cached is not None:
        return cached

    rows = conn.execute(
        """
        SELECT product_id
        FROM products
        WHERE LOWER(name) = ?
        ORDER BY product_id
        LIMIT 2
        """,
        (term,),
    ).fetchall()
    ids = [int(row["product_id"] if hasattr(row, "keys") else row[0]) for row in rows]
    _exact_cache[cache_key] = ids
    return ids
