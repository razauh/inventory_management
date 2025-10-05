from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QSize, QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QDateEdit,
    QGridLayout, QFrame, QSizePolicy, QTableView, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication, QSpacerItem
)
from PySide6.QtGui import QStandardItemModel, QStandardItem

# Prefer app TableView if available
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView

# Composite blocks
from .financial_overview_widget import FinancialOverviewWidget

# PaymentSummaryWidget may not be implemented yet—render a placeholder gracefully.
try:
    from .payment_summary_widget import PaymentSummaryWidget  # type: ignore
except Exception:  # pragma: no cover
    class PaymentSummaryWidget(QWidget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            l = QVBoxLayout(self)
            l.setContentsMargins(12, 12, 12, 12)
            box = QFrame()
            box.setFrameShape(QFrame.StyledPanel)
            box.setStyleSheet("QFrame {border:1px dashed #bbb; border-radius:8px;}")
            bl = QVBoxLayout(box)
            bl.addWidget(QLabel("<i>PaymentSummaryWidget not implemented yet</i>"))
            l.addWidget(box)


def _money(x: Optional[float]) -> str:
    try:
        return f"{float(x or 0.0):,.2f}"
    except Exception:
        return "0.00"


class DashboardView(QWidget):
    """
    Pure-UI dashboard surface. Controller drives it by calling the setters.

    Signals:
        create_sale_requested()
        add_expense_requested()
        period_changed(period_key: str, date_from: str, date_to: str)
        kpi_drilldown(key: str, date_from: str, date_to: str)
        low_stock_view_requested()

    Public setters the controller will use:
        set_kpi_value(key, value, caption=None)
        set_top_products(rows)
        set_quotations(rows)
        financial_overview.set_pl(...)
        financial_overview.set_ar_ap(...)
        financial_overview.set_low_stock_count(...)
        set_period_from_to(df, dt)  # updates date edits + combo to 'Custom'
    """

    # Top-bar actions
    create_sale_requested = Signal()
    add_expense_requested = Signal()
    # Period & drilldowns
    period_changed = Signal(str, str, str)
    kpi_drilldown = Signal(str, str, str)
    # Shortcuts
    low_stock_view_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kpi_cards: Dict[str, KPICard] = {}
        self._period_key = "today"
        self._build_ui()
        self._wire()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ===== Top Bar =====
        top = QHBoxLayout()
        title = QLabel("<h2>Dashboard</h2>")
        title.setTextFormat(Qt.RichText)

        top.addWidget(title)
        top.addStretch(1)

        self.cmb_period = QComboBox()
        self.cmb_period.addItems(["Today", "MTD", "Last 7 Days", "Custom"])
        self.cmb_period.setCurrentIndex(0)

        self.ed_from = QDateEdit()
        self.ed_from.setCalendarPopup(True)
        self.ed_from.setDisplayFormat("yyyy-MM-dd")
        self.ed_to = QDateEdit()
        self.ed_to.setCalendarPopup(True)
        self.ed_to.setDisplayFormat("yyyy-MM-dd")
        self._set_dates_for_key("today")  # default

        self.btn_apply_period = QPushButton("Apply")
        self._toggle_custom_dates(False)

        top.addWidget(QLabel("Period:"))
        top.addWidget(self.cmb_period)
        top.addWidget(self.ed_from)
        top.addWidget(self.ed_to)
        top.addWidget(self.btn_apply_period)

        root.addLayout(top)

        # ===== KPI Grid =====
        gridwrap = QWidget()
        self.grid = QGridLayout(gridwrap)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)

        def add_kpi(key: str, title: str, caption: str) -> None:
            card = KPICard(title, caption)
            card.clicked.connect(lambda k=key: self._emit_kpi(k))
            self._kpi_cards[key] = card
            self._reflow_kpis()

        # Core KPIs (controller can update captions if needed)
        add_kpi("total_sales", "Total Sales", "period sales")
        add_kpi("gross_profit", "Gross Profit", "sales - cogs")
        add_kpi("net_profit", "Net Profit", "after expenses")
        add_kpi("receipts_cleared", "Receipts (Cleared)", "cash/bank in")
        add_kpi("vendor_payments_cleared", "Vendor Payments (Cleared)", "cash/bank out")
        add_kpi("open_receivables", "Open Receivables", "AR balance")
        add_kpi("open_payables", "Open Payables", "AP balance")
        add_kpi("low_stock", "Low Stock Items", "below min levels")

        gridwrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(gridwrap)

        # ===== Body: 2 composite widgets =====
        body = QHBoxLayout()
        body.setSpacing(10)

        self.financial_overview = FinancialOverviewWidget()
        self.financial_overview.view_low_stock_requested.connect(self.low_stock_view_requested)
        self.financial_overview.ar_drilldown_requested.connect(
            lambda: self._emit_kpi("open_receivables")
        )
        self.financial_overview.ap_drilldown_requested.connect(
            lambda: self._emit_kpi("open_payables")
        )

        self.payment_summary = PaymentSummaryWidget()

        body.addWidget(self.financial_overview, 1)
        body.addWidget(self.payment_summary, 1)

        root.addLayout(body)

        # ===== Optional small tables =====
        tables = QHBoxLayout()
        tables.setSpacing(10)

        self.tbl_top_products = _BaseTableView()
        self._prep_simple_table(self.tbl_top_products, ["Product", "Qty (base)", "Revenue"])
        self.model_top_products = QStandardItemModel(0, 3)
        self.model_top_products.setHorizontalHeaderLabels(["Product", "Qty (base)", "Revenue"])
        self.tbl_top_products.setModel(self.model_top_products)
        tables.addWidget(_Card(self.tbl_top_products, "Top Products (Period)"))

        self.tbl_quotations = _BaseTableView()
        self._prep_simple_table(self.tbl_quotations, ["Quotation", "Customer", "Expiry", "Amount"])
        self.model_quot = QStandardItemModel(0, 4)
        self.model_quot.setHorizontalHeaderLabels(["Quotation", "Customer", "Expiry", "Amount"])
        self.tbl_quotations.setModel(self.model_quot)
        tables.addWidget(_Card(self.tbl_quotations, "Quotations Expiring Soon"))

        root.addLayout(tables)

        root.addItem(QSpacerItem(0, 6, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def _wire(self) -> None:


        self.cmb_period.currentIndexChanged.connect(self._on_period_combo)
        self.btn_apply_period.clicked.connect(self._apply_period)
        self.ed_from.dateChanged.connect(lambda *_: self._on_custom_edited())
        self.ed_to.dateChanged.connect(lambda *_: self._on_custom_edited())

    # ---------------- KPI + period helpers ----------------
    def _emit_kpi(self, key: str) -> None:
        df, dt = self._current_period_dates()
        self.kpi_drilldown.emit(key, df, dt)

    def _on_period_combo(self) -> None:
        key = self._period_key_from_combo()
        self._period_key = key
        self._toggle_custom_dates(key == "custom")
        # For non-custom, immediately update dates and emit
        if key != "custom":
            self._set_dates_for_key(key)
            self._apply_period()

    def _on_custom_edited(self) -> None:
        # Don't spam emits while editing; wait for Apply.
        pass

    def _apply_period(self) -> None:
        df, dt = self._current_period_dates()
        self.period_changed.emit(self._period_key, df, dt)

    def _period_key_from_combo(self) -> str:
        m = {0: "today", 1: "mtd", 2: "last7", 3: "custom"}
        return m.get(self.cmb_period.currentIndex(), "today")

    def _toggle_custom_dates(self, on: bool) -> None:
        self.ed_from.setVisible(on)
        self.ed_to.setVisible(on)
        self.btn_apply_period.setVisible(True if on else False)

    def _set_dates_for_key(self, key: str) -> None:
        today = QDate.currentDate()
        if key == "today":
            df = dt = today
        elif key == "mtd":
            df = QDate(today.year(), today.month(), 1)
            dt = today
        elif key == "last7":
            df = today.addDays(-6)  # include today → 7 days window
            dt = today
        else:  # custom: keep current edits
            return
        self.ed_from.setDate(df)
        self.ed_to.setDate(dt)

    def _current_period_dates(self) -> Tuple[str, str]:
        df = self.ed_from.date().toString("yyyy-MM-dd")
        dt = self.ed_to.date().toString("yyyy-MM-dd")
        return df, dt

    # ---------------- Public setters for controller ----------------
    def set_kpi_value(self, key: str, value: float | int, caption: Optional[str] = None) -> None:
        card = self._kpi_cards.get(key)
        if not card:
            return
        if isinstance(value, int) and key == "low_stock":
            card.set_value(str(int(value)))
        else:
            card.set_value(_money(value))
        if caption is not None:
            card.set_caption(caption)

    def set_top_products(self, rows: List[Dict[str, object]]) -> None:
        self.model_top_products.removeRows(0, self.model_top_products.rowCount())
        for r in rows:
            self.model_top_products.appendRow([
                QStandardItem(str(r.get("product_name", ""))),
                QStandardItem(f"{float(r.get('qty_base') or 0.0):,.2f}"),
                QStandardItem(_money(r.get("revenue")))
            ])
        self.tbl_top_products.resizeColumnsToContents()

    def set_quotations(self, rows: List[Dict[str, object]]) -> None:
        self.model_quot.removeRows(0, self.model_quot.rowCount())
        for r in rows:
            self.model_quot.appendRow([
                QStandardItem(str(r.get("sale_id", ""))),
                QStandardItem(str(r.get("customer_name", ""))),
                QStandardItem(str(r.get("expiry_date", "") or "")),
                QStandardItem(_money(r.get("amount")))
            ])
        self.tbl_quotations.resizeColumnsToContents()

    def set_period_from_to(self, date_from: str, date_to: str) -> None:
        y1, m1, d1 = (int(x) for x in date_from.split("-"))
        y2, m2, d2 = (int(x) for x in date_to.split("-"))
        self.cmb_period.setCurrentIndex(3)  # Custom
        self._period_key = "custom"
        self._toggle_custom_dates(True)
        self.ed_from.setDate(QDate(y1, m1, d1))
        self.ed_to.setDate(QDate(y2, m2, d2))

    # --------------- Layout: responsive KPI grid ---------------
    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reflow_kpis()

    def _reflow_kpis(self) -> None:
        # Remove existing items first
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        # Decide cols based on width: 3 on wide, 2 otherwise
        cols = 3 if self.width() >= 1100 else 2
        idx = 0
        for key in [
            "total_sales",
            "gross_profit",
            "net_profit",
            "receipts_cleared",
            "vendor_payments_cleared",
            "open_receivables",
            "open_payables",
            "low_stock",
        ]:
            card = self._kpi_cards.get(key)
            if not card:
                continue
            r = idx // cols
            c = idx % cols
            self.grid.addWidget(card, r, c)
            idx += 1

    # --------------- Small helpers ---------------
    def _prep_simple_table(self, tv: QTableView, headers: List[str]) -> None:
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.NoSelection)
        tv.verticalHeader().setVisible(False)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)


