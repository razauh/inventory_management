# inventory_management/modules/dashboard/model.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ...database.repositories.dashboard_repo import DashboardRepo


# --------------------------- Period helpers ---------------------------

@dataclass(frozen=True)
class DateRange:
    date_from: str  # ISO yyyy-mm-dd
    date_to: str    # ISO yyyy-mm-dd


def _calc_period(key: str, date_from: Optional[str] = None, date_to: Optional[str] = None) -> DateRange:
    """Resolve a friendly period key to a concrete (date_from, date_to)."""
    today = date.today()
    iso_today = today.isoformat()
    k = (key or "today").lower()

    if k == "today":
        return DateRange(iso_today, iso_today)
    if k == "mtd":
        start = date(today.year, today.month, 1).isoformat()
        return DateRange(start, iso_today)
    if k in ("last7", "7d"):
        start = (today - timedelta(days=6)).isoformat()  # inclusive range
        return DateRange(start, iso_today)
    if k == "custom" and date_from and date_to:
        return DateRange(str(date_from), str(date_to))

    # Fallback
    return DateRange(iso_today, iso_today)


# --------------------------- Dashboard Model ---------------------------

@dataclass
class DashboardModel:
    """
    Pulls data from DashboardRepo and exposes properties for the view.

    Usage:
        model = DashboardModel(conn)
        model.refresh(period=("today", None, None))
        print(model.kpi_today_sales, model.kpi_today_net_profit, ...)
    """

    conn: sqlite3.Connection
    repo: DashboardRepo = field(init=False)

    # current resolved range (set after refresh)
    date_from: str = field(init=False, default="")
    date_to: str = field(init=False, default="")

    # ---- KPI numbers (for current period) ----
    kpi_today_sales: float = 0.0
    kpi_today_gross_profit: float = 0.0
    kpi_today_net_profit: float = 0.0
    kpi_receipts_cleared: float = 0.0
    kpi_vendor_payments_cleared: float = 0.0
    kpi_ar_open: float = 0.0
    kpi_ap_open: float = 0.0
    low_stock_count: int = 0

    # ---- Tables / lists (dict rows) ----
    table_top_products: List[Dict[str, Any]] = field(default_factory=list)
    table_bank_accounts: List[Dict[str, Any]] = field(default_factory=list)
    table_payments_in: List[Dict[str, Any]] = field(default_factory=list)
    table_payments_out: List[Dict[str, Any]] = field(default_factory=list)
    table_quotations_expiring: List[Dict[str, Any]] = field(default_factory=list)
    low_stock_rows: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.conn.row_factory = sqlite3.Row
        self.repo = DashboardRepo(self.conn)

    # --------------------------- Public API ---------------------------

    def refresh(
        self,
        period: Tuple[str, Optional[str], Optional[str]] = ("today", None, None),
        *,
        top_products_limit: int = 5,
        low_stock_limit: int = 20,
        expiring_days: int = 7,
    ) -> None:
        """
        Fetch everything needed for the dashboard.

        Args:
          period: (key, custom_from, custom_to)
                  key in {"today","mtd","last7","custom"}
          top_products_limit: N rows for the leaderboard
          low_stock_limit: N rows for low-stock preview
          expiring_days: horizon for quotations expiring list
        """
        key, df_custom, dt_custom = period
        dr = _calc_period(key, df_custom, dt_custom)
        self.date_from, self.date_to = dr.date_from, dr.date_to

        df, dt = self.date_from, self.date_to

        # ---------- Batch 1: P&L ----------
        sales = self._safe(self.repo.total_sales, 0.0, df, dt)
        cogs = self._safe(self.repo.cogs_for_sales, 0.0, df, dt)
        expenses = self._safe(self.repo.expenses_total, 0.0, df, dt)

        gross = (sales or 0.0) - (cogs or 0.0)
        net = gross - (expenses or 0.0)

        self.kpi_today_sales = float(sales or 0.0)
        self.kpi_today_gross_profit = float(gross)
        self.kpi_today_net_profit = float(net)

        # ---------- Batch 2: Cash & bank flows ----------
        self.kpi_receipts_cleared = float(self._safe(self.repo.receipts_cleared, 0.0, df, dt) or 0.0)
        self.kpi_vendor_payments_cleared = float(self._safe(self.repo.vendor_payments_cleared, 0.0, df, dt) or 0.0)

        # Bank movements per account (for optional small table/chart)
        bank_rows = self._safe(self.repo.bank_movements_by_account, [], df, dt) or []
        self.table_bank_accounts = [self._normalize_row(r) for r in bank_rows]

        # ---------- Batch 3: AR/AP & stock ----------
        self.kpi_ar_open = float(self._safe(self.repo.open_receivables, 0.0) or 0.0)
        self.kpi_ap_open = float(self._safe(self.repo.open_payables, 0.0) or 0.0)
        self.low_stock_count = int(self._safe(self.repo.low_stock_count, 0) or 0)

        # Optional: low stock preview list (if the repo provides rows)
        try:
            rows = self.repo.low_stock_rows(limit_n=low_stock_limit)
            self.low_stock_rows = [self._normalize_row(r) for r in (rows or [])]
        except Exception:
            self.low_stock_rows = []

        # ---------- Batch 4: Leaderboards & pipelines ----------
        top_rows = self._safe(self.repo.top_products, [], df, dt, top_products_limit) or []
        self.table_top_products = [self._normalize_row(r) for r in top_rows]

        self.table_payments_in = [
            self._normalize_row(r) for r in (self._safe(self.repo.sales_payments_breakdown, [], df, dt) or [])
        ]
        self.table_payments_out = [
            self._normalize_row(r) for r in (self._safe(self.repo.purchase_payments_breakdown, [], df, dt) or [])
        ]

        # ---------- Batch 5: Quotations expiring (date-agnostic, uses days horizon) ----------
        self.table_quotations_expiring = [
            self._normalize_row(r) for r in (self._safe(self.repo.quotations_expiring, [], expiring_days) or [])
        ]

    # --------------------------- Internals ---------------------------

    def _safe(self, fn, default, *args):
        """Call repo fn safely, returning `default` on any error."""
        try:
            return fn(*args)
        except Exception:
            return default

    def _normalize_row(self, r: Any) -> Dict[str, Any]:
        """sqlite3.Row → dict or passthrough dict; shallow copy for safety."""
        if hasattr(r, "keys"):
            return {k: r[k] for k in r.keys()}
        if isinstance(r, dict):
            return dict(r)
        # Tuple/list → best-effort enumeration
        try:
            return dict(r)  # may fail if it isn't (k,v) pairs
        except Exception:
            return {"value": r}
