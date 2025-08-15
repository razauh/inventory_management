from __future__ import annotations
import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple, Iterable

from ...database.repositories.purchases_repo import PurchasesRepo
from ...database.repositories.vendors_repo import VendorsRepo, Vendor
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo


def _to_date(s: str) -> date:
    # Accept YYYY-MM-DD; raise if invalid (surface to caller)
    return datetime.strptime(s, "%Y-%m-%d").date()


def _days_outstanding(as_of: date, doc_date_str: str) -> int:
    try:
        d = _to_date(doc_date_str)
    except Exception:
        # If date is malformed, treat as fully outstanding (0 days to avoid negative)
        return 0
    return max(0, (as_of - d).days)


class VendorAgingReports:
    """
    Compute vendor payables aging snapshots and list open invoices.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.purchases = PurchasesRepo(conn)
        self.vendors = VendorsRepo(conn)
        self.vadv = VendorAdvancesRepo(conn)

    # -------------------------------
    # Aging Snapshot (per vendor)
    # -------------------------------
    def compute_aging_snapshot(
        self,
        as_of: str,
        buckets: Tuple[Tuple[int, int], ...] = ((0, 30), (31, 60), (61, 90), (91, 10_000)),
        include_credit_column: bool = True,
    ) -> list[dict]:
        """
        For each vendor:
          - Pull purchases up to `as_of` with remaining_due > 0
          - Bucket remaining_due by age (days between as_of and purchase.date)
          - Sum per bucket and compute total_due
          - Optionally fetch available vendor credit (does not offset invoices unless applied)

        Returns:
            [
              {
                "vendor_id": int,
                "vendor_name": str,
                "buckets": {"0-30": float, "31-60": float, ...},
                "total_due": float,
                "available_credit": float,     # included if include_credit_column is True
              },
              ...
            ]
        Sorted by total_due DESC.
        """
        cutoff = _to_date(as_of)

        # Pre-format bucket labels & helper
        bucket_labels = [f"{lo}-{hi}" for (lo, hi) in buckets]

        def pick_bucket(days: int) -> str:
            for (lo, hi), label in zip(buckets, bucket_labels):
                if lo <= days <= hi:
                    return label
            # If none matched, drop into the last bucket (acts as a catch-all)
            return bucket_labels[-1]

        results: list[dict] = []

        # Iterate all vendors
        all_vendors: Iterable[Vendor] = self.vendors.list_vendors()
        for v in all_vendors:
            # Pull all purchases for vendor (no date filter here), then filter by as_of & remaining_due > 0
            rows = self.purchases.list_purchases_by_vendor(v.vendor_id, None, None)
            # Normalize and filter
            open_rows = []
            for r in rows:
                try:
                    pdate_str = r["date"]
                    rdate = _to_date(pdate_str)
                except Exception:
                    # Skip rows with invalid dates (or treat as non-open)
                    continue

                if rdate <= cutoff:
                    # Prefer repo-provided remaining_due; fallback compute if missing
                    if "remaining_due" in r.keys():  # sqlite3.Row supports .keys()
                        remaining = float(r["remaining_due"])
                    else:
                        remaining = float(r["total_amount"]) - float(r["paid_amount"]) - float(r["advance_payment_applied"])
                    if remaining > 1e-9:
                        open_rows.append((pdate_str, remaining))

            if not open_rows:
                # No open invoices as of cutoff → skip vendor from snapshot
                continue

            # Initialize buckets for this vendor
            sums = {label: 0.0 for label in bucket_labels}
            total_due = 0.0
            for pdate_str, rem in open_rows:
                days = _days_outstanding(cutoff, pdate_str)
                label = pick_bucket(days)
                sums[label] += float(rem)
                total_due += float(rem)

            row_out = {
                "vendor_id": v.vendor_id,
                "vendor_name": v.name,
                "buckets": sums,
                "total_due": total_due,
            }

            if include_credit_column:
                try:
                    credit = float(self.vadv.get_balance(v.vendor_id))
                except Exception:
                    credit = 0.0
                row_out["available_credit"] = credit

            results.append(row_out)

        # Sort vendors by total_due DESC
        results.sort(key=lambda d: float(d.get("total_due", 0.0)), reverse=True)
        return results

    # ---------------------------------
    # Open invoices list for a vendor
    # ---------------------------------
    def list_open_invoices(self, vendor_id: int, as_of: str) -> list[dict]:
        """
        Return open invoices for vendor with date ≤ as_of and remaining_due > 0.

        Fields per row:
          purchase_id, date, total_amount, paid_amount, advance_payment_applied, remaining_due, days_outstanding
        """
        cutoff = _to_date(as_of)
        rows = self.purchases.list_purchases_by_vendor(vendor_id, None, None)

        out: list[dict] = []
        for r in rows:
            try:
                pdate = _to_date(r["date"])
            except Exception:
                continue
            if pdate > cutoff:
                continue

            # Remaining due (repo already provides `remaining_due`; recompute if absent)
            if "remaining_due" in r.keys():
                remaining = float(r["remaining_due"])
            else:
                remaining = float(r["total_amount"]) - float(r["paid_amount"]) - float(r["advance_payment_applied"])

            if remaining > 1e-9:
                out.append({
                    "purchase_id": r["purchase_id"],
                    "date": r["date"],
                    "total_amount": float(r["total_amount"]),
                    "paid_amount": float(r["paid_amount"]),
                    "advance_payment_applied": float(r["advance_payment_applied"]),
                    "remaining_due": remaining,
                    "days_outstanding": _days_outstanding(cutoff, r["date"]),
                })

        # Sort by (date ASC, purchase_id ASC) for a consistent invoice list
        out.sort(key=lambda d: (d["date"], d["purchase_id"]))
        return out
