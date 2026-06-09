import sqlite3

import pytest

from inventory_management.database.repositories.vendors_repo import DomainError, VendorsRepo
from inventory_management.database.schema import SQL


def make_vendor_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


def test_create_rejects_blank_name_and_contact():
    conn = make_vendor_db()
    repo = VendorsRepo(conn)

    with pytest.raises(DomainError, match="Name cannot be empty"):
        repo.create("   ", "Contact", None)

    with pytest.raises(DomainError, match="Contact cannot be empty"):
        repo.create("Vendor", "   ", None)

    conn.close()


def test_create_trims_vendor_fields():
    conn = make_vendor_db()
    repo = VendorsRepo(conn)

    vendor_id = repo.create("  Vendor A  ", "  Contact A  ", "  Address A  ")
    row = conn.execute(
        "SELECT name, contact_info, address FROM vendors WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()

    assert dict(row) == {
        "name": "Vendor A",
        "contact_info": "Contact A",
        "address": "Address A",
    }
    conn.close()


def test_update_rejects_blank_name_and_contact():
    conn = make_vendor_db()
    repo = VendorsRepo(conn)
    vendor_id = repo.create("Vendor A", "Contact A", None)

    with pytest.raises(DomainError, match="Name cannot be empty"):
        repo.update(vendor_id, "   ", "Contact A", None)

    with pytest.raises(DomainError, match="Contact cannot be empty"):
        repo.update(vendor_id, "Vendor A", "   ", None)

    conn.close()


def test_schema_rejects_duplicate_trimmed_vendor_name():
    conn = make_vendor_db()

    conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Vendor A", "Contact A"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
            ("  Vendor A  ", "Contact B"),
        )

    conn.close()


def test_schema_rejects_update_to_duplicate_trimmed_vendor_name():
    conn = make_vendor_db()
    first_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Vendor A", "Contact A"),
    ).lastrowid
    second_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Vendor B", "Contact B"),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE vendors SET name = ? WHERE vendor_id = ?",
            ("  Vendor A  ", second_id),
        )

    assert conn.execute(
        "SELECT name FROM vendors WHERE vendor_id = ?",
        (first_id,),
    ).fetchone()["name"] == "Vendor A"
    conn.close()


def test_schema_rejects_blank_vendor_name_and_contact():
    conn = make_vendor_db()

    with pytest.raises(sqlite3.IntegrityError, match="Vendor name and contact cannot be empty"):
        conn.execute(
            "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
            ("   ", "Contact A"),
        )

    with pytest.raises(sqlite3.IntegrityError, match="Vendor name and contact cannot be empty"):
        conn.execute(
            "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
            ("Vendor A", "   "),
        )

    conn.close()
