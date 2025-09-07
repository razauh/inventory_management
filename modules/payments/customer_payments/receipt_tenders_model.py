from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Optional, List, Dict, Iterable, Tuple, Any

# ---- Constants mirrored from SalePaymentsRepo (keep in sync) ----
METHODS = {
    "Cash",
    "Bank Transfer",
    "Card",
    "Cheque",
    "Cash Deposit",
    "Other",
}

ITYPES = {"online", "cross_cheque", "cash_deposit", "pay_order", "other"}

DEFAULT_ITYPE_BY_METHOD: Dict[str, str] = {
    "Cash": "other",
    "Bank Transfer": "online",
    "Cheque": "cross_cheque",
    "Cash Deposit": "cash_deposit",
    "Card": "other",
    "Other": "other",
}

DEFAULT_CLEARING_BY_METHOD: Dict[str, str] = {
    "Cash": "posted",
    "Bank Transfer": "posted",
    "Card": "posted",
    "Other": "posted",
    "Cheque": "pending",
    "Cash Deposit": "pending",
}

CLEARING_STATES = {"posted", "pending", "cleared", "bounced"}


@dataclass
class ReceiptHeader:
    sale_id: str
    date: Optional[str] = None            # 'YYYY-MM-DD' (None => DB default)
    ref_no: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None


@dataclass
class Tender:
    method: str
    amount: float
    bank_account_id: Optional[int] = None
    instrument_type: Optional[str] = None
    instrument_no: Optional[str] = None
    instrument_date: Optional[str] = None
    deposited_date: Optional[str] = None
    cleared_date: Optional[str] = None
    clearing_state: Optional[str] = None   # 'posted'|'pending'|'cleared'|'bounced' or None