# ======================= Visual building blocks =======================

class KPICard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, caption: str) -> None:
        super().__init__()
        self.setObjectName("kpi_card")
        self.setStyleSheet("""
            QFrame#kpi_card {
                border: 1px solid #e1e1e1;
                border-radius: 10px;
                background: #fff;
            }
            QLabel.kpi-title {
                color: #444;
            }
            QLabel.kpi-caption {
                color: #777;
            }
        """)
        self.setCursor(Qt.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(2)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("kpi_title")
        self.lbl_title.setProperty("class", "kpi-title")
        self.lbl_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        f = self.lbl_title.font()
        f.setBold(True)
        self.lbl_title.setFont(f)

        self.lbl_value = QLabel("—")
        self.lbl_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        fv = QFont(self.lbl_value.font())
        fv.setPointSize(fv.pointSize() + 6)
        fv.setBold(True)
        self.lbl_value.setFont(fv)

        self.lbl_caption = QLabel(caption)
        self.lbl_caption.setProperty("class", "kpi-caption")
        self.lbl_caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        v.addWidget(self.lbl_title)
        v.addWidget(self.lbl_value)
        v.addWidget(self.lbl_caption)

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def set_value(self, s: str) -> None:
        self.lbl_value.setText(s)

    def set_caption(self, s: str) -> None:
        self.lbl_caption.setText(s)


class _Card(QWidget):
    """Wrap any widget in a titled card frame."""
    def __init__(self, inner: QWidget, title: str) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { border:1px solid #dcdcdc; border-radius:8px; }")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 10, 12, 12)
        fl.setSpacing(6)
        lbl = QLabel(f"<b>{title}</b>")
        fl.addWidget(lbl)
        fl.addWidget(inner)
        v.addWidget(frame)
