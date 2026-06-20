import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from inventory_management.database.schema import SQL
from inventory_management.database.repositories.company_info_repo import (
    CompanyInfoRepo,
    get_invoice_company_context,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SQL)
    return conn


def test_company_info_context_uses_saved_profile_and_primary_bank_first():
    conn = _conn()
    repo = CompanyInfoRepo(conn)
    repo.save(
        {
            "company_name": "Acme Traders",
            "address_line1": "Line 1",
            "city": "Lahore",
            "phone": "123",
            "invoice_footer_note": "Thanks",
        }
    )
    repo.save_bank_account({"label": "Secondary", "bank_name": "Bank B"})
    repo.save_bank_account({"label": "Primary", "bank_name": "Bank A", "is_primary": 1})

    company = repo.invoice_context()

    assert company["name"] == "Acme Traders"
    assert company["address_lines"] == ["Line 1", "Lahore"]
    assert company["contact_lines"] == ["Phone: 123"]
    assert company["invoice_footer_note"] == "Thanks"
    assert [row["label"] for row in company["bank_accounts"]] == ["Primary", "Secondary"]


def test_company_info_fallback_is_centralized():
    company = get_invoice_company_context(_conn())

    assert company["name"] == "Your Company Name"
    assert company["bank_accounts"] == []


def test_invoice_templates_have_no_placeholder_company_blocks():
    root = Path(__file__).resolve().parents[1]
    for name in ["sale_invoice.html", "quotation_invoice.html", "purchase_invoice.html"]:
        text = (root / "resources" / "templates" / "invoices" / name).read_text(encoding="utf-8")
        assert "Address: XXXX" not in text
        assert "XXXXX" not in text
        assert "Account No: XXXX" not in text
