import sqlite3
import sys
from types import SimpleNamespace

import pytest

from inventory_management.database.schema import SQL
from inventory_management.scripts import bulk_import_vendors as importer


class FakeFrame:
    def __init__(self, rows):
        self.columns = list(importer.REQUIRED_HEADERS)
        self._rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self._rows)


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.commit()
    return conn


def install_fake_pandas(monkeypatch, rows):
    calls = []

    def read_excel(path, **kwargs):
        calls.append((path, kwargs))
        return FakeFrame(rows)

    monkeypatch.setitem(sys.modules, "pandas", SimpleNamespace(read_excel=read_excel))
    return calls


def test_import_vendors_from_xlsx_merges_bank_and_account_name(monkeypatch, tmp_path):
    conn = make_db()
    xlsx_path = tmp_path / "vendors.xlsx"
    xlsx_path.write_bytes(b"placeholder")
    rows = [
        {
            "Name": "Vendor Bulk",
            "Phone": "0300-1111111",
            "Address": "Main Road",
            "Bank1_Name": "HBL",
            "Account1_Name": "abc",
            "Account1_Number": "123",
            "Bank2_Name": "UBL",
            "Account2_Name": "xyz",
            "Account2_Number": "456",
        }
    ]
    calls = install_fake_pandas(monkeypatch, rows)

    result = importer.import_vendors_from_xlsx(conn, xlsx_path)

    assert result.imported_count == 1
    assert result.failed_count == 0
    assert calls[0][1]["engine"] == "openpyxl"
    vendor = conn.execute(
        "SELECT vendor_id, name, contact_info, address FROM vendors WHERE name = ?",
        ("Vendor Bulk",),
    ).fetchone()
    assert dict(vendor) == {
        "vendor_id": vendor["vendor_id"],
        "name": "Vendor Bulk",
        "contact_info": "0300-1111111",
        "address": "Main Road",
    }
    accounts = conn.execute(
        """
        SELECT label, bank_name, account_no, is_primary, is_active
        FROM vendor_bank_accounts
        WHERE vendor_id = ?
        ORDER BY vendor_bank_account_id
        """,
        (vendor["vendor_id"],),
    ).fetchall()
    assert [dict(row) for row in accounts] == [
        {
            "label": "HBL-abc",
            "bank_name": "HBL-abc",
            "account_no": "123",
            "is_primary": 1,
            "is_active": 1,
        },
        {
            "label": "UBL-xyz",
            "bank_name": "UBL-xyz",
            "account_no": "456",
            "is_primary": 0,
            "is_active": 1,
        },
    ]
    conn.close()


def test_import_vendors_from_xlsx_rejects_existing_vendor_without_partial_import(monkeypatch, tmp_path):
    conn = make_db()
    conn.execute(
        "INSERT INTO vendors (name, contact_info, address) VALUES (?, ?, NULL)",
        ("Existing Vendor", "111"),
    )
    conn.commit()
    xlsx_path = tmp_path / "vendors.xlsx"
    xlsx_path.write_bytes(b"placeholder")
    rows = [
        {
            "Name": "New Vendor",
            "Phone": "222",
            "Address": "",
            "Bank1_Name": "HBL",
            "Account1_Name": "abc",
            "Account1_Number": "123",
            "Bank2_Name": "",
            "Account2_Name": "",
            "Account2_Number": "",
        },
        {
            "Name": "Existing Vendor",
            "Phone": "333",
            "Address": "",
            "Bank1_Name": "",
            "Account1_Name": "",
            "Account1_Number": "",
            "Bank2_Name": "",
            "Account2_Name": "",
            "Account2_Number": "",
        },
    ]
    install_fake_pandas(monkeypatch, rows)

    with pytest.raises(importer.ImportValidationError) as excinfo:
        importer.import_vendors_from_xlsx(conn, xlsx_path)

    assert excinfo.value.failed_count == 1
    assert "duplicate vendors" in str(excinfo.value)
    names = [
        row["name"]
        for row in conn.execute("SELECT name FROM vendors ORDER BY vendor_id").fetchall()
    ]
    assert names == ["Existing Vendor"]
    assert conn.execute("SELECT COUNT(*) AS c FROM vendor_bank_accounts").fetchone()["c"] == 0
    conn.close()
