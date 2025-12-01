# inventory_management/modules/vendor/payment_history_view.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import logging
import os
import subprocess
import sys
import tempfile
import time
import threading

from jinja2 import Template
from weasyprint import HTML

try:
    # Project-standard UI stack
    from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QObject, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QTableView,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    raise


_log = logging.getLogger(__name__)


def _t(s: str) -> str:
    """i18n shim."""
    return s


# -----------------------------
# Minimal dict-backed table model
# -----------------------------
class _DictTableModel(QAbstractTableModel):
    """
    Simple model that takes a list[dict] and displays it as a table.
    Column order is determined by `columns` passed in; any missing values show as "".
    """

    def __init__(self, rows: List[Dict[str, Any]], columns: List[str], parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows = rows
        self._cols = columns

    # Qt model API
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._cols)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._cols[section]
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        row = self._rows[index.row()]
        key = self._cols[index.column()]
        val = row.get(key, "")
        if val is None:
            return ""
        # Format floats a bit nicer for display
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    # Helpers
    def at(self, r: int) -> Dict[str, Any]:
        return self._rows[r]

    def rows(self) -> List[Dict[str, Any]]:
        return self._rows

    def columns(self) -> List[str]:
        return self._cols


# -----------------------------
# Window
# -----------------------------
class _VendorHistoryDialog(QDialog):
    """
    Thin, read-only viewer for vendor payments/advances/statement rows.

    Expected `history` shape (flexible):
      - Preferred (statement-style, as produced by controller.build_vendor_statement):
        {
          "vendor_id": int,
          "period": {"from": "YYYY-MM-DD"|None, "to": "YYYY-MM-DD"|None},
          "opening_credit": float,
          "opening_payable": float,
          "rows": [
            {
              "date": "YYYY-MM-DD",
              "type": "Purchase"|"Cash Payment"|"Refund"|"Credit Note"|"Credit Applied",
              "doc_id": str|None,
              "reference": {... arbitrary keys ...},
              "amount_effect": float,
              "balance_after": float
            },
            ...
          ],
          "totals": {...},
          "closing_balance": float
        }

      - Also tolerates a simpler payload with lists like history.get("payments"), history.get("advances").
        Those will be concatenated for display after a best-effort flatten.
    """

    def __init__(self, *, vendor_id: int, history: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_t(f"Vendor History — #{vendor_id}"))
        self.resize(960, 560)

        self._vendor_id = int(vendor_id)
        self._history = history or {}
        self._print_in_progress: bool = False
        self._print_lock = threading.Lock()

        outer = QVBoxLayout(self)

        # Header: period & headline numbers if present
        header = QWidget(self)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(0, 0, 0, 0)

        period = self._history.get("period") or {}
        p_from = period.get("from")
        p_to = period.get("to")
        period_txt = _t("All Dates")
        if p_from or p_to:
            if not p_from:
                period_txt = _t(f"… to {p_to}")
            elif not p_to:
                period_txt = _t(f"{p_from} to …")
            else:
                period_txt = _t(f"{p_from} to {p_to}")

        opening_payable = self._safe_float(self._history.get("opening_payable"))
        opening_credit = self._safe_float(self._history.get("opening_credit"))
        closing_balance = self._safe_float(self._history.get("closing_balance"))

        lbl_period = QLabel(_t(f"Period: {period_txt}"))
        lbl_open = QLabel(_t(f"Opening Payable: {opening_payable:.2f}    Opening Credit: {opening_credit:.2f}"))
        lbl_close = QLabel(_t(f"Closing Balance: {closing_balance:.2f}") if closing_balance is not None else "")

        for w in (lbl_period, lbl_open, lbl_close):
            w.setStyleSheet("color: #444;")
            hbox.addWidget(w)
        hbox.addStretch(1)
        outer.addWidget(header)

        # Tabs
        tabs = QTabWidget(self)
        outer.addWidget(tabs, 1)

        # Transactions tab (statement rows if available, else merged fallback)
        tx_rows = self._build_tx_rows(self._history)
        tx_columns = self._choose_tx_columns(tx_rows)

        tx_table = QTableView(self)
        tx_model = _DictTableModel(tx_rows, tx_columns, self)
        tx_table.setModel(tx_model)
        tx_table.setAlternatingRowColors(True)
        tx_table.setSortingEnabled(True)
        tx_table.resizeColumnsToContents()

        tx_page = QWidget(self)
        tx_layout = QVBoxLayout(tx_page)
        tx_layout.addWidget(tx_table)
        tabs.addTab(tx_page, _t("Transactions"))

        # Store for printing
        self._tx_rows = tx_rows
        self._tx_columns = tx_columns

        # Totals tab if available
        totals = self._history.get("totals") or {}
        if totals:
            totals_rows, totals_cols = self._dict_to_rows_cols(totals)
            totals_table = QTableView(self)
            totals_model = _DictTableModel(totals_rows, totals_cols, self)
            totals_table.setModel(totals_model)
            totals_table.setAlternatingRowColors(True)
            totals_table.setSortingEnabled(True)
            totals_table.resizeColumnsToContents()

            totals_page = QWidget(self)
            t_layout = QVBoxLayout(totals_page)
            t_layout.addWidget(totals_table)
            tabs.addTab(totals_page, _t("Totals"))

        # Close / Print buttons
        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        self._print_btn = btns.addButton(_t("Print"), QDialogButtonBox.ActionRole)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        self._print_btn.clicked.connect(self._on_print)
        outer.addWidget(btns)

    # -----------------------------
    # Row building / flattening
    # -----------------------------
    def _build_tx_rows(self, history: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if isinstance(history.get("rows"), list):
            # Statement-style rows: flatten reference object
            for r in history["rows"]:
                base = {
                    "date": r.get("date"),
                    "type": r.get("type"),
                    "doc_id": r.get("doc_id"),
                    "amount_effect": self._safe_float(r.get("amount_effect")),
                    "balance_after": self._safe_float(r.get("balance_after")),
                }
                ref = r.get("reference") or {}
                flat = {**base, **self._flatten_reference(ref)}
                rows.append(flat)
            return rows

        # Fallback: merge payments & advances if present
        pays = history.get("payments") or []
        advs = history.get("advances") or []
        for p in pays:
            rows.append({
                "date": p.get("date"),
                "type": p.get("type") or "Cash Payment",
                "doc_id": p.get("purchase_id"),
                "amount_effect": -abs(self._safe_float(p.get("amount"), 0.0)),  # payments reduce payable
                "balance_after": None,
                **self._flatten_reference({
                    "payment_id": p.get("payment_id"),
                    "method": p.get("method"),
                    "instrument_no": p.get("instrument_no"),
                    "instrument_type": p.get("instrument_type"),
                    "bank_account_id": p.get("bank_account_id"),
                    "vendor_bank_account_id": p.get("vendor_bank_account_id"),
                    "ref_no": p.get("ref_no"),
                    "clearing_state": p.get("clearing_state"),
                }),
            })
        for a in advs:
            amt = self._safe_float(a.get("amount"), 0.0)
            src_type = (a.get("source_type") or "").lower()
            if src_type == "applied_to_purchase":
                rows.append({
                    "date": a.get("tx_date"),
                    "type": "Credit Applied",
                    "doc_id": a.get("source_id"),
                    "amount_effect": -abs(amt),
                    "balance_after": None,
                    "tx_id": a.get("tx_id"),
                })
            else:
                rows.append({
                    "date": a.get("tx_date"),
                    "type": "Credit Note",
                    "doc_id": a.get("source_id"),
                    "amount_effect": -amt,
                    "balance_after": None,
                    "tx_id": a.get("tx_id"),
                })
        return rows

    def _choose_tx_columns(self, rows: List[Dict[str, Any]]) -> List[str]:
        # Preferred column order; any extra keys appended at the end (stable)
        preferred = [
            "date",
            "type",
            "doc_id",
            "amount_effect",
            "balance_after",
            "payment_id",
            "method",
            "instrument_no",
            "instrument_type",
            "clearing_state",
            "ref_no",
            "bank_account_id",
            "vendor_bank_account_id",
            "tx_id",
        ]
        seen = {k for r in rows for k in r.keys()}
        cols = [c for c in preferred if c in seen]
        # Append any other discovered keys (deterministic order)
        extras = sorted(k for k in seen if k not in set(preferred))
        return cols + extras

    def _flatten_reference(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested `reference` dict into top-level displayable keys."""
        out: Dict[str, Any] = {}
        if not isinstance(ref, dict):
            return out
        for k, v in ref.items():
            out[str(k)] = v
        return out

    @staticmethod
    def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            if v is None:
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    def _dict_to_rows_cols(self, data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Convert a simple totals dict into rows/columns suitable for
        _DictTableModel. We use a single row with sorted keys so headers
        stay stable.
        """
        if not isinstance(data, dict):
            return [], []
        cols = sorted(data.keys())
        row = {k: data.get(k) for k in cols}
        return [row], cols

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _find_project_root(start_path: str) -> str:
        """
        Walk upward from the given path looking for a project root marker
        (pyproject.toml or setup.py). Fallback to PROJECT_ROOT env var or
        the original two-level dirname traversal if none is found.
        """
        cur = os.path.abspath(start_path)
        markers = ("pyproject.toml", "setup.py")
        while True:
            if any(os.path.isfile(os.path.join(cur, m)) for m in markers):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent

        env_root = os.environ.get("PROJECT_ROOT")
        if env_root and os.path.isdir(env_root):
            return os.path.abspath(env_root)

        # Fallback to previous behavior: two levels up from this file.
        return os.path.dirname(os.path.dirname(start_path))

    # -----------------------------
    # Printing
    # -----------------------------
    def _on_print(self) -> None:
        """Render the transactions table to a landscape PDF."""
        with self._print_lock:
            if self._print_in_progress:
                return
            self._print_in_progress = True

        app = QApplication.instance()
        if app is not None:
            try:
                app.setOverrideCursor(Qt.WaitCursor)
            except Exception:
                app = None

        rows = getattr(self, "_tx_rows", []) or []
        cols = getattr(self, "_tx_columns", []) or []
        if not rows or not cols:
            with self._print_lock:
                self._print_in_progress = False
            if app is not None:
                try:
                    app.restoreOverrideCursor()
                except Exception:
                    pass
            return

        closing = self._safe_float(self._history.get("closing_balance"), 0.0) or 0.0
        if closing > 0:
            total_label = "Total payable to vendor"
            total_amount = closing
        elif closing < 0:
            total_label = "Total receivable from vendor"
            total_amount = abs(closing)
        else:
            total_label = "No balance (account settled)"
            total_amount = 0.0

        def worker():
            try:
                # Load template using robust project-root resolution
                template_path = ""
                try:
                    here = os.path.abspath(os.path.dirname(__file__))
                    project_root = self._find_project_root(here)
                    template_path = os.path.join(
                        project_root, "resources", "templates", "invoices", "vendor_history_table.html"
                    )
                    with open(template_path, "r", encoding="utf-8") as f:
                        tpl = f.read()
                except (OSError, FileNotFoundError) as e:
                    _log.error(
                        "Failed to load vendor history template at %s: %s",
                        template_path or "<unknown>",
                        e,
                        exc_info=True,
                    )
                    # Fallback: minimal template that surfaces the error visibly
                    tpl_local = (
                        "<html><body><p>Failed to load vendor history template."
                        " See logs for details.</p></body></html>"
                    )
                else:
                    tpl_local = tpl

                template = Template(tpl_local, autoescape=True)

                # Normalize rows: ensure dicts and coerce numeric-like values
                numeric_cols = {
                    "amount_effect",
                    "balance_after",
                    "opening_credit",
                    "opening_payable",
                    "closing_balance",
                }
                norm_rows: List[Dict[str, Any]] = []
                for r in rows or []:
                    if isinstance(r, dict):
                        row_dict = dict(r)
                    else:
                        try:
                            row_dict = dict(r)
                        except Exception:
                            continue
                    cleaned: dict = {}
                    for k in cols:
                        v = row_dict.get(k)
                        try:
                            if isinstance(v, (int, float)):
                                cleaned[k] = v
                            elif isinstance(v, str) and v.strip() and k in numeric_cols:
                                # Best-effort numeric parse only for known numeric columns
                                cleaned[k] = float(v)
                            else:
                                cleaned[k] = v
                        except Exception:
                            cleaned[k] = v
                    norm_rows.append(cleaned)

                html = template.render(
                    title=f"Vendor History — #{self._vendor_id}",
                    keys=cols,
                    labels=cols,
                    rows=norm_rows,
                    vendor_id=self._vendor_id,
                    total_label=total_label,
                    total_amount=total_amount,
                )

                temp_root = tempfile.gettempdir()
                pdf_dir = os.path.join(temp_root, "inventory_vendor_history")
                os.makedirs(pdf_dir, exist_ok=True)

                # Clean up PDFs older than 1 day
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

                file_path = os.path.join(pdf_dir, f"vendor_{self._vendor_id}.pdf")
                try:
                    HTML(string=html).write_pdf(file_path)
                except Exception as e:
                    _log.error(
                        "Failed to render vendor history PDF to %s: %s",
                        file_path,
                        e,
                        exc_info=True,
                    )
                    return

                try:
                    if sys.platform.startswith("win"):
                        subprocess.run(
                            ["cmd", "/c", "start", "", file_path],
                            shell=False,
                            timeout=5,
                        )
                    elif sys.platform.startswith("darwin"):
                        subprocess.run(["open", file_path], timeout=5)
                    else:
                        subprocess.run(["xdg-open", file_path], timeout=5)
                except subprocess.TimeoutExpired:
                    _log.warning(
                        "Timed out while trying to open vendor history PDF: %s",
                        file_path,
                    )
                except Exception as e:
                    _log.warning(
                        "Failed to open vendor history PDF %s: %s", file_path, e
                    )
            finally:
                finish()

        def finish():
            def reset():
                with self._print_lock:
                    self._print_in_progress = False
                a = QApplication.instance()
                if a is not None:
                    try:
                        a.restoreOverrideCursor()
                    except Exception:
                        pass

            app_local = QApplication.instance()
            if app_local is not None:
                QTimer.singleShot(0, reset)
            else:
                with self._print_lock:
                    self._print_in_progress = False

        # Track the worker thread so we can join it on close.
        self._print_thread = threading.Thread(target=worker, daemon=False)
        self._print_thread.start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """
        Ensure any in-flight print thread has a chance to finish before closing.
        """
        try:
            th = getattr(self, "_print_thread", None)
            if th is not None and th.is_alive():
                th.join(timeout=2.0)
        except Exception:
            pass
        super().closeEvent(event)


# -----------------------------
# Public API
# -----------------------------
def open_vendor_history(*, vendor_id: int, history: Dict[str, Any]) -> None:
    """
    Open the vendor history window.

    Usage:
        payload = controller.build_vendor_statement(vendor_id, date_from, date_to)
        open_vendor_history(vendor_id=vid, history=payload)
    """
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    dlg = _VendorHistoryDialog(vendor_id=int(vendor_id), history=history)
    dlg.exec()

    if owns_app:
        app.quit()
