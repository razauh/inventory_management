# inventory_management/modules/dashboard/controller.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QWidget

from ..base_module import BaseModule

# Repo (implemented in database/repositories/dashboard_repo.py)
from modules.accounting import AccountingService
from ...database.repositories.dashboard_repo import DashboardRepo

# View & composite widgets (these are standard QWidget subclasses)
from .view import DashboardView  # main dashboard widget (top bar + cards + composites)


# ---------------------------- Helper types ----------------------------

@dataclass
class DateRange:
    date_from: str  # ISO yyyy-mm-dd
    date_to: str    # ISO yyyy-mm-dd


# ---------------------------- Controller ----------------------------

class DashboardController(BaseModule):
    """
    Owns the date context, coordinates repo <-> view, and emits navigation intents.

    Signals you can hook in your MainWindow/App:
      - navigate_to_report(target: str, params: dict): route to an existing module (e.g. Sales Reports)
         Examples of `target`:
           "sales_by_day", "sales_by_product", "sales_by_customer",
           "margin_by_day", "status_breakdown", "drilldown_sales",
           "purchase_by_day", etc.
         `params` should include at least {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}.
    """

    navigate_to_report = Signal(str, dict)

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.repo = DashboardRepo(conn)
        self.accounting = AccountingService(conn)
        self._refresh_gen = 0

        # View is a QWidget; the app should embed it where appropriate.
        self.view = DashboardView()
        self._wire_view()

        self._refresh_timer = QTimer(self.view)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)

        # default period is "Today"
        self._current_range = self._calc_period("today")
        self._schedule_refresh()

    # ---------------------------- Wiring ----------------------------

    def _wire_view(self) -> None:
        """
        Connect view events to controller actions.
        The DashboardView is expected to expose these signals:
          - period_changed(period_key: str, date_from: Optional[str], date_to: Optional[str])
          - kpi_drilldown(target: str)  # e.g., "sales_total", "gross_profit", etc.
          - request_drilldown(target: str, params: dict) from child widgets (optional)
        """
        # Period switch (Today / MTD / Last 7 / Custom)
        if hasattr(self.view, "period_changed"):
            self.view.period_changed.connect(self.on_period_changed)  # type: ignore



        # KPI cards click
        if hasattr(self.view, "kpi_drilldown"):
            self.view.kpi_drilldown.connect(lambda key, df, dt: self._on_kpi_clicked(key))  # type: ignore

        # Composite widgets may bubble drilldown requests via the view
        if hasattr(self.view, "requestDrilldown"):
            self.view.requestDrilldown.connect(self._on_request_drilldown)  # type: ignore

    # ---------------------------- Period handling ----------------------------

    @Slot(str, object, object)
    def on_period_changed(self, period_key: str, date_from: Optional[str], date_to: Optional[str]) -> None:
        """
        period_key in {"today","mtd","last7","custom"}.
        If "custom", date_from/date_to are provided (or None).
        """
        self._current_range = self._calc_period(period_key, date_from, date_to)
        self._schedule_refresh()

    def _calc_period(self, key: str, df: Optional[str] = None, dt: Optional[str] = None) -> DateRange:
        today = date.today()
        iso_today = today.isoformat()

        key = (key or "today").lower()
        if key == "today":
            return DateRange(iso_today, iso_today)
        if key == "mtd":
            first_of_month = date(today.year, today.month, 1).isoformat()
            return DateRange(first_of_month, iso_today)
        if key == "last7":
            start = (today - timedelta(days=6)).isoformat()  # inclusive of today → 7 days window
            return DateRange(start, iso_today)
        # custom
        if df and dt:
            return DateRange(str(df), str(dt))
        # fallback to today
        return DateRange(iso_today, iso_today)

    # ---------------------------- Refresh pipeline ----------------------------

    @Slot()
    def refresh(self) -> None:
        """
        Pull fresh data from repo for the current date range and push it to the view/widgets.
        """
        self._refresh_timer.stop()
        df, dt = self._current_range.date_from, self._current_range.date_to
        self._refresh_gen += 1
        gen = self._refresh_gen

        try:
            metrics = self.accounting.get_sales_dashboard_metrics(df, dt)
            summary = {
                "total_sales": float(metrics.total_sales),
                "total_cogs": float(metrics.total_cogs),
                "total_expenses": float(metrics.total_expenses),
                "receipts_cleared": float(metrics.receipts_cleared),
                "vendor_payments_cleared": float(metrics.vendor_payments_cleared),
                "open_receivables": float(metrics.open_receivables),
                "open_payables": float(metrics.open_payables),
                "low_stock_count": self.repo.low_stock_count(),
            }
        except Exception:
            summary = {
                "total_sales": 0.0, "total_cogs": 0.0, "total_expenses": 0.0,
                "receipts_cleared": 0.0, "vendor_payments_cleared": 0.0,
                "open_receivables": 0.0, "open_payables": 0.0, "low_stock_count": 0,
            }

        total_sales = float(summary.get("total_sales") or 0.0)
        total_cogs = float(summary.get("total_cogs") or 0.0)
        total_exp = float(summary.get("total_expenses") or 0.0)
        gross = total_sales - total_cogs
        net = gross - total_exp
        receipts_cleared = float(summary.get("receipts_cleared") or 0.0)
        vendor_pmt_cleared = float(summary.get("vendor_payments_cleared") or 0.0)
        ar_open = float(summary.get("open_receivables") or 0.0)
        ap_open = float(summary.get("open_payables") or 0.0)
        low_stock_count = int(summary.get("low_stock_count") or 0)

        self._apply_core_summary(
            total_sales=total_sales,
            total_cogs=total_cogs,
            total_exp=total_exp,
            gross=gross,
            net=net,
            receipts_cleared=receipts_cleared,
            vendor_pmt_cleared=vendor_pmt_cleared,
            ar_open=ar_open,
            ap_open=ap_open,
            low_stock_count=low_stock_count,
            df=df,
            dt=dt,
        )

        self._clear_secondary_widgets()
        QTimer.singleShot(0, lambda gen=gen, df=df, dt=dt: self._refresh_secondary(gen, df, dt))

    def _schedule_refresh(self) -> None:
        """Queue a dashboard refresh so the UI can paint first."""
        self._refresh_timer.start(0)

    def _apply_core_summary(
        self,
        *,
        total_sales: float,
        total_cogs: float,
        total_exp: float,
        gross: float,
        net: float,
        receipts_cleared: float,
        vendor_pmt_cleared: float,
        ar_open: float,
        ap_open: float,
        low_stock_count: int,
        df: str,
        dt: str,
    ) -> None:
        self.view.set_kpi_value("sales_total", total_sales)
        self.view.set_kpi_value("gross_profit", gross)
        self.view.set_kpi_value("net_profit", net)
        self.view.set_kpi_value("receipts_cleared", receipts_cleared)
        self.view.set_kpi_value("vendor_payments_cleared", vendor_pmt_cleared)
        self.view.set_kpi_value("open_receivables", ar_open)
        self.view.set_kpi_value("open_payables", ap_open)
        self.view.set_kpi_value("low_stock", low_stock_count)

        self.view.financial_overview.set_pl(total_sales, total_cogs, total_exp, net)
        self.view.financial_overview.set_ar_ap(ar_open, ap_open)
        self.view.financial_overview.set_low_stock_count(low_stock_count)

        if hasattr(self.view, "setPeriodText"):
            self.view.setPeriodText(self._human_period(df, dt))  # type: ignore

    def _clear_secondary_widgets(self) -> None:
        if hasattr(self.view.payment_summary, "set_sales_breakdown"):
            self.view.payment_summary.set_sales_breakdown([])
            self.view.payment_summary.set_purchase_breakdown([])
        self.view.set_top_products([])
        self.view.set_quotations([])

    def _refresh_secondary(self, gen: int, df: str, dt: str) -> None:
        if gen != self._refresh_gen:
            return

        incoming_rows = self.safe_repo_call(lambda: self.repo.sales_payments_breakdown(df, dt), [])
        outgoing_rows = self.safe_repo_call(lambda: self.repo.purchase_payments_breakdown(df, dt), [])
        top_products = self.safe_repo_call(lambda: self.repo.top_products(df, dt, limit_n=5), [])

        today = date.today()
        df_q = today.isoformat()
        dt_q = (today + timedelta(days=7)).isoformat()
        quotes_exp = self.safe_repo_call(lambda: self.repo.quotations_expiring(df_q, dt_q), [])

        if gen != self._refresh_gen:
            return

        if hasattr(self.view.payment_summary, "set_sales_breakdown"):
            self.view.payment_summary.set_sales_breakdown(incoming_rows)
            self.view.payment_summary.set_purchase_breakdown(outgoing_rows)

        self.view.set_top_products(top_products)
        self.view.set_quotations(quotes_exp)

    # ---------------------------- Button handlers ----------------------------



    # ---------------------------- Card clicks → navigation ----------------------------

    @Slot(str)
    def _on_kpi_clicked(self, card_id: str) -> None:
        """
        Route KPI card clicks to relevant reporting tabs with the current date range.
        Map your card IDs to report targets here.
        """
        df, dt = self._current_range.date_from, self._current_range.date_to

        mapping = {
            "sales_total": ("sales_by_day", {}),
            "gross_profit": ("margin_by_day", {}),
            "net_profit": ("margin_by_day", {}),  # still the same view; net shown in FinancialOverview
            "receipts_cleared": ("status_breakdown", {"payment_side": "sales"}),
            "vendor_payments_cleared": ("status_breakdown", {"payment_side": "purchases"}),
            # add others if you add more cards
        }
        target, extra = mapping.get(card_id, ("sales_by_day", {}))
        params = {"date_from": df, "date_to": dt}
        params.update(extra or {})
        self.navigate_to_report.emit(target, params)

    @Slot(str, dict)
    def _on_request_drilldown(self, target: str, params: dict) -> None:
        """
        Bubble up drilldown requests coming from the View or its sub-widgets.
        Ensures the current date range is present unless explicitly overridden.
        """
        p = dict(params or {})
        p.setdefault("date_from", self._current_range.date_from)
        p.setdefault("date_to", self._current_range.date_to)
        self.navigate_to_report.emit(target, p)

    # ---------------------------- Utilities ----------------------------

    def get_widget(self) -> QWidget:
        """Return the main QWidget to embed in your window (required by BaseModule)."""
        return self.view

    def widget(self) -> DashboardView:
        """Return the main QWidget to embed in your window."""
        return self.view

    def safe_repo_call(self, fn, default):
        try:
            return fn()
        except Exception:
            return default

    def _human_period(self, df: str, dt: str) -> str:
        try:
            d1 = datetime.strptime(df, "%Y-%m-%d").date()
            d2 = datetime.strptime(dt, "%Y-%m-%d").date()
            if d1 == d2:
                return f"{d1.strftime('%d %b %Y')}"
            if d1.year == d2.year:
                if d1.month == d2.month:
                    return f"{d1.strftime('%d')}–{d2.strftime('%d %b %Y')}"
                return f"{d1.strftime('%d %b')} – {d2.strftime('%d %b %Y')}"
            return f"{d1.strftime('%d %b %Y')} – {d2.strftime('%d %b %Y')}"
        except Exception:
            return f"{df} → {dt}"
