# inventory_management/modules/reporting/controller.py
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget

from ..base_module import BaseModule


logger = logging.getLogger(__name__)


def _placeholder_tab(msg: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lbl = QLabel(msg)
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    return w


def _safe_build_widget(
    module_path: str,
    class_name: str,
    conn: sqlite3.Connection,
    placeholder_msg: str,
    init_kwargs: Optional[Dict[str, Any]] = None,
) -> QWidget:
    try:
        mod = import_module(module_path)
        cls = getattr(mod, class_name)
        kwargs = dict(init_kwargs or {})
        try:
            return cls(conn, **kwargs)
        except TypeError:
            return cls(conn)
    except Exception as exc:
        import sys
        import traceback

        print(
            f"[Reporting:{class_name}] failed to load from {module_path}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc()
        return _placeholder_tab(f"{placeholder_msg}\n\n({module_path}.{class_name} failed to load)")


@dataclass
class _TabDescriptor:
    key: str
    title: str
    placeholder_msg: str
    module_path: Optional[str] = None
    class_name: Optional[str] = None
    init_kwargs: Dict[str, Any] = field(default_factory=dict)
    widget: Optional[QWidget] = None


class PaymentsTabHost(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self._sources: Dict[str, QWidget] = {}
        self._page_hosts: Dict[str, QWidget] = {}
        self._source_attached = False
        self._flat_tabs: list[dict[str, Any]] = [
            {"key": "summary", "title": "Summary", "family": "summary"},
            {
                "key": "enhanced_all",
                "title": "All Payment Records",
                "family": "enhanced",
                "source_index": 0,
            },
            {
                "key": "enhanced_status",
                "title": "All Payments by Status",
                "family": "enhanced",
                "source_index": 1,
            },
            {
                "key": "enhanced_uncleared",
                "title": "Uncleared Payment Records",
                "family": "enhanced",
                "source_index": 2,
            },
            {
                "key": "comprehensive_status",
                "title": "Payment Summary by Status",
                "family": "comprehensive",
                "source_index": 0,
            },
            {
                "key": "comprehensive_unprocessed",
                "title": "Unprocessed Payment Records",
                "family": "comprehensive",
                "source_index": 1,
            },
            {
                "key": "comprehensive_all",
                "title": "Detailed Payment Records",
                "family": "comprehensive",
                "source_index": 2,
            },
        ]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget(self)
        for spec in self._flat_tabs:
            host = _placeholder_tab("Open tab to load report.")
            self._page_hosts[spec["key"]] = host
            self.tabs.addTab(host, spec["title"])
        self.tabs.currentChanged.connect(self._on_current_changed)
        root.addWidget(self.tabs)

    def _build_source(self, family: str) -> QWidget:
        if family == "summary":
            return _safe_build_widget(
                "inventory_management.modules.reporting.payment_reports",
                "PaymentReportsTab",
                self.conn,
                "Payment summary tab not available yet.",
                {"auto_refresh": False},
            )
        if family == "enhanced":
            return _safe_build_widget(
                "inventory_management.modules.reporting.enhanced_payment_reports",
                "EnhancedPaymentReportsTab",
                self.conn,
                "Enhanced payment reports tab not available yet.",
                {"auto_refresh": False, "use_background_refresh": True},
            )
        return _safe_build_widget(
            "inventory_management.modules.reporting.comprehensive_payments_reports",
            "ComprehensivePaymentReportsTab",
            self.conn,
            "Comprehensive payment reports tab not available yet.",
            {"auto_refresh": False, "use_background_refresh": True},
        )

    def _ensure_family(self, family: str) -> QWidget:
        widget = self._sources.get(family)
        if widget is not None:
            return widget
        widget = self._build_source(family)
        self._sources[family] = widget

        if family == "summary":
            host = self._page_hosts["summary"]
            lay = host.layout()
            if lay is not None:
                while lay.count():
                    item = lay.takeAt(0)
                    child = item.widget()
                    if child is not None:
                        child.setParent(None)
                lay.addWidget(widget)
            return widget

        tabs = getattr(widget, "tabs", None)
        if tabs is None:
            return widget

        for spec in self._flat_tabs:
            if spec["family"] != family:
                continue
            source_index = int(spec["source_index"])
            page = tabs.widget(source_index)
            host = self._page_hosts[spec["key"]]
            lay = host.layout()
            if page is None or lay is None:
                continue
            while lay.count():
                item = lay.takeAt(0)
                child = item.widget()
                if child is not None:
                    child.setParent(None)
            page.setParent(host)
            lay.addWidget(page)
        return widget

    def _refresh_spec(self, spec: dict[str, Any]) -> None:
        family = str(spec["family"])
        widget = self._ensure_family(family)
        if family == "summary":
            fn = getattr(widget, "refresh", None)
            if callable(fn):
                fn()
            return

        refresh_page = getattr(widget, "refresh_page", None)
        if callable(refresh_page):
            refresh_page(int(spec["source_index"]))
            return

        tabs = getattr(widget, "tabs", None)
        if tabs is not None:
            tabs.setCurrentIndex(int(spec["source_index"]))
        fn = getattr(widget, "refresh", None)
        if callable(fn):
            fn()

    @Slot(int)
    def _on_current_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._flat_tabs):
            return
        self._refresh_spec(self._flat_tabs[index])

    def refresh(self) -> None:
        idx = self.tabs.currentIndex()
        if idx < 0 or idx >= len(self._flat_tabs):
            return
        self._refresh_spec(self._flat_tabs[idx])

    def cancel_refresh(self) -> None:
        for widget in self._sources.values():
            fn = getattr(widget, "cancel_refresh", None)
            if callable(fn):
                fn()


class ReportingController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: Optional[dict] = None) -> None:
        try:
            super().__init__()
        except Exception:
            pass

        self.conn = conn
        self.user = current_user
        self._descriptors: list[_TabDescriptor] = []

        self._root = QWidget()
        self._root.setObjectName("ReportingModuleRoot")
        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget(self._root)
        self.tabs.setObjectName("ReportingTabs")
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setMovable(False)
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)

        self._register_tabs()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._ensure_tab(self.tabs.currentIndex())
        self._safe_refresh(self.tabs.currentWidget())

    def _register_tabs(self) -> None:
        self._add_descriptor(
            _TabDescriptor(
                key="vendor_aging",
                title="Vendor Aging",
                module_path="inventory_management.modules.reporting.vendor_aging_reports",
                class_name="VendorAgingTab",
                placeholder_msg="Vendor Aging tab failed to load.",
                init_kwargs={"auto_refresh": False},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="customer_aging",
                title="Customer Aging",
                module_path="inventory_management.modules.reporting.customer_aging_reports",
                class_name="CustomerAgingTab",
                placeholder_msg="Customer Aging tab failed to load.",
                init_kwargs={"auto_refresh": False},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="inventory",
                title="Inventory",
                module_path="inventory_management.modules.reporting.inventory_reports",
                class_name="InventoryReportsTab",
                placeholder_msg="Inventory Reports tab failed to load.",
                init_kwargs={"auto_refresh": False},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="expenses",
                title="Expenses",
                module_path="inventory_management.modules.reporting.expense_reports",
                class_name="ExpenseReportsTab",
                placeholder_msg="Expense Reports tab failed to load.",
                init_kwargs={"auto_refresh": False},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="financials",
                title="Financials",
                module_path="inventory_management.modules.reporting.financial_reports",
                class_name="FinancialReportsTab",
                placeholder_msg="Financial Reports tab failed to load.",
                init_kwargs={"auto_refresh": False},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="sales",
                title="Sales",
                module_path="inventory_management.modules.reporting.sales_reports",
                class_name="SalesReportsTab",
                placeholder_msg="Sales Reports tab not available yet.",
                init_kwargs={"auto_refresh": False, "use_background_refresh": True},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="purchases",
                title="Purchases",
                module_path="inventory_management.modules.reporting.purchase_reports",
                class_name="PurchaseReportsTab",
                placeholder_msg="Purchase Reports tab not available yet.",
                init_kwargs={"auto_refresh": False, "use_background_refresh": True},
            )
        )
        self._add_descriptor(
            _TabDescriptor(
                key="payments",
                title="Payments",
                placeholder_msg="Payment Reports tab not available yet.",
            )
        )

    def _add_descriptor(self, descriptor: _TabDescriptor) -> None:
        self._descriptors.append(descriptor)
        self.tabs.addTab(_placeholder_tab("Open tab to load report."), descriptor.title)

    def _create_widget(self, descriptor: _TabDescriptor) -> QWidget:
        if descriptor.key == "payments":
            return PaymentsTabHost(self.conn)
        assert descriptor.module_path is not None
        assert descriptor.class_name is not None
        return _safe_build_widget(
            descriptor.module_path,
            descriptor.class_name,
            self.conn,
            descriptor.placeholder_msg,
            descriptor.init_kwargs,
        )

    def _ensure_tab(self, index: int) -> QWidget | None:
        if index < 0 or index >= len(self._descriptors):
            return None
        descriptor = self._descriptors[index]
        if descriptor.widget is not None:
            return descriptor.widget
        widget = self._create_widget(descriptor)
        descriptor.widget = widget
        old = self.tabs.widget(index)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, widget, descriptor.title)
        self.tabs.setCurrentIndex(index)
        if old is not None:
            old.deleteLater()
        return widget

    def get_widget(self) -> QWidget:
        return self._root

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        app = QApplication.instance()
        if app is not None:
            try:
                app.setOverrideCursor(Qt.WaitCursor)
            except Exception:
                app = None
        try:
            widget = self._ensure_tab(index)
            self._safe_refresh(widget)
        finally:
            if app is not None:
                try:
                    app.restoreOverrideCursor()
                except Exception as exc:
                    logger.error("Failed to restore override cursor: %s", exc, exc_info=True)

    def _safe_refresh(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        fn = getattr(widget, "refresh_active_page", None)
        if not callable(fn):
            fn = getattr(widget, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception as exc:
                try:
                    obj_name = widget.objectName()
                except Exception:
                    obj_name = ""
                logger.warning(
                    "Reporting.refresh_failed widget=%s objectName=%s exc=%s",
                    type(widget).__name__,
                    obj_name,
                    exc,
                    exc_info=True,
                )

    def open_sub(self, key: str) -> None:
        for index, descriptor in enumerate(self._descriptors):
            if descriptor.key == key:
                self.tabs.setCurrentIndex(index)
                return

    def refresh(self) -> None:
        self._safe_refresh(self.tabs.currentWidget())
