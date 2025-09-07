# inventory_management/modules/payments/vendor_payments/model.py
"""
VendorPaymentsScreenModel

Aggregator for the Vendor Payments screen:
- Lists and details purchase_payments in chronological order (DATE(date), payment_id).
- Provides actions: record single payment, allocate one payout across many purchases,
  apply vendor credit, update clearing state, delete/edit instruments.
- Mirrors purchase header policy: only CLEARED rows roll up into paid/status.
- Does not implement business rules; delegates to repos and DB triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


# ---------- Row contracts ----------

@dataclass(frozen=True)
class PaymentRow:
    payment_id: int
    purchase_id: str
    date: Optional[str]
    amount: float
    method: str
    bank_account_id: Optional[int]
    vendor_bank_account_id: Optional[int]
    instrument_type: Optional[str]
    instrument_no: Optional[str]
    instrument_date: Optional[str]
    deposited_date: Optional[str]
    cleared_date: Optional[str]
    clearing_state: Optional[str]
    ref_no: Optional[str]
    notes: Optional[str]
    created_by: Optional[int]


@dataclass(frozen=True)
class VendorSnapshot:
    vendor_id: int
    credit_balance: float            # from advances (running sum)
    open_payables_sum: float         # sum(max(0, total - paid_cleared - advance_applied)) at "today"


# ---------- Aggregator ----------

class VendorPaymentsScreenModel:
    def __init__(
        self,
        *,
        db_path: str,
        # factories to avoid hard imports and ease testing
        purchase_payments_repo_factory: Callable[[str], Any],
        vendor_advances_repo_factory: Callable[[str], Any],
        reporting_repo_factory: Callable[[str], Any],
        # optional helpers (you already specced these in earlier files)
        allocations_model_factory: Optional[Callable[..., Any]] = None,
        partial_model_factory: Optional[Callable[..., Any]] = None,  # not used here but kept for parity
        advances_model_factory: Optional[Callable[..., Any]] = None,  # optional
        advance_applications_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._db_path = db_path
        self._pp = purchase_payments_repo_factory(db_path)
        self._adv = vendor_advances_repo_factory(db_path)
        self._rep = reporting_repo_factory(db_path)
        self._alloc_factory = allocations_model_factory
        self._partial_factory = partial_model_factory
        self._adv_model_factory = advances_model_factory
        self._adv_apply_factory = advance_applications_factory

    # ------- Loads & snapshots -------

    def list_payments_for_vendor(
        self,
        vendor_id: int,
        *,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 100
    ) -> dict:
        """List purchase payments for a vendor, normalized, filtered, and paginated."""
        rows_raw: List[Dict[str, Any]] = []
        # Prefer list_by_vendor if present
        if hasattr(self._pp, "list_by_vendor"):
            rows_raw = list(self._pp.list_by_vendor(vendor_id))  # type: ignore[attr-defined]
        else:
            # Fallback: try a generic list for vendor
            if hasattr(self._pp, "list_for_vendor"):
                rows_raw = list(self._pp.list_for_vendor(vendor_id))  # type: ignore[attr-defined]
            else:
                # As a last resort, gather all vendor purchase_ids then list each
                rows_raw = list(getattr(self._pp, "list_by_vendor_id", lambda _vid: [])(vendor_id))  # type: ignore

        rows = [self._norm_row(r) for r in rows_raw]
        rows = self._apply_filters(rows, filters or {})
        return self._paginate(rows, page, page_size)

    def list_payments_for_purchase(
        self,
        purchase_id: str,
        *,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 100
    ) -> dict:
        """List payments for a single purchase, normalized, filtered, and paginated."""
        if hasattr(self._pp, "list_by_purchase"):
            rows_raw = list(self._pp.list_by_purchase(purchase_id))  # type: ignore[attr-defined]
        else:
            rows_raw = []  # repo missing — return empty list (screen remains functional)
        rows = [self._norm_row(r) for r in rows_raw]
        rows = self._apply_filters(rows, filters or {})
        return self._paginate(rows, page, page_size)

    def get_detail(self, payment_id: int, *, context_rows: Optional[Iterable[dict]] = None) -> Optional[PaymentRow]:
        """Return one normalized row by id from context or repo; None if not found."""
        if context_rows:
            for r in context_rows:
                try:
                    if int(r.get("payment_id")) == int(payment_id):
                        return self._norm_row(r)
                except Exception:
                    continue
        # Try repo direct getter if available
        if hasattr(self._pp, "get"):
            try:
                raw = self._pp.get(payment_id)  # type: ignore[attr-defined]
                if raw:
                    return self._norm_row(raw)
            except Exception:
                pass
        return None

    def vendor_snapshot_today(self, vendor_id: int, *, today: Optional[str] = None) -> VendorSnapshot:
        """Return credit balance and open payables as of 'today' (YYYY-MM-DD)."""
        as_of = today or self._today_str()
        credit = float(self._rep.vendor_credit_as_of(vendor_id, as_of))  # running sum up to date
        headers = list(self._rep.vendor_headers_as_of(vendor_id, as_of))
        open_sum = 0.0
        for h in headers:
            total = float(h.get("total_amount", 0.0) or 0.0)
            paid = float(h.get("paid_amount", 0.0) or 0.0)  # cleared-only basis by triggers
            adv_applied = float(h.get("advance_payment_applied", 0.0) or 0.0)
            rem = total - paid - adv_applied
            if rem > 0:
                open_sum += rem
        return VendorSnapshot(vendor_id=vendor_id, credit_balance=credit, open_payables_sum=open_sum)

    # ------- Actions (delegate to repos/helpers) -------

    def record_single_payment(self, payload: dict) -> int:
        """
        Insert one purchase payment using the thin façade that normalizes UI payloads.
        Surfaces repository exceptions unchanged.
        """
        # Lazy import to avoid circular deps
        from inventory_management.modules.payments.vendor_payments.purchase_payments_model import (  # type: ignore
            record_from_ui,
        )
        return int(record_from_ui(self._db_path, payload))

    def allocate_and_record(
        self,
        header: dict,
        purchases: Iterable[dict],
        total_amount: float,
        *,
        strategy: str = "oldest_first",
        user_overrides: Optional[Dict[str, float]] = None
    ) -> List[int]:
        """
        Create an allocation plan (UI-only), then persist one row per purchase.
        Returns list of new payment_ids in the order of inserted rows.
        """
        if not self._alloc_factory:
            raise RuntimeError("allocations_model_factory was not provided.")
        model = self._alloc_factory(header)  # VendorAllocationsModel(header)
        # The allocation model expects candidates with keys: purchase_id, date, remaining_payable
        model.set_candidates(list(purchases))
        env = model.allocate(
            total_amount,
            strategy=strategy,
            user_overrides=user_overrides or None,
        )
        ids: List[int] = []
        for row in env.get("rows", []):
            pid = self._pp.record_payment(**row)
            ids.append(int(pid))
        return ids

    def apply_credit_to_purchase(
        self,
        vendor_id: int,
        purchase_id: str,
        amount: float,
        *,
        date: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None
    ) -> None:
        """
        Apply vendor credit to a purchase (writes a NEGATIVE ledger row in repo).
        """
        if not self._adv_apply_factory:
            raise RuntimeError("advance_applications_factory was not provided.")
        helper = self._adv_apply_factory(
            # factories for helper:
            lambda p: self._adv.__class__,  # not used by helper; keep signature parity if needed
            lambda p: self._rep.__class__,
            lambda p: getattr(self, "_pp").__class__,
            self._db_path,
        )
        # The helper needs real instances; re-instantiate with same db_path:
        helper = self._adv_apply_factory(type(self._adv), type(self._rep), type(self._pp), self._db_path)
        ctx = helper.bootstrap(vendor_id, purchase_id)
        helper.validate_amount(ctx, amount)
        payload = helper.to_repo_payload(ctx, amount)
        # Override optional fields if provided (ctx dataclass is frozen)
        if date is not None:
            payload["date"] = date
        if notes is not None:
            payload["notes"] = notes
        if created_by is not None:
            payload["created_by"] = created_by
        # Perform the write via advances repo
        self._adv.apply_credit_to_purchase(**payload)

    def update_clearing_state(self, payment_id: int, *, clearing_state: str, cleared_date: Optional[str] = None) -> None:
        """
        Update clearing pipeline for a purchase payment. Headers change only when CLEARED.
        """
        if hasattr(self._pp, "update_clearing_state"):
            self._pp.update_clearing_state(payment_id, clearing_state, cleared_date)  # type: ignore[attr-defined]
        else:
            # Fallback to a generic update method
            if hasattr(self._pp, "update"):
                self._pp.update(payment_id, clearing_state=clearing_state, cleared_date=cleared_date)  # type: ignore[attr-defined]
            else:
                raise AttributeError("PurchasePaymentsRepo lacks update_clearing_state/update methods.")

    def delete_payment(self, payment_id: int) -> None:
        """Delete a payment row; triggers will recompute headers accordingly."""
        if hasattr(self._pp, "delete"):
            self._pp.delete(payment_id)  # type: ignore[attr-defined]
        else:
            raise AttributeError("PurchasePaymentsRepo.delete(...) not found.")

    def edit_payment_instrument(self, payment_id: int, fields: dict) -> None:
        """
        Edit instrument/bank/reference fields for a payment.
        Does not allow changing amount/method/purchase_id here.
        """
        editable = {
            "bank_account_id",
            "vendor_bank_account_id",
            "instrument_no",
            "instrument_type",
            "instrument_date",
            "deposited_date",
            "cleared_date",
            "clearing_state",
            "ref_no",
            "notes",
        }
        safe_fields = {k: v for k, v in (fields or {}).items() if k in editable}
        if not safe_fields:
            return
        if hasattr(self._pp, "update"):
            self._pp.update(payment_id, **safe_fields)  # type: ignore[attr-defined]
        else:
            raise AttributeError("PurchasePaymentsRepo.update(...) not found.")

    # ====================== Internal helpers (pure) ======================

    def _norm_row(self, r: Dict[str, Any]) -> PaymentRow:
        """Coerce types and subset to PaymentRow schema."""
        def _i(x) -> Optional[int]:
            try:
                return int(x) if x is not None else None
            except Exception:
                return None

        def _f(x) -> float:
            try:
                return float(x)
            except Exception:
                return 0.0

        def _s(x) -> Optional[str]:
            if x is None:
                return None
            s = str(x).strip()
            return s if s else None

        return PaymentRow(
            payment_id=int(r.get("payment_id")),
            purchase_id=str(r.get("purchase_id", "")),
            date=_s(r.get("date")),
            amount=_f(r.get("amount")),
            method=str(r.get("method", "")),
            bank_account_id=_i(r.get("bank_account_id")),
            vendor_bank_account_id=_i(r.get("vendor_bank_account_id")),
            instrument_type=_s(r.get("instrument_type")),
            instrument_no=_s(r.get("instrument_no")),
            instrument_date=_s(r.get("instrument_date")),
            deposited_date=_s(r.get("deposited_date")),
            cleared_date=_s(r.get("cleared_date")),
            clearing_state=_s(r.get("clearing_state")),
            ref_no=_s(r.get("ref_no")),
            notes=_s(r.get("notes")),
            created_by=_i(r.get("created_by")),
        )

    def _apply_filters(self, rows: List[PaymentRow], filters: Dict[str, Any]) -> List[PaymentRow]:
        """Client-side filters (equality/IN for categorical, range for dates/amount)."""
        if not filters:
            return rows

        def _in(val, crit):
            if crit is None:
                return True
            if isinstance(crit, (list, tuple, set)):
                return val in crit
            return val == crit

        out: List[PaymentRow] = []
        df = filters.get("date_from")
        dt = filters.get("date_to")
        amin = filters.get("amount_min")
        amax = filters.get("amount_max")
        mcrit = filters.get("method")
        scrit = filters.get("clearing_state")
        bcrit = filters.get("bank_account_id")
        vbcrit = filters.get("vendor_bank_account_id")

        for r in rows:
            if not _in(r.method, mcrit):
                continue
            if not _in(r.clearing_state, scrit):
                continue
            if not _in(r.bank_account_id, bcrit):
                continue
            if not _in(r.vendor_bank_account_id, vbcrit):
                continue
            if df and (r.date or "") < df:
                continue
            if dt and (r.date or "") > dt:
                continue
            if amin is not None and r.amount < float(amin):
                continue
            if amax is not None and r.amount > float(amax):
                continue
            out.append(r)
        return out

    def _paginate(self, rows: List[PaymentRow], page: int, page_size: int) -> dict:
        total = len(rows)
        p = max(1, int(page))
        ps = max(1, int(page_size))
        start = (p - 1) * ps
        end = start + ps
        return {
            "rows": rows[start:end],
            "total": total,
            "page": p,
            "page_size": ps,
        }

    def _today_str(self) -> str:
        import datetime as _dt
        return _dt.date.today().isoformat()
