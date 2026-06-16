from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from inventory_management.modules.reporting.controller import ReportingController
from inventory_management.modules.reporting.enhanced_payment_reports import EnhancedPaymentReportsTab
from inventory_management.modules.reporting.purchase_reports import PurchaseReportsTab
from inventory_management.modules.reporting.sales_reports import SalesReportsTab


def test_reporting_controller_lazily_builds_tabs(app, qtbot, monkeypatch) -> None:
    counts = {
        "VendorAgingTab": 0,
        "SalesReportsTab": 0,
        "PaymentReportsTab": 0,
        "EnhancedPaymentReportsTab": 0,
        "ComprehensivePaymentReportsTab": 0,
    }

    class _SimpleWidget(QWidget):
        def __init__(self, _conn, **_kwargs) -> None:
            super().__init__()
            counts.setdefault(type(self).__name__, 0)
            counts[type(self).__name__] += 1
            self.refresh_calls = 0

        def refresh(self) -> None:
            self.refresh_calls += 1

    class VendorAgingTab(_SimpleWidget):
        pass

    class SalesReportsTab(_SimpleWidget):
        pass

    class PaymentReportsTab(_SimpleWidget):
        pass

    class _NestedWidget(_SimpleWidget):
        def __init__(self, _conn, **_kwargs) -> None:
            super().__init__(_conn, **_kwargs)
            self.tabs = QTabWidget()
            for index in range(3):
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.addWidget(QLabel(f"Page {index}"))
                self.tabs.addTab(page, f"Tab {index}")
            self.page_refreshes: list[int] = []

        def refresh_page(self, index: int) -> None:
            self.page_refreshes.append(index)

    class EnhancedPaymentReportsTab(_NestedWidget):
        pass

    class ComprehensivePaymentReportsTab(_NestedWidget):
        pass

    modules = {
        "inventory_management.modules.reporting.vendor_aging_reports": SimpleNamespace(
            VendorAgingTab=VendorAgingTab
        ),
        "inventory_management.modules.reporting.customer_aging_reports": SimpleNamespace(
            CustomerAgingTab=_SimpleWidget
        ),
        "inventory_management.modules.reporting.inventory_reports": SimpleNamespace(
            InventoryReportsTab=_SimpleWidget
        ),
        "inventory_management.modules.reporting.expense_reports": SimpleNamespace(
            ExpenseReportsTab=_SimpleWidget
        ),
        "inventory_management.modules.reporting.financial_reports": SimpleNamespace(
            FinancialReportsTab=_SimpleWidget
        ),
        "inventory_management.modules.reporting.sales_reports": SimpleNamespace(
            SalesReportsTab=SalesReportsTab
        ),
        "inventory_management.modules.reporting.purchase_reports": SimpleNamespace(
            PurchaseReportsTab=_SimpleWidget
        ),
        "inventory_management.modules.reporting.payment_reports": SimpleNamespace(
            PaymentReportsTab=PaymentReportsTab
        ),
        "inventory_management.modules.reporting.enhanced_payment_reports": SimpleNamespace(
            EnhancedPaymentReportsTab=EnhancedPaymentReportsTab
        ),
        "inventory_management.modules.reporting.comprehensive_payments_reports": SimpleNamespace(
            ComprehensivePaymentReportsTab=ComprehensivePaymentReportsTab
        ),
    }

    monkeypatch.setattr(
        "inventory_management.modules.reporting.controller.import_module",
        lambda path: modules[path],
    )

    conn = sqlite3.connect(":memory:")
    try:
        controller = ReportingController(conn)
        qtbot.addWidget(controller.get_widget())

        assert counts["VendorAgingTab"] == 1
        assert counts["SalesReportsTab"] == 0
        assert counts["PaymentReportsTab"] == 0
        assert counts["EnhancedPaymentReportsTab"] == 0
        assert counts["ComprehensivePaymentReportsTab"] == 0

        controller.tabs.setCurrentIndex(5)
        assert counts["SalesReportsTab"] == 1

        controller.tabs.setCurrentIndex(7)
        assert counts["PaymentReportsTab"] == 1
        assert counts["EnhancedPaymentReportsTab"] == 0
        assert counts["ComprehensivePaymentReportsTab"] == 0

        payments_host = controller.tabs.currentWidget()
        payments_host.tabs.setCurrentIndex(1)
        assert counts["EnhancedPaymentReportsTab"] == 1
        assert counts["ComprehensivePaymentReportsTab"] == 0
    finally:
        conn.close()


def test_sales_reports_refresh_only_loads_active_tab(app, qtbot) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        tab = SalesReportsTab(conn, auto_refresh=False)
        qtbot.addWidget(tab)

        calls = {
            "sales_by_period": 0,
            "sales_by_customer": 0,
        }

        tab.repo.sales_by_period = lambda *args: calls.__setitem__("sales_by_period", calls["sales_by_period"] + 1) or []
        tab.repo.sales_by_customer = lambda *args: calls.__setitem__("sales_by_customer", calls["sales_by_customer"] + 1) or []
        tab.repo.sales_by_product = lambda *args: []
        tab.repo.sales_by_category = lambda *args: []
        tab.repo.margin_by_period = lambda *args: []
        tab.repo.margin_by_customer = lambda *args: []
        tab.repo.margin_by_product = lambda *args: []
        tab.repo.margin_by_category = lambda *args: []
        tab.repo.top_customers = lambda *args: []
        tab.repo.top_products = lambda *args: []
        tab.repo.returns_summary = lambda *args: []
        tab.repo.status_breakdown = lambda *args: []
        tab.repo.drilldown_sales = lambda *args: []

        tab.refresh_active_page()
        assert calls["sales_by_period"] == 1
        assert calls["sales_by_customer"] == 0

        tab.tabs.setCurrentIndex(1)
        assert calls["sales_by_customer"] == 1
    finally:
        conn.close()


def test_purchase_reports_refresh_only_loads_active_tab(app, qtbot) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        tab = PurchaseReportsTab(conn, auto_refresh=False)
        qtbot.addWidget(tab)

        seen = {"period": 0, "vendor": 0}
        def _load_key(key, filters):
            if key == "purch_by_period":
                seen["period"] += 1
            if key == "purch_by_vendor":
                seen["vendor"] += 1
            return []

        tab._load_key = _load_key  # type: ignore[method-assign]
        tab.refresh_active_page()
        assert seen["period"] == 1
        assert seen["vendor"] == 0

        tab.tabs.setCurrentIndex(1)
        assert seen["vendor"] == 1
    finally:
        conn.close()


def test_enhanced_payment_reports_refresh_page_updates_only_active_model(app, qtbot) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        tab = EnhancedPaymentReportsTab(conn, auto_refresh=False)
        qtbot.addWidget(tab)

        tab._load_rows = lambda: (  # type: ignore[method-assign]
            [{"date": "2026-06-10", "amount": 10.0, "status": "cleared", "type": "Collection"}],
            [{"date": "2026-06-11", "amount": 5.0, "status": "pending", "type": "Collection"}],
            10.0,
            0.0,
            0.0,
            10.0,
            5.0,
            "Posting date",
            "2026-06-10",
            "2026-06-11",
        )

        tab.refresh_page(1)
        assert tab.model_status.rowCount() == 1
        assert tab.model_all.rowCount() == 0
        assert tab.model_uncleared.rowCount() == 0
    finally:
        conn.close()
