# inventory_management/modules/dashboard/controller.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QWidget

from ..base_module import BaseModule

# Repo (implemented in database/repositories/dashboard_repo.py)
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
      - open_create_sale(): ask the app to open the sales entry screen
      - open_add_expense(): ask the app to open the expense dialog
      - navigate_to_report(target: str, params: dict): route to an existing module (e.g. Sales Reports)
         Examples of `target`:
           "sales_by_day", "sales_by_product", "sales_by_customer",
           "margin_by_day", "status_breakdown", "drilldown_sales",
           "purchase_by_day", etc.
         `params` should include at least {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}.
    """

    open_create_sale = Signal()
    open_add_expense = Signal()
    navigate_to_report = Signal(str, dict)

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.repo = DashboardRepo(conn)

        # View is a QWidget; the app should embed it where appropriate.
        self.view = DashboardView()
        self._wire_view()

        # default period is "Today"
        self._current_range = self._calc_period("today")
        self.refresh()

    # ---------------------------- Wiring ----------------------------

    def _wire_view(self) -> None:
        """
        Connect view events to controller actions.
        The DashboardView is expected to expose these signals:
          - period_changed(period_key: str, date_from: Optional[str], date_to: Optional[str])
          - create_sale_requested()
          - add_expense_requested()
          - kpi_drilldown(target: str)  # e.g., "sales_total", "gross_profit", etc.
          - request_drilldown(target: str, params: dict) from child widgets (optional)
        """
        # Period switch (Today / MTD / Last 7 / Custom)
        if hasattr(self.view, "period_changed"):
            self.view.period_changed.connect(self.on_period_changed)  # type: ignore

        # Top bar buttons
        if hasattr(self.view, "create_sale_requested"):
            self.view.create_sale_requested.connect(self._on_create_sale)  # type: ignore
        if hasattr(self.view, "add_expense_requested"):
            self.view.add_expense_requested.connect(self._on_add_expense)  # type: ignore

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
        self.refresh()

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
        df, dt = self._current_range.date_from, self._current_range.date_to

        # 1) KPIs (sales, cogs, expenses, gross, net)
        total_sales = self.repo.total_sales(df, dt) or 0.0
        total_cogs = self.repo.cogs_for_sales(df, dt) or 0.0
        total_exp = self.repo.expenses_total(df, dt) or 0.0
        gross = (total_sales - total_cogs)
        net = (gross - total_exp)

        # 2) Cash/bank (cleared today/period)
        receipts_cleared = self.repo.receipts_cleared(df, dt) or 0.0
        vendor_pmt_cleared = self.repo.vendor_payments_cleared(df, dt) or 0.0

        # 3) AR / AP & stock health
        ar_open = self.repo.open_receivables() or 0.0
        ap_open = self.repo.open_payables() or 0.0
        low_stock_count = self.repo.low_stock_count() or 0

        # 4) Payment breakdown tables
        incoming_rows = self.repo.sales_payments_breakdown(df, dt) or []
        outgoing_rows = self.repo.purchase_payments_breakdown(df, dt) or []

        # 5) Optional small tables
        top_products = self.safe_repo_call(lambda: self.repo.top_products(df, dt, limit_n=5), [])

        # Expiring quotations: anchor to app-local 'today'
        today = date.today()
        df_q = today.isoformat()
        dt_q = (today + timedelta(days=7)).isoformat()
        quotes_exp = self.safe_repo_call(lambda: self.repo.quotations_expiring(df_q, dt_q), [])

        # -------- Push to view --------
        # KPI Cards – update each card value
        self.view.set_kpi_value("sales_total", total_sales)
        self.view.set_kpi_value("gross_profit", gross)
        self.view.set_kpi_value("net_profit", net)
        self.view.set_kpi_value("receipts_cleared", receipts_cleared)
        self.view.set_kpi_value("vendor_payments_cleared", vendor_pmt_cleared)
        self.view.set_kpi_value("open_receivables", ar_open)
        self.view.set_kpi_value("open_payables", ap_open)
        self.view.set_kpi_value("low_stock", int(low_stock_count))

        # Financial overview widget (P&L, AR/AP, Low stock)
        self.view.financial_overview.set_pl(total_sales, total_cogs, total_exp, net)
        self.view.financial_overview.set_ar_ap(ar_open, ap_open)
        self.view.financial_overview.set_low_stock_count(int(low_stock_count))

        # Payment summary tables (if widget is implemented)
        if hasattr(self.view.payment_summary, "set_sales_breakdown"):
            self.view.payment_summary.set_sales_breakdown(incoming_rows)
            self.view.payment_summary.set_purchase_breakdown(outgoing_rows)

        # Update small tables
        self.view.set_top_products(top_products)
        self.view.set_quotations(quotes_exp)

        # Let the view update its header subtitle / breadcrumbs if it wants
        if hasattr(self.view, "setPeriodText"):
            self.view.setPeriodText(self._human_period(df, dt))  # type: ignore

    # ---------------------------- Button handlers ----------------------------

    @Slot()
    def _on_create_sale(self) -> None:
        # Defer actual screen opening to the host app.
        self.open_create_sale.emit()

    @Slot()
    def _on_add_expense(self) -> None:
        # Defer to the host app.
        self.open_add_expense.emit()

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