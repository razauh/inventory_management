# inventory_management/modules/payments/customer_payments/sale_payments_model.py
"""
Façade for turning UI dicts into kwargs for SalePaymentsRepo.record_payment(...).
Keep this dumb/pass-through — validations/defaults remain in the repo & DB triggers.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

# ───────────────────────────────────────────────────────────────────────────────
# 1) UI alias map → canonical repo field names
#    (only keys listed here will be recognized; everything else is ignored)
# ───────────────────────────────────────────────────────────────────────────────

ALIASES: Dict[str, str] = {
    # identity
    "sale_id": "sale_id",
    "amount": "amount",
    "method": "method",
    "date": "date",
    "bank_account_id": "bank_account_id",
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
    "sale": "sale_id",
    "sale_no": "sale_id",
    "payment_method": "method",
    "posting_date": "date",
    "bank": "bank_account_id",
    "bank_id": "bank_account_id",
    "txn_no": "instrument_no",
    "transaction_no": "instrument_no",
    "receipt_no": "ref_no",
}

# The repo’s canonical method strings (title-cased)
_METHOD_SET = {
    "Cash",
    "Bank Transfer",
    "Card",
    "Cheque",
    "Cash Deposit",
    "Other",
}

# Optional: fast map for common user-entered variants → canonical
_METHOD_CANON_MAP = {
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


def _canon_method(m: Optional[str]) -> Optional[str]:
    """
    Return the repo’s canonical method string, or None if empty.
    Leave unknown values as title-cased (repo will validate/raise).
    """
    if m is None:
        return None
    s = str(m).strip()
    if not s:
        return None
    k = s.lower()
    if k in _METHOD_CANON_MAP:
        return _METHOD_CANON_MAP[k]
    # fallback: title-case, but do not enforce membership here (repo owns that)
    t = s.title()
    return t if t in _METHOD_SET else t


# ───────────────────────────────────────────────────────────────────────────────
# 3) normalize_ui_payload(data)  → kwargs for SalePaymentsRepo.record_payment(...)
#    - map aliases
#    - coerce simple types
#    - omit missing optionals (repo will apply defaults where appropriate)
# ───────────────────────────────────────────────────────────────────────────────

def normalize_ui_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn a raw UI dict into the exact kwargs that SalePaymentsRepo.record_payment expects.
    Pure function — no DB calls. Leaves business validation to the repo.
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

    # 2) required basics
    # sale_id
    if "sale_id" in tmp:
        v = tmp["sale_id"]
        out["sale_id"] = str(v).strip() if v is not None else v

    # amount
    if "amount" in tmp and tmp["amount"] is not None:
        out["amount"] = float(tmp["amount"])

    # method (canonicalize casing/variants; repo will validate the final value)
    if "method" in tmp:
        out["method"] = _canon_method(tmp["method"])

    # date (posting date, 'YYYY-MM-DD' — do not reformat)
    if "date" in tmp:
        v = tmp["date"]
        out["date"] = str(v).strip() if v is not None else None

    # 3) bank / instrument fields (only pass if provided; repo may default)
    if "bank_account_id" in tmp:
        v = tmp["bank_account_id"]
        out["bank_account_id"] = None if v in ("", None) else int(v)

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

    # 4) misc
    if "ref_no" in tmp:
        v = tmp["ref_no"]
        out["ref_no"] = None if v in ("", None) else str(v).strip()

    if "notes" in tmp:
        v = tmp["notes"]
        out["notes"] = None if v in ("", None) else str(v).strip()

    if "created_by" in tmp:
        v = tmp["created_by"]
        out["created_by"] = None if v in ("", None) else int(v)

    # Do NOT add defaults here (e.g., instrument_type, clearing_state) — let repo decide.
    # Do NOT validate method/bank/amount combos — repo owns validation and error text.

    return out


# ───────────────────────────────────────────────────────────────────────────────
# 4) record_from_ui(db_path, data) → int payment_id
#    - lazy-import the repo inside the function to avoid circular imports
# ───────────────────────────────────────────────────────────────────────────────

def record_from_ui(db_path: str, data: Dict[str, Any]) -> int:
    """
    Convenience: normalize UI dict, then insert via SalePaymentsRepo and return payment_id.
    Surfaces repository exceptions as-is (so callers show consistent error messages).
    """
    # NOTE: If the actual repo path differs in your project, adjust this import.
    from inventory_management.database.repositories.sales.sale_payments_repo import (  # type: ignore
        SalePaymentsRepo,
    )

    kwargs = normalize_ui_payload(data)
    repo = SalePaymentsRepo(db_path)
    payment_id = repo.record_payment(**kwargs)
    return int(payment_id)
