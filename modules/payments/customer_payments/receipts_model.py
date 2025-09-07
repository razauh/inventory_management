from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["ReceiptsModel", "summarize_amounts"]


class ReceiptsModel:
    """
    UI adapter for reading sale payments (customer receipts).
    Wraps SalePaymentsRepo.list_by_sale / list_by_customer and normalizes rows.
    Pure read-only; no DB writes here.
    """

    # ---- Constructor ----
    def __init__(self, repo) -> None:
        """
        repo: an instance with methods:
          - list_by_sale(sale_id) -> list[Mapping]
          - list_by_customer(customer_id) -> list[Mapping]
        """
        self._repo = repo

    # ---- Primary loaders ----
    def for_sale(
        self,
        sale_id: str,
        *,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        raw = self._repo.list_by_sale(sale_id)  # already date-ordered ASC per tests
        rows = [self._norm_row(x) for x in raw]
        rows = self._apply_filters(rows, filters)
        return self._paginate(rows, page, page_size)

    def for_customer(
        self,
        customer_id: int,
        *,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        raw = self._repo.list_by_customer(customer_id)  # sorted ASC per tests
        rows = [self._norm_row(x) for x in raw]
        rows = self._apply_filters(rows, filters)
        return self._paginate(rows, page, page_size)

    # ---- Convenience detail ----
    def get_detail(self, payment_id: int, *, context_rows: Optional[Iterable[dict]] = None) -> Optional[dict]:
        """
        Return a single normalized row by id. If context_rows provided,
        search those first; otherwise, you may fetch via for_customer/for_sale
        before calling this (keeps adapter DB-agnostic).
        """
        if context_rows is not None:
            for r in context_rows:
                try:
                    if int(r.get("payment_id")) == int(payment_id):
                        # Ensure it's normalized to schema
                        return self._norm_row(r)
                except Exception:
                    continue
        return None

    # ---- Internals ----
    _ROW_KEYS = (
        "payment_id",
        "sale_id",
        "date",
        "amount",
        "method",
        "bank_account_id",
        "instrument_type",
        "instrument_no",
        "instrument_date",
        "deposited_date",
        "cleared_date",
        "clearing_state",
        "ref_no",
        "notes",
        "created_by",
    )

    def _norm_row(self, r: dict) -> dict:
        out: Dict[str, Any] = {k: None for k in self._ROW_KEYS}
        # Required ids
        try:
            out["payment_id"] = int(r.get("payment_id"))
        except Exception:
            out["payment_id"] = None
        out["sale_id"] = None if r.get("sale_id") is None else str(r.get("sale_id"))

        # Dates (keep as stored 'YYYY-MM-DD' or None)
        for key in ("date", "instrument_date", "deposited_date", "cleared_date"):
            v = r.get(key)
            out[key] = None if v in ("", None) else str(v)

        # Amount
        try:
            out["amount"] = float(r.get("amount", 0.0) or 0.0)
        except Exception:
            out["amount"] = 0.0

        # Strings / enums
        for key in ("method", "instrument_type", "instrument_no", "clearing_state", "ref_no", "notes"):
            v = r.get(key)
            out[key] = None if v in ("", None) else str(v)

        # Bank account id & created_by
        for key in ("bank_account_id", "created_by"):
            v = r.get(key)
            try:
                out[key] = None if v in ("", None) else int(v)
            except Exception:
                out[key] = None

        return out

    def _apply_filters(self, rows: List[dict], filters: Optional[dict]) -> List[dict]:
        if not filters:
            return rows
        method = filters.get("method")
        clearing_state = filters.get("clearing_state")
        bank_account_id = filters.get("bank_account_id")
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")

        def _as_list(x):
            if x is None:
                return None
            return x if isinstance(x, (list, tuple, set)) else [x]

        mset = _as_list(method)
        cset = _as_list(clearing_state)
        bset = _as_list(bank_account_id)

        out: List[dict] = []
        for r in rows:
            if mset is not None and r.get("method") not in mset:
                continue
            if cset is not None and r.get("clearing_state") not in cset:
                continue
            if bset is not None and r.get("bank_account_id") not in bset:
                continue
            d = r.get("date") or ""
            if date_from and d < str(date_from):
                continue
            if date_to and d > str(date_to):
                continue
            out.append(r)
        return out

    def _paginate(self, rows: List[dict], page: int, page_size: int) -> Dict[str, Any]:
        try:
            page = int(page)
        except Exception:
            page = 1
        try:
            page_size = int(page_size)
        except Exception:
            page_size = 100
        if page < 1:
            page = 1
        if page_size <= 0:
            page_size = 100

        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        sliced = rows[start:end]
        return {"rows": sliced, "total": total, "page": page, "page_size": page_size}


# ---- Optional presentation helper ----

def summarize_amounts(rows: Iterable[dict]) -> Dict[str, float]:
    """
    Return {'receipts': float>=0, 'refunds': float>=0, 'net': float}
    receipts = sum(amount for amount > 0)
    refunds  = sum(-amount for amount < 0)
    net      = sum(amount)
    """
    receipts = 0.0
    refunds = 0.0
    net = 0.0
    for r in rows:
        try:
            amt = float(r.get("amount", 0.0) or 0.0)
        except Exception:
            amt = 0.0
        net += amt
        if amt > 0:
            receipts += amt
        elif amt < 0:
            refunds += -amt
    return {"receipts": receipts, "refunds": refunds, "net": net}