class ReceiptTendersModel:
    def __init__(self, header: ReceiptHeader) -> None:
        self._header: ReceiptHeader = header
        self._tenders: List[Tender] = []

    # ---- mutate ----
    def add_tender(self, t: Tender) -> None:
        self._tenders.append(t)

    def remove_index(self, idx: int) -> None:
        if 0 <= idx < len(self._tenders):
            self._tenders.pop(idx)

    def clear(self) -> None:
        self._tenders.clear()

    def set_header(self, header: ReceiptHeader) -> None:
        self._header = header

    def clone_row(self, idx: int) -> None:
        if 0 <= idx < len(self._tenders):
            self._tenders.insert(idx + 1, replace(self._tenders[idx]))

    # Convenience: fill defaults on a row (returns same instance for chaining)
    def ensure_defaults_on_row(self, t: Tender) -> Tender:
        if not t.instrument_type:
            t.instrument_type = DEFAULT_ITYPE_BY_METHOD.get(t.method, t.instrument_type)
        if not t.clearing_state:
            t.clearing_state = DEFAULT_CLEARING_BY_METHOD.get(t.method, t.clearing_state)
        return t

    def spread_amount_evenly(self, total: float, methods_order: List[str] | None = None) -> None:
        """Split total equally across existing tenders, optionally setting methods in order.
        Rounds to 0.01; last row gets the remainder to ensure sum equals total.
        """
        n = len(self._tenders)
        if n == 0:
            return
        try:
            total_f = float(total or 0.0)
        except Exception:
            total_f = 0.0
        if methods_order:
            for i, m in enumerate(methods_order[:n]):
                self._tenders[i].method = m
        if total_f == 0.0:
            for t in self._tenders:
                t.amount = 0.0
            return
        base = round(total_f / n, 2)
        assigned = 0.0
        for i in range(n - 1):
            self._tenders[i].amount = base
            assigned += base
        self._tenders[-1].amount = round(total_f - assigned, 2)

    # ---- read ----
    def rows(self) -> List[Tender]:
        return list(self._tenders)

    def totals(self) -> Dict[str, float]:
        receipts = 0.0
        refunds = 0.0
        total = 0.0
        for t in self._tenders:
            try:
                amt = float(t.amount)
            except Exception:
                amt = 0.0
            total += amt
            if amt > 0:
                receipts += amt
            elif amt < 0:
                refunds += -amt
        return {"count": len(self._tenders), "sum": total, "receipts": receipts, "refunds": refunds}

    # ---- validation & output ----
    def validate(self) -> None:
        # 1) Header
        if not isinstance(self._header.sale_id, str) or not self._header.sale_id.strip():
            raise ValueError("sale_id is required.")

        if not self._tenders:
            # Allow empty (controller may treat as no-op), but be explicit
            raise ValueError("At least one tender is required.")

        any_negative = False
        any_positive = False

        for idx, t in enumerate(self._tenders):
            # Method
            if t.method not in METHODS:
                raise ValueError(f"Unsupported payment method: {t.method}")

            # Amount
            if t.amount is None:
                raise ValueError("Amount is required.")
            try:
                amt = float(t.amount)
            except Exception:
                raise ValueError("Amount is required.")

            if amt < 0:
                any_negative = True
            if amt > 0:
                any_positive = True

            # Defaults for instrument_type / clearing_state
            if not t.instrument_type:
                t.instrument_type = DEFAULT_ITYPE_BY_METHOD[t.method]
            if t.instrument_type not in ITYPES:
                allowed = ", ".join(sorted(ITYPES))
                raise ValueError(f"Invalid instrument type '{t.instrument_type}'. Allowed: {allowed}")
            if not t.clearing_state:
                t.clearing_state = DEFAULT_CLEARING_BY_METHOD[t.method]
            if t.clearing_state not in CLEARING_STATES:
                raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")

            # Per-method constraints
            if t.method == "Cash":
                # Cash can be positive or negative; must not reference company bank
                if t.bank_account_id is not None:
                    raise ValueError("Cash must not reference a company bank account.")
                # Instrument type must be 'other' per default; allow if already set to other
                if t.instrument_type != "other":
                    raise ValueError("Cash instrument_type must be 'other'.")
            elif t.method == "Bank Transfer":
                if amt <= 0:
                    raise ValueError("Bank Transfer requires a positive amount.")
                if t.bank_account_id is None:
                    raise ValueError("Bank Transfer requires a company bank account.")
                if not t.instrument_no:
                    raise ValueError("Bank Transfer requires an instrument/reference number.")
                if t.instrument_type != "online":
                    raise ValueError("Instrument type must be 'online' for Bank Transfer.")
            elif t.method == "Cheque":
                if amt <= 0:
                    raise ValueError("Cheque requires a positive amount.")
                if t.bank_account_id is None:
                    raise ValueError("Cheque requires a company bank account.")
                if not t.instrument_no:
                    raise ValueError("Cheque requires an instrument/reference number.")
                if t.instrument_type != "cross_cheque":
                    raise ValueError("Instrument type must be 'cross_cheque' for Cheque.")
            elif t.method == "Cash Deposit":
                if amt <= 0:
                    raise ValueError("Cash Deposit requires a positive amount.")
                if t.bank_account_id is None:
                    raise ValueError("Cash Deposit requires a company bank account.")
                if not t.instrument_no:
                    raise ValueError("Cash Deposit requires an instrument/reference number.")
                if t.instrument_type != "cash_deposit":
                    raise ValueError("Instrument type must be 'cash_deposit' for Cash Deposit.")
            elif t.method in {"Card", "Other"}:
                if amt <= 0:
                    raise ValueError(f"{t.method} requires a positive amount.")
                # bank optional; instrument_no optional; instrument_type should be 'other'
                if t.instrument_type != "other":
                    raise ValueError(f"Instrument type must be 'other' for {t.method}.")

            # Cleared state/date soft consistency (optional nudge; repo will enforce dates if needed)
            if t.clearing_state == "cleared" and not t.cleared_date:
                # Keep message aligned with other UIs for clarity
                raise ValueError("Please provide a cleared_date when clearing_state is 'cleared'.")

        # 3) Mixed-sign rule (UI sanity) — block mixing refund with receipts in a single batch
        if any_negative and any_positive:
            raise ValueError("Do not mix refund (negative) and receipt (positive) tenders in one batch. Record refunds separately.")

    def to_payloads(self) -> List[dict]:
        """Validate and emit payloads ready for SalePaymentsRepo.record_payment(...)."""
        self.validate()
        hdr = self._header
        payloads: List[Dict[str, Any]] = []
        for t in self._tenders:
            payloads.append({
                "sale_id": hdr.sale_id,
                "amount": float(t.amount),
                "method": t.method,
                "date": hdr.date,
                "bank_account_id": t.bank_account_id,
                "instrument_type": t.instrument_type,
                "instrument_no": t.instrument_no,
                "instrument_date": t.instrument_date,
                "deposited_date": t.deposited_date,
                "cleared_date": t.cleared_date,
                "clearing_state": t.clearing_state,
                "ref_no": hdr.ref_no,
                "notes": hdr.notes,
                "created_by": hdr.created_by,
            })
        return payloads
