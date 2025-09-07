# inventory_management/modules/dashboard/payment_summary_widget.py
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel, QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QTableView,
    QHeaderView, QAbstractItemView, QSizePolicy
)

# If your app ships a custom TableView, you can swap it here if needed.
try:
    from ..widgets.table_view import TableView as _BaseTableView  # type: ignore
except Exception:  # pragma: no cover
    _BaseTableView = QTableView


def _money(val: Optional[float]) -> str:
    try:
        return f"{float(val or 0.0):,.2f}"
    except Exception:
        return "0.00"


_COLS = ["Method", "Posted", "Pending", "Cleared", "Bounced", "Total"]
_STATES = ("posted", "pending", "cleared", "bounced")


class PaymentSummaryWidget(QWidget):
    """
    Two side-by-side pivot tables:

        Incoming (Sales payments)   |   Outgoing (Purchase payments)

    Columns per table:
        Method | Posted | Pending | Cleared | Bounced | Total

    Controller API:
        set_sales_breakdown(rows)
        set_purchase_breakdown(rows)

    Where each `rows` is: list of dicts like
        { "method": "Bank Transfer", "clearing_state": "cleared", "amount": 123.45 }

    Signals (optional, for drilldowns on click):
        cell_drilldown(kind: str, method: str, state: str)  # kind ∈ {"incoming","outgoing"}, state ∈ {"posted","pending","cleared","bounced","total"}
    """
    cell_drilldown = Signal(str, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # Incoming (sales payments)
        self.tbl_incoming = _BaseTableView()
        self.model_incoming = self._prep_table(self.tbl_incoming)
        incoming_card = self._wrap_card("Incoming (Sales Payments)", self.tbl_incoming)

        # Outgoing (purchase payments)
        self.tbl_outgoing = _BaseTableView()
        self.model_outgoing = self._prep_table(self.tbl_outgoing)
        outgoing_card = self._wrap_card("Outgoing (Purchase Payments)", self.tbl_outgoing)

        root.addWidget(incoming_card, 1)
        root.addWidget(outgoing_card, 1)

        # Click -> drilldown
        self.tbl_incoming.clicked.connect(lambda idx: self._emit_drilldown("incoming", self.tbl_incoming, idx))
        self.tbl_outgoing.clicked.connect(lambda idx: self._emit_drilldown("outgoing", self.tbl_outgoing, idx))

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def _wrap_card(self, title: str, inner: QWidget) -> QWidget:
        outer = QFrame()
        outer.setFrameShape(QFrame.StyledPanel)
        outer.setStyleSheet("QFrame { border:1px solid #dcdcdc; border-radius:8px; }")
        v = QVBoxLayout(outer)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(6)
        v.addWidget(QLabel(f"<b>{title}</b>"))
        v.addWidget(inner)
        return outer

    def _prep_table(self, tv: QTableView) -> QStandardItemModel:
        model = QStandardItemModel(0, len(_COLS))
        model.setHorizontalHeaderLabels(_COLS)

        tv.setModel(model)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SingleSelection)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.verticalHeader().setVisible(False)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        return model

    # ---------------- Controller-facing API ----------------

    def set_sales_breakdown(self, rows: List[Dict[str, object]]) -> None:
        """
        rows: [{method, clearing_state, amount}, ...] for SALE payments
        """
        pivot = self._pivot(rows)
        self._fill_model(self.model_incoming, pivot)

    def set_purchase_breakdown(self, rows: List[Dict[str, object]]) -> None:
        """
        rows: [{method, clearing_state, amount}, ...] for PURCHASE payments
        """
        pivot = self._pivot(rows)
        self._fill_model(self.model_outgoing, pivot)

    # ---------------- Data shaping ----------------

    def _pivot(self, rows: Iterable[Dict[str, object]]) -> List[Tuple[str, Dict[str, float]]]:
        """
        Returns a list of (method, sums_by_state) with keys posted/pending/cleared/bounced/total.
        Sorted by method ascending; totals not included here (we add a footer later).
        """
        agg: Dict[str, Dict[str, float]] = {}
        for r in rows or []:
            method = str(r.get("method") or "—")
            state = str(r.get("clearing_state") or "").lower()
            amt = float(r.get("amount") or 0.0)
            if method not in agg:
                agg[method] = {s: 0.0 for s in _STATES}
                agg[method]["total"] = 0.0
            if state in _STATES:
                agg[method][state] += amt
            agg[method]["total"] += amt

        # Sort methods alphabetically, keep stability for "Cash"/"Bank Transfer"/etc.
        ordered = sorted(agg.items(), key=lambda x: x[0].lower())
        return ordered

    def _fill_model(self, model: QStandardItemModel, pivot: List[Tuple[str, Dict[str, float]]]) -> None:
        model.removeRows(0, model.rowCount())
        # Body rows
        col_idx = {name: i for i, name in enumerate(_COLS)}
        totals = {s: 0.0 for s in list(_STATES) + ["total"]}

        for method, sums in pivot:
            row_items: List[QStandardItem] = []
            # Method
            it_method = QStandardItem(method)
            row_items.append(it_method)
            # Posted / Pending / Cleared / Bounced
            for state in _STATES:
                val = sums.get(state, 0.0)
                row_items.append(self._num_item(val))
                totals[state] += val
            # Total
            row_items.append(self._num_item(sums.get("total", 0.0)))
            totals["total"] += sums.get("total", 0.0)

            model.appendRow(row_items)

        # Footer (totals)
        if pivot:
            footer = [QStandardItem("Total")]
            fnt = QFont()
            fnt.setBold(True)
            footer[0].setFont(fnt)

            for state in _STATES:
                it = self._num_item(totals[state])
                it.setFont(fnt)
                footer.append(it)
            it_total = self._num_item(totals["total"])
            it_total.setFont(fnt)
            footer.append(it_total)

            model.appendRow(footer)

        # Tweak alignments for entire column set after refill
        for r in range(model.rowCount()):
            for c in range(1, len(_COLS)):  # numeric columns
                idx = model.index(r, c)
                model.setData(idx, Qt.AlignRight | Qt.AlignVCenter, Qt.TextAlignmentRole)

    def _num_item(self, value: float) -> QStandardItem:
        it = QStandardItem(_money(value))
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    # ---------------- Drilldown emit ----------------

    def _emit_drilldown(self, kind: str, table: QTableView, index) -> None:
        """
        Emits (kind, method, state) when user clicks a cell.
        - method comes from column 0 of the clicked row
        - state based on column clicked; column 1..4 map to posted/pending/cleared/bounced
          column 5 maps to "total"
        Footer totals row will emit method="Total".
        """
        if not index.isValid():
            return
        row = index.row()
        col = index.column()

        model: QStandardItemModel = table.model()  # type: ignore
        method = model.index(row, 0).data() or ""
        if col == 0:
            state = "total"  # clicking method name → overall
        elif 1 <= col <= 4:
            state = _STATES[col - 1]
        else:
            state = "total"

        self.cell_drilldown.emit(kind, str(method), state)
