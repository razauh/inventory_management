# database/__init__.py
from __future__ import annotations

from pathlib import Path
import sqlite3

from config import DB_PATH
from constants import TABLE_SCHEMA_VERSION, SCHEMA_VERSION
from . import schema as schema_module
from .seeders.default_data import seed as seed_default_data


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_SCHEMA_VERSION}(
            id INTEGER PRIMARY KEY CHECK (id=1),
            version TEXT NOT NULL
        );
    """)
    row = conn.execute(
        f"SELECT version FROM {TABLE_SCHEMA_VERSION} WHERE id=1;"
    ).fetchone()
    if row is None:
        conn.execute(
            f"INSERT INTO {TABLE_SCHEMA_VERSION}(id, version) VALUES (1, ?);",
            (SCHEMA_VERSION,),
        )


def get_connection() -> sqlite3.Connection:
    """
    Returns a sqlite3.Connection with:
      - WAL mode
      - foreign_keys ON
      - row_factory = sqlite3.Row (so rows behave like dicts and tuples)
    Ensures schema & seed data are applied idempotently.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Always apply the schema (idempotent: uses CREATE IF NOT EXISTS / DROP TRIGGER IF EXISTS)
    schema_module.init_schema(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    _ensure_version_table(conn)

    # Seeders should be safe to run repeatedly (idempotent).
    seed_default_data(conn)

    conn.commit()
    return conn


__all__ = [
    "get_connection",
]
