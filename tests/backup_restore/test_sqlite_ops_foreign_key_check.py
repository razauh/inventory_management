from __future__ import annotations

import sqlite3

import pytest

from inventory_management.modules.backup_restore import sqlite_ops


def test_foreign_key_check_raises_for_missing_database(tmp_path):
    missing_db = tmp_path / "missing.imsdb"

    with pytest.raises(FileNotFoundError):
        sqlite_ops.foreign_key_check(str(missing_db))


def test_verify_database_reports_foreign_key_check_failure(monkeypatch, tmp_path):
    db_path = tmp_path / "valid.imsdb"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY);")

    def fail_foreign_key_check(_db_path: str):
        raise RuntimeError("simulated FK check failure")

    monkeypatch.setattr(sqlite_ops, "foreign_key_check", fail_foreign_key_check)

    ok, details = sqlite_ops.verify_database(str(db_path), mode="quick", fk_check=True)

    assert ok is False
    assert any("foreign_key_check failed" in detail for detail in details)
    assert any("simulated FK check failure" in detail for detail in details)


def test_foreign_key_check_returns_empty_list_when_no_violations(tmp_path):
    db_path = tmp_path / "clean.imsdb"
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys = ON;")
        con.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY);")
        con.execute(
            "CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));"
        )
        con.execute("INSERT INTO parent(id) VALUES (1);")
        con.execute("INSERT INTO child(id, parent_id) VALUES (1, 1);")

    assert sqlite_ops.foreign_key_check(str(db_path)) == []


def test_verify_database_reports_foreign_key_violations(tmp_path):
    db_path = tmp_path / "orphaned.imsdb"
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys = OFF;")
        con.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY);")
        con.execute(
            "CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));"
        )
        con.execute("INSERT INTO child(id, parent_id) VALUES (1, 42);")

    ok, details = sqlite_ops.verify_database(str(db_path), mode="quick", fk_check=True)

    assert ok is False
    assert any("foreign_key_check violations: 1" in detail for detail in details)
    assert any("table=child" in detail for detail in details)
