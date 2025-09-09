# inventory_management/modules/customer/payment_history_view.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    # Per project standard: PySide6
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QHeaderView,
        QLabel,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    raise


# -----------------------------
# i18n shim
# -----------------------------
def _t(s: str) -> str:
    return s


# -----------------------------
# Public API
# -----------------------------
def open_customer_history(*, customer_id: int, history: Dict[str, Any]) -> None:
    """
    Local, read-only window for customer payment/advance history.

    Parameters
    ----------
    customer_id : int
        Customer identifier (display-only).
    history : dict
        Payload produced by CustomerHistoryService.full_history(customer_id).
        This viewer is resilient: it will create one tab per key whose value is a list[dict],
        and render columns based on dict keys found.
    """
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    dlg = _CustomerHistoryDialog(customer_id=customer_id, history=history or {})
    dlg.exec()

    if owns_app:
        app.quit()


# -----------------------------
# Dialog
# -----------------------------
class _CustomerHistoryDialog(QDialog):
    """
    Thin, read-only viewer for history payloads.
    Creates tabs automatically for each list[dict] in the payload.
    """

    # Preferred tabs order (if present)
    _PREFERRED_ORDER = [
        "sale_payments",          # receipts/refunds against sales
        "customer_advances",      # advances ledger (grants/applies)
        "sales",                  # sales headers
        "invoices",               # any synonym your service might provide
        "receipts",               # alternate naming
        "refunds",
        "allocations",
        "summary",                # will be computed locally if present as dict/list
    ]

    def __init__(self, *, customer_id: int, history: Dict[str, Any]) -> None:
        super().__init__(None)
        self.setWindowTitle(_t(f"Customer History — #{customer_id}"))
        self.setModal(True)
        self.resize(980, 620)

        self._customer_id = customer_id
        self._history = history or {}

        outer = QVBoxLayout(self)

        # Header
        outer.addWidget(QLabel(_t(f"Customer ID: {customer_id}")))
        self._hint = QLabel(_t("Read-only view. Columns are inferred from data."))
        self._hint.setStyleSheet("color:#666;")
        outer.addWidget(self._hint)

        # Tabs
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Build tabs from history
        self._build_tabs_from_history()

        # Footer buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttonBox.rejected.connect(self.reject)
        self.buttonBox.accepted.connect(self.accept)  # not shown, but keeps symmetry
        outer.addWidget(self.buttonBox)

        # Context/header actions (optional light feature)
        self._add_header_actions()

    # ---- helpers ------------------------------------------------------------

    def _add_header_actions(self) -> None:
        # Add a "Resize Columns" action to quickly fit columns per tab
        act_resize = QAction(_t("Resize Columns to Contents"), self)
        act_resize.triggered.connect(self._resize_current_tab_columns)
        self.addAction(act_resize)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)

    def _resize_current_tab_columns(self) -> None:
        w = self.tabs.currentWidget()
        if isinstance(w, _TablePage):
            w.resize_columns()

    def _build_tabs_from_history(self) -> None:
        # Identify list[dict] entries and optional summaries
        tables: List[Tuple[str, List[Dict[str, Any]]]] = []
        extras: List[Tuple[str, Any]] = []

        for key, val in (self._history or {}).items():
            if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                tables.append((key, val))
            else:
                extras.append((key, val))

        # Sort tables: preferred keys first, then alphabetically
        def _sort_key(kv: Tuple[str, List[Dict[str, Any]]]) -> Tuple[int, str]:
            key = kv[0]
            try:
                pref_idx = self._PREFERRED_ORDER.index(key)
            except ValueError:
                pref_idx = len(self._PREFERRED_ORDER) + 1
            return (pref_idx, key.lower())

        tables.sort(key=_sort_key)

        # Create a tab for each table
        for key, rows in tables:
            title = self._pretty_title(key)
            page = _TablePage(title=title, rows=rows)
            self.tabs.addTab(page, title)

        # Add a summary tab if any basic stats are useful
        summary_widget = self._build_summary_widget(tables, extras)
        if summary_widget is not None:
            self.tabs.addTab(summary_widget, _t("Summary"))

        # If nothing tabbed, show a fallback message
        if self.tabs.count() == 0:
            empty = QWidget()
            lay = QVBoxLayout(empty)
            msg = QLabel(_t("No tabular history found to display."))
            msg.setAlignment(Qt.AlignCenter)
            lay.addWidget(msg)
            self.tabs.addTab(empty, _t("History"))

    def _build_summary_widget(
        self,
        tables: List[Tuple[str, List[Dict[str, Any]]]],
        extras: List[Tuple[str, Any]],
    ) -> Optional[QWidget]:
        """
        Very light summary: counts per table and presence of known keys.
        (Avoids making assumptions about sign conventions.)
        """
        if not tables and not extras:
            return None

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        # Counts per table
        if tables:
            lay.addWidget(QLabel("<b>" + _t("Sections") + "</b>"))
            for key, rows in tables:
                lay.addWidget(QLabel(f"• {self._pretty_title(key)} — {len(rows)} {_t('row(s)')}"))

        # Known fields presence (helps debugging payload shape)
        known_sets = []
        for key, rows in tables:
            headers = _collect_headers(rows)
            # show up to 10 headers to keep it compact
            sample = ", ".join(list(headers)[:10])
            known_sets.append(f"{self._pretty_title(key)}: {sample}")
        if known_sets:
            lay.addSpacing(8)
            lay.addWidget(QLabel("<b>" + _t("Detected Columns") + "</b>"))
            for line in known_sets:
                lab = QLabel(line)
                lab.setStyleSheet("color:#666;")
                lay.addWidget(lab)

        lay.addStretch(1)
        return w

    @staticmethod
    def _pretty_title(key: str) -> str:
        k = key.replace("_", " ").strip()
        # Title case but keep common acronyms sensible
        k = " ".join(w.upper() if w in {"id", "uid"} else (w.capitalize()) for w in k.split())
        return k


