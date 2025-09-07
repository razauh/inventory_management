from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)


def _money(val: Optional[float]) -> str:
    try:
        return f"{float(val or 0.0):,.2f}"
    except Exception:
        return "0.00"


class FinancialOverviewWidget(QWidget):
    """
    Left:  P&L mini (Sales, COGS, Expenses, Net)
    Right: AR/AP capsules and Low-Stock pill with a 'View' button.

    Controller should call:
        set_pl(sales, cogs, expenses, net)
        set_ar_ap(ar, ap)
        set_low_stock_count(n)
    and connect to:
        view_low_stock_requested
        ar_drilldown_requested
        ap_drilldown_requested
    """
    view_low_stock_requested = Signal()
    ar_drilldown_requested = Signal()
    ap_drilldown_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        card = lambda: _CardFrame()

        # Left: P&L strip
        pnl = card()
        l = QVBoxLayout(pnl)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(6)
        title = _SectionTitle("P&L")
        self.lbl_sales = _MetricRow("Sales")
        self.lbl_cogs = _MetricRow("COGS")
        self.lbl_exp = _MetricRow("Expenses")
        self.lbl_net = _MetricRow("Net Profit")
        l.addWidget(title)
        l.addWidget(self.lbl_sales)
        l.addWidget(self.lbl_cogs)
        l.addWidget(self.lbl_exp)
        l.addWidget(_Separator())
        l.addWidget(self.lbl_net)

        # Right: AR/AP + Low Stock
        right = card()
        r = QVBoxLayout(right)
        r.setContentsMargins(12, 10, 12, 10)
        r.setSpacing(8)
        r.addWidget(_SectionTitle("Health"))

        # AR/AP rows are clickable labels + values
        arrow = _ClickableRow("Open Receivables")
        arrow.clicked.connect(self.ar_drilldown_requested)
        self.lbl_ar = arrow.value_label

        aprow = _ClickableRow("Open Payables")
        aprow.clicked.connect(self.ap_drilldown_requested)
        self.lbl_ap = aprow.value_label

        # Low stock pill + button
        lowwrap = QWidget()
        lowh = QHBoxLayout(lowwrap)
        lowh.setContentsMargins(0, 0, 0, 0)
        lowh.setSpacing(8)
        self.lbl_low = _Pill("Low stock: 0")
        btn_view_low = QPushButton("View")
        btn_view_low.clicked.connect(self.view_low_stock_requested)
        btn_view_low.setFixedHeight(26)
        lowh.addWidget(self.lbl_low, 0, Qt.AlignLeft)
        lowh.addStretch(1)
        lowh.addWidget(btn_view_low, 0, Qt.AlignRight)

        r.addWidget(arrow)
        r.addWidget(aprow)
        r.addWidget(lowwrap)

        root.addWidget(pnl, 1)
        root.addWidget(right, 1)

        # Make it height-friendly
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # -------------- Public setters --------------
    def set_pl(self, sales: float, cogs: float, expenses: float, net: float) -> None:
        self.lbl_sales.set_value(_money(sales))
        self.lbl_cogs.set_value(_money(cogs))
        self.lbl_exp.set_value(_money(expenses))
        self.lbl_net.set_value(_money(net))

    def set_ar_ap(self, ar: float, ap: float) -> None:
        self.lbl_ar.setText(_money(ar))
        self.lbl_ap.setText(_money(ap))

    def set_low_stock_count(self, n: int) -> None:
        n = int(n or 0)
        self.lbl_low.setText(f"Low stock: {n}")


# ---------------------- Small building blocks ----------------------

class _CardFrame(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setProperty("class", "card")
        self.setStyleSheet("""
            QFrame#card {
                border: 1px solid #dcdcdc;
                border-radius: 8px;
                background: #ffffff;
            }
        """)


class _SectionTitle(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(f"<b>{text}</b>")
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)


class _Separator(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)


class _MetricRow(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.lbl = QLabel(label)
        self.val = QLabel("0.00")
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val.setMinimumWidth(120)
        h.addWidget(self.lbl, 1)
        h.addWidget(self.val, 0)

    def set_value(self, s: str) -> None:
        self.val.setText(s)


class _ClickableRow(QWidget):
    clicked = Signal()

    def __init__(self, label: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.link = QLabel(f"<a href='#'>{label}</a>")
        self.link.setTextFormat(Qt.RichText)
        self.link.linkActivated.connect(lambda *_: self.clicked.emit())
        self.value_label = QLabel("0.00")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setMinimumWidth(120)
        h.addWidget(self.link, 1)
        h.addWidget(self.value_label, 0)


class _Pill(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                padding: 4px 10px;
                border-radius: 999px;
                background: #f1f3f5;
                color: #333;
            }
        """)
