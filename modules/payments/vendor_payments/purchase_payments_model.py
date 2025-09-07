# inventory_management/modules/payments/vendor_payments/purchase_payments_model.py
"""
Façade for turning UI dicts into kwargs for PurchasePaymentsRepo.record_payment(...).
Pass-through by design. Purchases roll up paid/status **only on CLEARED rows** (DB triggers).
This module does not enforce business rules or defaults—those live in the repo & database.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

# ───────────────────────────────────────────────────────────────────────────────
# 1) UI alias map → canonical repo field names
#    (only keys listed here will be recognized; everything else is ignored)
# ───────────────────────────────────────────────────────────────────────────────
ALIASES: Dict[str, str] = {
    # identity
    "purchase_id": "purchase_id",
    "amount": "amount",
    "method": "method",
    "date": "date",
    "bank_account_id": "bank_account_id",
    "vendor_bank_account_id": "vendor_bank_account_id",
    "instrument_type": "instrument_type",
    "instrument_no": "instrument_no",
    "instrument_date": "instrument_date",
    "deposited_date": "deposited_date",
    "cleared_date": "cleared_date",
    "clearing_state": "clearing_state",
    "ref_no": "ref_no",
    "notes": "notes",
    "created_by": "created_by",

    # common UI synonyms
    "purchase": "purchase_id",
    "po_no": "purchase_id",
    "payment_method": "method",
    "posting_date": "date",
    "company_bank_id": "bank_account_id",
    "vendor_bank_id": "vendor_bank_account_id",
    "txn_no": "instrument_no",
    "transaction_no": "instrument_no",
    "receipt_no": "ref_no",
}

# ───────────────────────────────────────────────────────────────────────────────
# 2) Method canonicalizer (same set as sales side; repo ultimately validates)
# ───────────────────────────────────────────────────────────────────────────────
_METHOD_SET = {"Cash", "Bank Transfer", "Card", "Cheque", "Cash Deposit", "Other"}
_METHOD_CANON_MAP: Dict[str, str] = {
    "cash": "Cash",
    "bank transfer": "Bank Transfer",
    "transfer": "Bank Transfer",
    "bt": "Bank Transfer",
    "card": "Card",
    "debit card": "Card",
    "credit card": "Card",
    "cheque": "Cheque",
    "check": "Cheque",
    "cash deposit": "Cash Deposit",
    "deposit": "Cash Deposit",
    "other": "Other",
}


def _canon_method(s: Optional[str]) -> Optional[str]:
    """
    Return canonical method string or None if empty.
    Unknown values are title-cased and left for the repo to validate.
    """
    if s is None:
        return None
    k = str(s).strip()
    if not k:
        return None
    lk = k.lower()
    mapped = _METHOD_CANON_MAP.get(lk)
    if mapped:
        return mapped
    t = k.title()
    return t if t in _METHOD_SET else t  # repo/DB will validate/raise if not allowed


# ───────────────────────────────────────────────────────────────────────────────
# 3) normalize_ui_payload(data)  → kwargs for PurchasePaymentsRepo.record_payment(...)
#    - map aliases
#    - coerce simple types
#    - omit missing optionals (repo will apply defaults where appropriate)
# ───────────────────────────────────────────────────────────────────────────────
def normalize_ui_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn a raw UI dict into the exact kwargs that PurchasePaymentsRepo.record_payment expects.
    Pure function — no DB calls. Leaves business validation/defaulting to the repo.
    """
    if not isinstance(data, dict):
        raise TypeError("data must be a dict")

    # 1) alias mapping (copy only recognized keys)
    tmp: Dict[str, Any] = {}
    for k, v in data.items():
        canon = ALIASES.get(k)
        if canon:
            tmp[canon] = v

    out: Dict[str, Any] = {}

    # 2) basics
    if "purchase_id" in tmp:
        v = tmp["purchase_id"]
        out["purchase_id"] = None if v is None else str(v).strip()

    if "amount" in tmp and tmp["amount"] is not None:
        out["amount"] = float(tmp["amount"])

    if "method" in tmp:
        out["method"] = _canon_method(tmp["method"])

    if "date" in tmp:
        v = tmp["date"]
        out["date"] = None if v in ("", None) else str(v).strip()

    # 3) bank / party accounts
    if "bank_account_id" in tmp:
        v = tmp["bank_account_id"]
        out["bank_account_id"] = None if v in ("", None) else int(v)

    if "vendor_bank_account_id" in tmp:
        v = tmp["vendor_bank_account_id"]
        out["vendor_bank_account_id"] = None if v in ("", None) else int(v)

    # 4) instrument fields
    if "instrument_type" in tmp:
        v = tmp["instrument_type"]
        out["instrument_type"] = None if v in ("", None) else str(v).strip()

    if "instrument_no" in tmp:
        v = tmp["instrument_no"]
        out["instrument_no"] = None if v in ("", None) else str(v).strip()

    for key in ("instrument_date", "deposited_date", "cleared_date"):
        if key in tmp:
            v = tmp[key]
            out[key] = None if v in ("", None) else str(v).strip()

    if "clearing_state" in tmp:
        v = tmp["clearing_state"]
        out["clearing_state"] = None if v in ("", None) else str(v).strip().lower()

    # 5) misc
    if "ref_no" in tmp:
        v = tmp["ref_no"]
        out["ref_no"] = None if v in ("", None) else str(v).strip()

    if "notes" in tmp:
        v = tmp["notes"]
        out["notes"] = None if v in ("", None) else str(v).strip()

    if "created_by" in tmp:
        v = tmp["created_by"]
        out["created_by"] = None if v in ("", None) else int(v)

    # Do NOT add defaults here — instrument/clearing defaults and validations belong in repo/DB.
    # Purchases header moves only on cleared rows; this façade just forwards the payload.
    return out


# ───────────────────────────────────────────────────────────────────────────────
# 4) record_from_ui(db_path, data) → int payment_id
#    - lazy-import the repo inside the function to avoid circular imports
# ───────────────────────────────────────────────────────────────────────────────
def record_from_ui(db_path: str, data: Dict[str, Any]) -> int:
    """
    Convenience: normalize UI dict, then insert via PurchasePaymentsRepo and return payment_id.
    Surfaces repository exceptions as-is (so callers show the canonical messages).
    """
    # Adjust path if your project locates the repo elsewhere.
    from inventory_management.database.repositories.purchase_payments_repo import (  # type: ignore
        PurchasePaymentsRepo,
    )

    kwargs = normalize_ui_payload(data)
    repo = PurchasePaymentsRepo(db_path)
    payment_id = repo.record_payment(**kwargs)
    return int(payment_id)
