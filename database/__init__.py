from pathlib import Path
import sqlite3

from ..config import DB_PATH
from ..constants import TABLE_SCHEMA_VERSION, SCHEMA_VERSION
from . import schema as schema_module
from .seeders.default_data import seed as seed_default_data

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def _ensure_version_table(conn: sqlite3.Connection):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_SCHEMA_VERSION}(
            id INTEGER PRIMARY KEY CHECK (id=1),
            version TEXT NOT NULL
        );
    """)
    row = conn.execute(f"SELECT version FROM {TABLE_SCHEMA_VERSION} WHERE id=1;").fetchone()
    if row is None:
        conn.execute(f"INSERT INTO {TABLE_SCHEMA_VERSION}(id, version) VALUES (1, ?);", (SCHEMA_VERSION,))

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_needed = not Path(DB_PATH).exists()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    # Always ensure schema is applied (idempotent CREATE IF NOT EXISTS)
    if init_needed:
        schema_module.init_schema(DB_PATH)
    _ensure_version_table(conn)
    seed_default_data(conn)
    conn.commit()
    return conn
