import sqlite3
from ..constants import TABLE_SCHEMA_VERSION

def _ensure_table(conn: sqlite3.Connection):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_SCHEMA_VERSION}(
            id INTEGER PRIMARY KEY CHECK (id=1),
            version TEXT NOT NULL
        );
    """)

def get_current_version(conn: sqlite3.Connection) -> str | None:
    _ensure_table(conn)
    row = conn.execute(f"SELECT version FROM {TABLE_SCHEMA_VERSION} WHERE id=1;").fetchone()
    return row["version"] if row else None

def set_current_version(conn: sqlite3.Connection, version: str):
    _ensure_table(conn)
    cur = conn.execute(f"SELECT 1 FROM {TABLE_SCHEMA_VERSION} WHERE id=1;").fetchone()
    if cur:
        conn.execute(f"UPDATE {TABLE_SCHEMA_VERSION} SET version=? WHERE id=1;", (version,))
    else:
        conn.execute(f"INSERT INTO {TABLE_SCHEMA_VERSION}(id, version) VALUES (1, ?);", (version,))
    conn.commit()