# -----------------------------
# Table Page
# -----------------------------
class _TablePage(QWidget):
    """
    Displays a list[dict] in a QTableWidget (read-only).
    Columns are inferred from union of keys in the first N rows.
    """

    def __init__(self, *, title: str, rows: List[Dict[str, Any]], sample_for_headers: int = 100) -> None:
        super().__init__(None)
        self._title = title
        self._rows = rows or []
        self._headers = list(_collect_headers(self._rows[:sample_for_headers]))
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        # Setup columns
        self.table.setColumnCount(len(self._headers))
        self.table.setHorizontalHeaderLabels([self._pretty_header(h) for h in self._headers])
        self._populate()

        # Sizing
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)

        lay.addWidget(self.table, 1)

        # Footer note
        hint = QLabel(_t("Tip: right-click anywhere to 'Resize Columns to Contents'."))
        hint.setStyleSheet("color:#666;")
        lay.addWidget(hint)

    def _populate(self) -> None:
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            for c, key in enumerate(self._headers):
                val = row.get(key, "")
                item = QTableWidgetItem(self._fmt(val))
                # Alignment: numeric → right, date-ish → center, text → left
                if _is_number(val):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif _looks_like_date(str(val)):
                    item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

    def resize_columns(self) -> None:
        self.table.resizeColumnsToContents()

    @staticmethod
    def _pretty_header(k: str) -> str:
        k = k.replace("_", " ").strip()
        return " ".join(w.upper() if w in {"id", "uid"} else (w.capitalize()) for w in k.split())

    @staticmethod
    def _fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)


# -----------------------------
# Utilities
# -----------------------------
def _collect_headers(rows: Iterable[Dict[str, Any]]) -> List[str]:
    headers: List[str] = []
    seen = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    return headers


def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except Exception:
        return False


def _looks_like_date(s: str) -> bool:
    # Very light heuristic: YYYY-MM-DD (10 chars) or similar; avoid strict parsing to keep it fast/safe
    s = s.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return True
    return False
