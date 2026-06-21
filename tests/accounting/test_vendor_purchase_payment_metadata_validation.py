import sqlite3

import pytest

from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService, VendorPaymentMetadata


def _metadata_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.execute("INSERT INTO company_info (company_id, company_name) VALUES (1, 'Company')")
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    other_vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Other Vendor', 'Contact')"
    ).lastrowid
    active_company_bank_id = conn.execute(
        "INSERT INTO company_bank_accounts (label, is_active) VALUES ('Active Bank', 1)"
    ).lastrowid
    inactive_company_bank_id = conn.execute(
        "INSERT INTO company_bank_accounts (label, is_active) VALUES ('Inactive Bank', 0)"
    ).lastrowid
    active_vendor_bank_id = conn.execute(
        "INSERT INTO vendor_bank_accounts (vendor_id, label, is_active) VALUES (?, 'Vendor Bank', 1)",
        (vendor_id,),
    ).lastrowid
    inactive_vendor_bank_id = conn.execute(
        "INSERT INTO vendor_bank_accounts (vendor_id, label, is_active) VALUES (?, 'Inactive Vendor Bank', 0)",
        (vendor_id,),
    ).lastrowid
    other_vendor_bank_id = conn.execute(
        "INSERT INTO vendor_bank_accounts (vendor_id, label, is_active) VALUES (?, 'Other Vendor Bank', 1)",
        (other_vendor_id,),
    ).lastrowid
    return {
        "conn": conn,
        "vendor_id": int(vendor_id),
        "active_company_bank_id": int(active_company_bank_id),
        "inactive_company_bank_id": int(inactive_company_bank_id),
        "active_vendor_bank_id": int(active_vendor_bank_id),
        "inactive_vendor_bank_id": int(inactive_vendor_bank_id),
        "other_vendor_bank_id": int(other_vendor_bank_id),
    }


def test_vendor_payment_metadata_preserves_current_method_rules():
    db = _metadata_db()
    service = AccountingService(db["conn"])

    service.validate_vendor_payment_metadata(
        VendorPaymentMetadata(vendor_id=db["vendor_id"], method="Cash")
    )
    service.validate_vendor_payment_metadata(
        VendorPaymentMetadata(
            vendor_id=db["vendor_id"],
            method="Bank Transfer",
            bank_account_id=db["active_company_bank_id"],
            vendor_bank_account_id=db["active_vendor_bank_id"],
            instrument_type="online",
            instrument_no="TXN-1",
            clearing_state="cleared",
            require_method_details=True,
        )
    )
    with pytest.raises(ValueError, match="Vendor purchase payments must have clearing_state='cleared'"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Cash",
                clearing_state="pending",
            )
        )
    with pytest.raises(ValueError, match="Invalid vendor advance payment method: Card"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Card",
                vendor_label="advance",
                reject_card=True,
            )
        )
    with pytest.raises(ValueError, match="Bank Transfer requires company account"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Bank Transfer",
                instrument_type="online",
                instrument_no="TXN-1",
                vendor_bank_account_id=db["active_vendor_bank_id"],
                clearing_state="cleared",
                require_method_details=True,
            )
        )
    db["conn"].close()


def test_vendor_payment_metadata_rejects_inactive_accounts():
    db = _metadata_db()
    service = AccountingService(db["conn"])

    with pytest.raises(ValueError, match="company bank account is inactive"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Bank Transfer",
                bank_account_id=db["inactive_company_bank_id"],
                vendor_bank_account_id=db["active_vendor_bank_id"],
                instrument_type="online",
                instrument_no="TXN-1",
                clearing_state="cleared",
            )
        )
    with pytest.raises(ValueError, match="vendor bank account is inactive"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Bank Transfer",
                bank_account_id=db["active_company_bank_id"],
                vendor_bank_account_id=db["inactive_vendor_bank_id"],
                instrument_type="online",
                instrument_no="TXN-1",
                clearing_state="cleared",
            )
        )
    with pytest.raises(ValueError, match="Vendor bank account does not belong to the purchase vendor"):
        service.validate_vendor_payment_metadata(
            VendorPaymentMetadata(
                vendor_id=db["vendor_id"],
                method="Bank Transfer",
                bank_account_id=db["active_company_bank_id"],
                vendor_bank_account_id=db["other_vendor_bank_id"],
                instrument_type="online",
                instrument_no="TXN-1",
                clearing_state="cleared",
                vendor_label="purchase",
            )
        )
    db["conn"].close()
