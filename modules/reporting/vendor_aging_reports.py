from __future__ import annotations
import sqlite3
from datetime import datetime, date
from typing import Tuple, Iterable

from inventory_management.database.repositories.purchases_repo import PurchasesRepo
from inventory_management.database.repositories.vendors_repo import VendorsRepo, Vendor
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo


def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _days_outstanding(as_of: date, doc_date_str: str) -> int:
    try:
        d = _to_date(doc_date_str)
    except Exception:
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

    # -------- internal helpers --------
    def _fetch_purchase_headers_as_of(self, vendor_id: int, as_of: str) -> list[sqlite3.Row]:
        """
        Pull header rows needed for aging (includes paid & advance fields) with date <= as_of.
        """
        sql = """
        SELECT
          p.purchase_id,
          p.date,
          CAST(p.total_amount AS REAL)             AS total_amount,
          CAST(p.paid_amount AS REAL)              AS paid_amount,
          CAST(p.advance_payment_applied AS REAL)  AS advance_payment_applied
        FROM purchases p
        WHERE p.vendor_id = ?
          AND DATE(p.date) <= DATE(?)
        ORDER BY DATE(p.date) ASC, p.purchase_id ASC
        """
        cur = self.conn.execute(sql, (vendor_id, as_of))
        return cur.fetchall()

    def _credit_balance_as_of(self, vendor_id: int, as_of: str) -> float:
        """
        Credit available as of cutoff (sum of vendor_advances up to that date).
        """
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS bal
            FROM vendor_advances
            WHERE vendor_id = ?
              AND DATE(tx_date) <= DATE(?)
            """,
            (vendor_id, as_of),
        ).fetchone()
        return float(row["bal"] if isinstance(row, sqlite3.Row) else row[0])

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
          - Optionally fetch available vendor credit (as-of the cutoff)
        """
        cutoff = _to_date(as_of)
        bucket_labels = [f"{lo}-{hi}" for (lo, hi) in buckets]

        def pick_bucket(days: int) -> str:
            for (lo, hi), label in zip(buckets, bucket_labels):
                if lo <= days <= hi:
                    return label
            return bucket_labels[-1]

        results: list[dict] = []

        all_vendors: Iterable[Vendor] = self.vendors.list_vendors()
        for v in all_vendors:
            headers = self._fetch_purchase_headers_as_of(v.vendor_id, as_of)

            open_rows: list[tuple[str, float]] = []
            for r in headers:
                pdate_str = r["date"]
                try:
                    _ = _to_date(pdate_str)
                except Exception:
                    continue

                remaining = float(r["total_amount"]) - float(r["paid_amount"]) - float(r["advance_payment_applied"])
                if remaining > 1e-9:
                    open_rows.append((pdate_str, remaining))

            if not open_rows:
                continue

            sums = {label: 0.0 for label in bucket_labels}
            total_due = 0.0
            for pdate_str, rem in open_rows:
                days = _days_outstanding(cutoff, pdate_str)
                sums[pick_bucket(days)] += rem
                total_due += rem

            row_out = {
                "vendor_id": v.vendor_id,
                "vendor_name": v.name,
                "buckets": sums,
                "total_due": total_due,
            }

            if include_credit_column:
                row_out["available_credit"] = self._credit_balance_as_of(v.vendor_id, as_of)

            results.append(row_out)

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
        headers = self._fetch_purchase_headers_as_of(vendor_id, as_of)

        out: list[dict] = []
        for r in headers:
            pdate_str = r["date"]
            try:
                pdate = _to_date(pdate_str)
            except Exception:
                continue
            if pdate > cutoff:
                continue

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

        out.sort(key=lambda d: (d["date"], d["purchase_id"]))
        return out
