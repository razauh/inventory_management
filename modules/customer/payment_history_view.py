# inventory_management/modules/customer/payment_history_view.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import logging
import os
import tempfile
import time

from jinja2 import Template
from weasyprint import HTML
from importlib import resources as importlib_resources
from ...utils.invoice_preview import show_invoice_preview

try:
    # Per project standard: PySide6
    from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QDialog,
        QDialogButtonBox,
        QHeaderView,
        QLabel,
        QMessageBox,
        QTabWidget,
        QTableView,
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


# Keep strong references to open dialogs so they are not
# garbage-collected immediately when shown non-modally.
_OPEN_HISTORY_DIALOGS: List[QDialog] = []
_log = logging.getLogger(__name__)


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
    global _OPEN_HISTORY_DIALOGS

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        # Standalone mode: create the app and run a normal event loop.
        app = QApplication([])
        dlg = _CustomerHistoryDialog(customer_id=customer_id, history=history or {})
        dlg.show()
        _OPEN_HISTORY_DIALOGS.append(dlg)
        dlg.destroyed.connect(
            lambda _obj: _OPEN_HISTORY_DIALOGS.remove(dlg) if dlg in _OPEN_HISTORY_DIALOGS else None
        )
        app.exec()
    else:
        # In-app mode: just show the non-modal dialog, like other module windows.
        dlg = _CustomerHistoryDialog(customer_id=customer_id, history=history or {})
        dlg.show()
        _OPEN_HISTORY_DIALOGS.append(dlg)
        dlg.destroyed.connect(
            lambda _obj: _OPEN_HISTORY_DIALOGS.remove(dlg) if dlg in _OPEN_HISTORY_DIALOGS else None
        )


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
        # Enable full window controls (minimize, maximize, close) and allow
        # the dialog to be minimized like other main windows.
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.resize(980, 620)

        self._customer_id = customer_id
        self._history = history or {}
        summary = self._history.get("summary") or {}
        customer_name = summary.get("customer_name") or f"Customer #{customer_id}"
        self.setWindowTitle(_t(f"Customer History - {customer_name}"))

        outer = QVBoxLayout(self)

        # Header
        outer.addWidget(QLabel(_t(f"Customer: {customer_name} (ID {customer_id})")))
        self._hint = QLabel(_t("Read-only customer account history."))
        self._hint.setStyleSheet("color:#666;")
        outer.addWidget(self._hint)

        # Single-tab history view
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self._build_history_view(outer)

        # Footer buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        self.printButton = self.buttonBox.addButton(_t("Print Current View"), QDialogButtonBox.ActionRole)
        self.printButton.setEnabled(bool((self._history or {}).get("timeline")))
        self.buttonBox.rejected.connect(self.reject)
        self.buttonBox.accepted.connect(self.accept)  # not shown, but keeps symmetry
        outer.addWidget(self.buttonBox)

        self.printButton.clicked.connect(self._on_print_current_tab)

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

    @staticmethod
    def _calculate_net_position(summary: Dict[str, Any]) -> Tuple[float, float, float]:
        """
        Helper to compute (open_due, credit, net) from a summary dict.
        net = open_due - credit.
        """
        try:
            open_due = float(summary.get("open_due_sum") or 0.0)
        except Exception:
            open_due = 0.0
        try:
            credit = float(summary.get("credit_balance") or 0.0)
        except Exception:
            credit = 0.0
        net = open_due - credit
        return open_due, credit, net

    def _on_print_current_tab(self) -> None:
        """
        Render the currently selected tab to a landscape PDF.
        Table tabs (Sales / Payments / Timeline) are exported as full tables;
        the Summary tab is exported as a single-row overview table.
        """
        w = self.tabs.currentWidget()
        summary = (self._history or {}).get("summary") or {}
        open_due, credit, net = self._calculate_net_position(summary)
        if net > 0:
            total_label = "Total receivable from customer"
            total_amount = net
        elif net < 0:
            total_label = "Total payable to customer"
            total_amount = abs(net)
        else:
            total_label = "No balance (account settled)"
            total_amount = 0.0
        # Decide what to export based on tab type
        if isinstance(w, _TablePage):
            headers = w.headers
            rows = w.rows
            title = w.title or "History"
            pretty_header = w._pretty_header
            columns = self._build_column_meta(headers, rows, pretty_header)
        else:
            # Treat non-table tab as summary: flatten the overview dict
            overview = (self._history or {}).get("summary") or {}
            if not overview:
                return
            headers = list(overview.keys())
            rows = [overview]
            title = "Summary"

            def pretty_header(k: str) -> str:
                return _CustomerHistoryDialog._pretty_title(k)
            columns = self._build_column_meta(headers, rows, pretty_header)

        # Load template via package-safe loader
        try:
            tpl_str = importlib_resources.files(
                "inventory_management.resources.templates.invoices"
            ).joinpath("customer_history_table.html").read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, ModuleNotFoundError) as e:
            _log.error("Failed to load customer history template: %s", e, exc_info=True)
            QMessageBox.warning(self, _t("Cannot Print"), _t("The customer history print template could not be loaded."))
            return

        template = Template(tpl_str, autoescape=True)

        # Normalize rows to dicts and coerce numeric values for safe formatting
        numeric_cols = {
            "amount",
            "amount_effect",
            "balance",
            "balance_after",
            "open_due",
            "open_due_sum",
            "credit",
            "credit_balance",
            "total",
            "total_amount",
            "paid_amount",
            "remaining",
            "remaining_due",
            "advance_payment_applied",
            "quantity",
            "price",
        }
        norm_rows: list[dict] = []
        for r in rows or []:
            if isinstance(r, dict):
                row_dict = dict(r)
            else:
                try:
                    row_dict = dict(r)
                except Exception:
                    continue
            cleaned: dict = {}
            for k in headers:
                v = row_dict.get(k)
                if k == "kind":
                    cleaned[k] = _TablePage._fmt_kind(v)
                    continue
                # Coerce common numeric-looking values only for known numeric columns;
                # leave other fields (IDs, notes, etc.) as strings.
                try:
                    if isinstance(v, (int, float)):
                        cleaned[k] = v
                    elif isinstance(v, str) and v.strip() and k in numeric_cols:
                        # Best-effort numeric parse for known numeric columns only
                        cleaned[k] = float(v)
                    else:
                        cleaned[k] = v
                except Exception:
                    cleaned[k] = v
            norm_rows.append(cleaned)

        html = template.render(
            title=title,
            columns=columns,
            rows=norm_rows,
            customer_id=self._customer_id,
            customer_name=summary.get("customer_name", ""),
            total_label=total_label,
            total_amount=total_amount,
        )

        temp_root = tempfile.gettempdir()
        pdf_dir = os.path.join(temp_root, "inventory_customer_history_tabs")
        os.makedirs(pdf_dir, exist_ok=True)

        # cleanup old PDFs (>1 day)
        now = time.time()
        try:
            for name in os.listdir(pdf_dir):
                if not name.lower().endswith(".pdf"):
                    continue
                path = os.path.join(pdf_dir, name)
                try:
                    if now - os.path.getmtime(path) > 86400:
                        os.remove(path)
                except OSError:
                    continue
        except OSError:
            pass

        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title.lower() or "tab")
        file_path = os.path.join(pdf_dir, f"customer_{self._customer_id}_{safe_title}.pdf")

        # Validate the file path resides in the expected temp directory *before* writing.
        real_pdf_dir = os.path.realpath(pdf_dir)
        real_file_path = os.path.realpath(file_path)
        try:
            common = os.path.commonpath([real_pdf_dir, real_file_path])
        except Exception:
            common = ""
        if common != real_pdf_dir:
            _log.error("Refusing to open customer history PDF outside temp dir: %s", real_file_path)
            QMessageBox.warning(self, _t("Cannot Print"), _t("The customer history output path was rejected."))
            return

        try:
            HTML(string=html).write_pdf(file_path)
        except Exception as e:
            _log.error("Failed to render customer history PDF to %s: %s", file_path, e, exc_info=True)
            QMessageBox.warning(self, _t("Cannot Print"), _t("The customer history PDF could not be created."))
            return

        show_invoice_preview(self, real_file_path, f"Customer History {self._customer_id}")

    def _build_history_view(self, outer: QVBoxLayout) -> None:
        """
        Build a single 'bank-statement' style history tab that merges sales,
        payments, and advances from the timeline payload.
        """
        timeline = (self._history or {}).get("timeline") or []
        page = _TablePage(title=_t("History"), rows=timeline)
        self.tabs.addTab(page, _t("History"))
        if not timeline:
            self._hint.setText(_t("No customer account activity is available."))

        # Summary label at the bottom with net position
        summary = (self._history or {}).get("summary") or {}
        open_due, credit, net = self._calculate_net_position(summary)
        if net > 0:
            msg = f"Customer still owes you: {net:,.2f} (outstanding {open_due:,.2f}, customer credit {credit:,.2f})"
        elif net < 0:
            msg = f"You owe the customer: {abs(net):,.2f} (outstanding {open_due:,.2f}, customer credit {credit:,.2f})"
        else:
            msg = f"No balance (account settled; outstanding {open_due:,.2f}, customer credit {credit:,.2f})."
        self._summary_label = QLabel(msg)
        self._summary_label.setStyleSheet("color:#444; margin-top:6px;")
        outer.addWidget(self._summary_label)

    @staticmethod
    def _build_column_meta(
        headers: List[str],
        rows: List[Dict[str, Any]],
        pretty_header,
    ) -> List[Dict[str, Any]]:
        numeric_keys = {
            "amount",
            "amount_effect",
            "balance",
            "balance_after",
            "open_due",
            "open_due_sum",
            "credit",
            "credit_balance",
            "total",
            "total_amount",
            "paid_amount",
            "remaining",
            "remaining_due",
            "advance_payment_applied",
            "quantity",
            "price",
        }
        date_keys = {"date", "posted_at", "tx_date", "cleared_date", "deposited_date", "instrument_date"}
        columns: List[Dict[str, Any]] = []
        for key in headers:
            align = "left"
            numeric = False
            if key in numeric_keys:
                align = "right"
                numeric = True
            elif key in date_keys:
                align = "center"
            else:
                sample = next((row.get(key) for row in rows if row.get(key) not in (None, "")), None)
                if _is_number(sample):
                    align = "right"
                    numeric = True
                elif isinstance(sample, str) and _looks_like_date(sample):
                    align = "center"
            columns.append(
                {
                    "key": key,
                    "label": pretty_header(key),
                    "align": align,
                    "numeric": numeric,
                }
            )
        return columns

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
    Displays a list[dict] in a QTableView (read-only).
    Columns are inferred from union of keys in the first N rows.
    """

    def __init__(self, *, title: str, rows: List[Dict[str, Any]], sample_for_headers: int = 100) -> None:
        super().__init__(None)
        self.title = title
        self.rows = rows or []
        headers = list(_collect_headers(self.rows))
        self.headers = self._filter_headers_for_title(headers)
        self.header_labels = [self._pretty_header(h) for h in self.headers]
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        self.table = QTableView()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)

        self.model = _DictTableModel(self.rows, self.headers, self.header_labels, self)
        self.table.setModel(self.model)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        if len(self.rows) <= 250 and len(self.headers) <= 16:
            self.table.resizeColumnsToContents()

        lay.addWidget(self.table, 1)

        # Footer note
        hint = QLabel(_t("Tip: right-click anywhere to 'Resize Columns to Contents'."))
        hint.setStyleSheet("color:#666;")
        lay.addWidget(hint)

    def resize_columns(self) -> None:
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _filter_headers_for_title(self, headers: List[str]) -> List[str]:
        """
        Drop purely technical columns and noisy fields that aren't useful in
        the UI, based on the logical table (tab) title.
        """
        title = (self.title or "").strip().lower()

        # Global blacklist
        blacklist = {"created_by", "notes", "id", "", None}

        # Table-specific exclusions
        if title == "sales":
            # Drop diagnostic / very noisy fields and redundant identifiers
            blacklist.update(
                {
                    "items",
                    "header_vs_calc_delta",
                    "notes",
                    "customer_id",
                    "customer_name",
                    "source_type",
                    "source_id",
                }
            )
        elif title == "payments":
            blacklist.update({"created_by", "notes"})
        elif title in {"timeline", "history"}:
            # Items is an embedded list of sale lines; too verbose for the grid
            blacklist.update({"items"})

        return [h for h in headers if h not in blacklist]

    @staticmethod
    def _pretty_header(k: str) -> str:
        raw = k
        k = k.replace("_", " ").strip()
        # Special-case common semantic fields
        if raw == "kind":
            return "Type"
        return " ".join(w.upper() if w in {"id", "uid"} else (w.capitalize()) for w in k.split())

    @staticmethod
    def _fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    @staticmethod
    def _fmt_kind(v: Any) -> str:
        labels = {
            "sale": "Sale",
            "sale_return": "Sale Return",
            "receipt": "Payment",
            "refund": "Refund",
            "advance": "Customer Credit",
            "advance_applied": "Credit Applied",
        }
        return labels.get(v, "" if v is None else str(v))


class _DictTableModel(QAbstractTableModel):
    def __init__(
        self,
        rows: List[Dict[str, Any]],
        headers: List[str],
        header_labels: List[str],
        parent=None,
        *,
        chunk_size: int = 200,
    ) -> None:
        super().__init__(parent)
        self._rows = rows or []
        self._headers = headers or []
        self._header_labels = header_labels or []
        self._chunk_size = max(1, int(chunk_size))
        self._loaded_rows = min(len(self._rows), self._chunk_size)

    def rowCount(self, parent: QModelIndex = QModelIndex()):  # type: ignore[override]
        return 0 if parent.isValid() else self._loaded_rows

    def columnCount(self, parent: QModelIndex = QModelIndex()):  # type: ignore[override]
        return 0 if parent.isValid() else len(self._headers)

    def canFetchMore(self, parent: QModelIndex = QModelIndex()):  # type: ignore[override]
        return not parent.isValid() and self._loaded_rows < len(self._rows)

    def fetchMore(self, parent: QModelIndex = QModelIndex()):  # type: ignore[override]
        if parent.isValid() or self._loaded_rows >= len(self._rows):
            return
        remaining = len(self._rows) - self._loaded_rows
        take = min(self._chunk_size, remaining)
        first = self._loaded_rows
        last = first + take - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._loaded_rows += take
        self.endInsertRows()

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._header_labels):
                return self._header_labels[section]
            return ""
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self._headers[index.column()]
        val = row.get(key, "")

        if role == Qt.DisplayRole:
            if key == "kind":
                return _TablePage._fmt_kind(val)
            if key == "clearing_state":
                return str(val or "").replace("_", " ").title()
            return _TablePage._fmt(val)

        if role == Qt.TextAlignmentRole:
            if _is_number(val):
                return Qt.AlignRight | Qt.AlignVCenter
            if _looks_like_date(str(val)):
                return Qt.AlignHCenter | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None


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
