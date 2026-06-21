from PySide6.QtWidgets import QWidget, QApplication, QMessageBox
from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
import sqlite3
import re
import uuid
import logging

from ..base_module import BaseModule
from .view import SalesView
from .model import SalesTableModel
from .form import SaleForm
from .return_form import SaleReturnForm
from ...database.repositories.sales_repo import SalesRepo, SaleHeader, SaleItem
from ...database.repositories.sales_returns_helpers import get_returnable_quantities
from ...database.repositories.customers_repo import CustomersRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str, fmt_money
from ...utils.invoice_preview import show_invoice_preview
import os
import tempfile
import datetime
from PySide6.QtCore import QStandardPaths


_log = logging.getLogger(__name__)


class SalesStatusProxy(QSortFilterProxyModel):
    """
    Compatibility proxy for the sales table.

    Status filtering is handled by SalesRepo queries so changing status does
    not scan loaded rows on the UI thread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status_filter = "all"
        self._doc_type = "sale"

    def set_status_filter(self, status: str):
        self._status_filter = (status or "all").lower()

    def set_doc_type(self, doc_type: str):
        self._doc_type = (doc_type or "sale").lower()
        self.invalidate()

    def filterAcceptsRow(self, source_row, source_parent):
        return True


class SalesController(BaseModule):
    PAGE_SIZE = 100

    # CSS for PDF generation - shared between print and export methods
    _INVOICE_PDF_CSS = '''
        @page {
            margin: 10mm;
            size: A4;
        }
        body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
        }
        .page {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
        }
    '''

    # Default path for invoice templates - can be overridden via config
    INVOICE_TEMPLATE_PATH = "resources/templates/invoices/sale_invoice.html"

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        super().__init__()
        self.conn = conn
        self.user = current_user
        self.view = SalesView()
        try:
            # Allow details panel to request payment status changes
            self.view.details.paymentStatusChangeRequested.connect(
                self._on_payment_status_change_requested
            )
        except (AttributeError, TypeError) as exc:
            _log.warning("Sales details payment-status signal is unavailable: %s", exc)
        except Exception:
            _log.exception("Unexpected error wiring sales details payment-status signal")

        # Controller-level state
        self._doc_type: str = "sale"   # 'sale' | 'quotation' (mirrors view toggle)
        self._search_text: str = ""    # current server-side search string
        self._status_filter: str = "all"
        self.active_dialog = None      # Track active dialog for non-modal operation
        self._detail_summary_cache: dict[str, dict] = {}
        self._last_detail_key: tuple[str, str] | None = None
        self._table_initialized = False
        self._page_offset = 0
        self._total_sales = 0
        self._detail_request_token = 0

        # Repos using the shared connection
        self.repo = SalesRepo(conn)
        self.customers = CustomersRepo(conn)
        self.products = ProductsRepo(conn)

        # Optional repo for bank accounts (lazy import; safe if missing)
        self.bank_accounts = None
        try:
            from ...database.repositories.bank_accounts_repo import BankAccountsRepo  # type: ignore
            self.bank_accounts = BankAccountsRepo(conn)
        except ImportError as exc:
            _log.warning("Bank accounts repository is unavailable: %s", exc)
            self.bank_accounts = None
        except Exception:
            _log.exception("Unexpected error creating bank accounts repository")
            self.bank_accounts = None

        # Path for path-based repos (payments/advances)
        self._db_path = self._get_db_path_from_conn(conn)

        self._search_timer = QTimer(self.view)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search_reload)
        self._detail_timer = QTimer(self.view)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(75)
        self._detail_timer.timeout.connect(self._run_deferred_detail_sync)

        self.base = SalesTableModel([], doc_type=self._doc_type)
        self.proxy = SalesStatusProxy(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.set_doc_type(self._doc_type)
        self.view.tbl.setModel(self.proxy)
        self.view.payments_tbl.setModel(self.proxy)
        sel = self.view.tbl.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_selection_changed)
        payment_sel = self.view.payments_tbl.selectionModel()
        if payment_sel is not None:
            payment_sel.selectionChanged.connect(self._sync_payment_tab_history)

        self._wire()
        self._reload()

    # ---- internals --------------------------------------------------------

    def _current_user_id(self) -> int | None:
        if not self.user:
            return None
        try:
            user_id = int(self.user.get("user_id"))
        except (TypeError, ValueError):
            return None
        row = self.conn.execute(
            "SELECT 1 FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return user_id if row else None

    @staticmethod
    def _get_db_path_from_conn(conn: sqlite3.Connection) -> str:
        """
        Returns the file path for the 'main' database of this connection.
        Falls back to ':memory:' if not available.
        """
        try:
            cur = conn.execute("PRAGMA database_list;")
            row = cur.fetchone()
            if row is not None:
                # row columns: seq, name, file
                file_path = row[2] if isinstance(row, tuple) else row["file"]
                return file_path or ":memory:"
        except sqlite3.Error:
            _log.exception("Could not read sales database path from connection")
        except (IndexError, KeyError, TypeError):
            _log.exception("Sales database path row has an unexpected shape")
        except Exception:
            _log.exception("Unexpected error reading sales database path")
        return ":memory:"

    def get_widget(self) -> QWidget:
        return self.view

    # ---- wiring / model ---------------------------------------------------

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.btn_return.clicked.connect(self._return)
        self.view.btn_return_all.clicked.connect(lambda: self._return(return_whole_order=True))

        # Server-side search: on change, refetch from repo
        self.view.search.textChanged.connect(self._on_search_changed)
        # Status filter (paid/unpaid/partial/all)
        if hasattr(self.view, "status_filter"):
            self.view.status_filter.currentIndexChanged.connect(self._on_status_filter_changed)
        if hasattr(self.view, "btn_clear_filters"):
            self.view.btn_clear_filters.clicked.connect(self._clear_filters)
        if hasattr(self.view, "btn_prev_page"):
            self.view.btn_prev_page.clicked.connect(self._prev_page)
        if hasattr(self.view, "btn_next_page"):
            self.view.btn_next_page.clicked.connect(self._next_page)

        if hasattr(self.view, "btn_record_payment"):
            self.view.btn_record_payment.clicked.connect(self._record_payment)
        if hasattr(self.view, "btn_print"):
            self.view.btn_print.clicked.connect(self._print)
        if hasattr(self.view, "btn_convert"):
            self.view.btn_convert.clicked.connect(self._convert_to_sale)
        # Apply Credit button (sales mode only)
        if hasattr(self.view, "btn_apply_credit"):
            self.view.btn_apply_credit.clicked.connect(self._on_apply_credit)

        # React to Sales|Quotations toggle → update controller state + reload
        if hasattr(self.view, "modeChanged"):
            self.view.modeChanged.connect(self._on_mode_changed)

        # initial action-state guard
        self._update_action_states()

    def _on_mode_changed(self, mode: str):
        mode = (mode or "sale").lower()
        self._doc_type = "quotation" if mode == "quotation" else "sale"
        self._status_filter = "all"
        self._page_offset = 0

        # Show a busy cursor while we rebuild potentially large models
        app = QApplication.instance()
        if app is not None:
            try:
                app.setOverrideCursor(Qt.WaitCursor)
            except Exception:
                app = None

        try:
            # Let the model update its headers for the new document type
            try:
                self.base.set_doc_type(self._doc_type)
            except Exception:
                pass
            # Let the details widget know (if it supports this)
            try:
                if hasattr(self.view, "details") and hasattr(self.view.details, "set_mode"):
                    self.view.details.set_mode(self._doc_type)
            except Exception:
                pass
            self._update_action_states()
            self._reload()
        finally:
            if app is not None:
                try:
                    app.restoreOverrideCursor()
                except Exception:
                    pass

    def _on_search_changed(self, text: str):
        self._search_text = text or ""
        self._search_timer.start()

    def _run_search_reload(self):
        self._page_offset = 0
        self._reload()

    def _on_status_filter_changed(self, _idx: int):
        # Read the current data value; fall back to label if needed.
        value = None
        try:
            value = self.view.status_filter.currentData()
        except Exception:
            try:
                value = self.view.status_filter.currentText()
            except Exception:
                value = "all"
        self._status_filter = str(value or "all").lower()
        self._page_offset = 0
        self._reload()

    def _clear_filters(self):
        self.view.search.blockSignals(True)
        self.view.search.clear()
        self.view.search.blockSignals(False)
        self.view.status_filter.blockSignals(True)
        all_index = self.view.status_filter.findData("all")
        self.view.status_filter.setCurrentIndex(max(0, all_index))
        self.view.status_filter.blockSignals(False)
        self._search_text = ""
        self._status_filter = "all"
        self._page_offset = 0
        self._search_timer.stop()
        self._reload()

    def _update_filter_summary(self):
        if not hasattr(self.view, "lbl_filter_summary"):
            return

        visible_count = self.proxy.rowCount() if hasattr(self, "proxy") else 0
        total_count = int(self._total_sales or 0)
        mode_label = "quotations" if self._doc_type == "quotation" else "sales"
        search_text = self._search_text.strip()
        status_text = ""
        try:
            if self._status_filter != "all":
                status_text = self.view.status_filter.currentText()
        except Exception:
            status_text = self._status_filter.title()

        filters = []
        if search_text:
            filters.append(f'Search: "{search_text}"')
        if status_text:
            filters.append(f"Status: {status_text}")

        if total_count == 0:
            if filters:
                message = f"No {mode_label} match. Active filters: " + " | ".join(filters)
                style = "color: #a22; font-weight: bold;"
            else:
                message = f"No {mode_label} available."
                style = "color: #555555;"
        elif filters:
            message = (
                f"Showing {visible_count} of {total_count} {mode_label}. "
                "Active filters: " + " | ".join(filters)
            )
            style = "color: #555555;"
        else:
            message = f"Showing {visible_count} of {total_count} {mode_label}."
            style = "color: #555555;"

        self.view.lbl_filter_summary.setText(message)
        self.view.lbl_filter_summary.setStyleSheet(style)
        if hasattr(self.view, "btn_clear_filters"):
            self.view.btn_clear_filters.setEnabled(bool(filters))

    def _on_selection_changed(self, *_):
        # Enable/disable buttons then refresh details
        self._update_action_states()
        self._schedule_details_update()

    def _update_action_states(self, detail_payload: dict | None = None):
        """Guard toolbar buttons by selection and mode."""
        row = self._selected_row()
        selected = row is not None

        # Always available
        if hasattr(self.view, "btn_edit"):
            self.view.btn_edit.setEnabled(selected)
        if hasattr(self.view, "btn_print"):
            self.view.btn_print.setEnabled(selected)

        # Sales-only actions
        allow_sales = (self._doc_type == "sale") and selected
        return_allowed = False
        return_message = "Select a sale to check return eligibility."
        if allow_sales and detail_payload is None:
            return_message = "Return eligibility loading."
        elif allow_sales:
            return_allowed, return_message = self._return_action_from_detail(detail_payload)
        if hasattr(self.view, "btn_return"):
            self.view.btn_return.setEnabled(return_allowed)
            self.view.btn_return.setToolTip(return_message)
        if hasattr(self.view, "btn_return_all"):
            self.view.btn_return_all.setEnabled(return_allowed)
            self.view.btn_return_all.setToolTip(return_message)
        if hasattr(self.view, "lbl_return_eligibility"):
            self.view.lbl_return_eligibility.setText(return_message)
        payment_allowed = False
        payment_message = "Select a sale to record payment."
        credit_allowed = False
        credit_message = "Select a sale to apply credit."
        if allow_sales and detail_payload is None:
            payment_message = "Payment status loading."
            credit_message = "Customer credit loading."
        elif allow_sales:
            (
                payment_allowed,
                payment_message,
                credit_allowed,
                credit_message,
            ) = self._financial_action_from_detail(detail_payload)
        if hasattr(self.view, "btn_record_payment"):
            self.view.btn_record_payment.setEnabled(payment_allowed)
            self.view.btn_record_payment.setToolTip(payment_message)
        if hasattr(self.view, "btn_apply_credit"):
            self.view.btn_apply_credit.setEnabled(credit_allowed)
            self.view.btn_apply_credit.setToolTip(credit_message)

        # Quotation-only action
        allow_convert = False
        if (self._doc_type == "quotation") and selected:
            if row and row.get("quotation_status") in ("draft", "sent"):
                allow_convert = True

        if hasattr(self.view, "btn_convert"):
            self.view.btn_convert.setEnabled(allow_convert)

    def _return_action_from_detail(self, detail_payload: dict | None) -> tuple[bool, str]:
        if self._doc_type != "sale":
            return False, "Returns apply to sales only."
        if not detail_payload:
            return False, "Select a sale to check return eligibility."
        returnable_lines = int(detail_payload.get("returnable_lines") or 0)
        if returnable_lines <= 0:
            return False, "Return unavailable: sale is fully returned."
        noun = "item" if returnable_lines == 1 else "items"
        return True, f"Return available: {returnable_lines} {noun} remaining."

    def _financial_action_from_detail(
        self, detail_payload: dict | None
    ) -> tuple[bool, str, bool, str]:
        if self._doc_type != "sale":
            return (
                False,
                "Payments apply to sales only.",
                False,
                "Customer credit applies to sales only.",
            )
        if not detail_payload:
            return (
                False,
                "Select a sale to record payment.",
                False,
                "Select a sale to apply credit.",
            )

        returned_value = float(detail_payload.get("returned_value") or 0.0)
        returnable_lines = int(detail_payload.get("returnable_lines") or 0)
        if returned_value > 1e-9 and returnable_lines <= 0:
            return (
                False,
                "Payment unavailable: sale is fully returned.",
                False,
                "Apply Credit unavailable: sale is fully returned.",
            )

        remaining = float(detail_payload.get("remaining_due") or 0.0)
        if remaining <= 1e-9:
            return (
                False,
                "Payment unavailable: sale is fully settled.",
                False,
                "Apply Credit unavailable: sale is fully settled.",
            )

        payment_message = f"Payment available: {fmt_money(remaining)} due."
        customer_id = int(detail_payload.get("customer_id") or 0)
        if not customer_id:
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer information is missing.",
            )
        credit = detail_payload.get("customer_credit_balance")
        if credit is None:
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer credit could not be checked.",
            )
        credit_amount = float(credit or 0.0)
        if credit_amount <= 1e-9:
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer has no available credit.",
            )
        applicable = min(remaining, credit_amount)
        return (
            True,
            payment_message,
            True,
            f"Apply Credit available: up to {fmt_money(applicable)}.",
        )

    def _return_eligibility(self, row: dict | None) -> tuple[bool, str]:
        if self._doc_type != "sale":
            return False, "Returns apply to sales only."
        if not row:
            return False, "Select a sale to check return eligibility."

        try:
            remaining = get_returnable_quantities(self.conn, row["sale_id"])
            returnable_lines = sum(
                1 for qty in remaining.values() if float(qty) > 1e-9
            )
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            _log.exception(
                "Could not check return eligibility for sale_id=%s",
                row.get("sale_id"),
            )
            return False, "Return unavailable: eligibility could not be checked."
        except Exception:
            _log.exception(
                "Unexpected error checking return eligibility for sale_id=%s",
                row.get("sale_id"),
            )
            return False, "Return unavailable: eligibility could not be checked."

        if returnable_lines == 0:
            return False, "Return unavailable: sale is fully returned."
        noun = "item" if returnable_lines == 1 else "items"
        return True, f"Return available: {returnable_lines} {noun} remaining."

    def _financial_action_eligibility(
        self, row: dict | None
    ) -> tuple[bool, str, bool, str]:
        if self._doc_type != "sale":
            return (
                False,
                "Payments apply to sales only.",
                False,
                "Customer credit applies to sales only.",
            )
        if not row:
            return (
                False,
                "Select a sale to record payment.",
                False,
                "Select a sale to apply credit.",
            )

        try:
            remaining = float(
                self._fetch_sale_financials(str(row["sale_id"]))["remaining_due"]
            )
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            _log.exception(
                "Could not check financial actions for sale_id=%s",
                row.get("sale_id"),
            )
            message = "Unavailable: sale balance could not be checked."
            return False, message, False, message
        except Exception:
            _log.exception(
                "Unexpected error checking financial actions for sale_id=%s",
                row.get("sale_id"),
            )
            message = "Unavailable: sale balance could not be checked."
            return False, message, False, message

        if remaining <= 1e-9:
            return (
                False,
                "Payment unavailable: sale is fully settled.",
                False,
                "Apply Credit unavailable: sale is fully settled.",
            )

        payment_message = f"Payment available: {fmt_money(remaining)} due."
        customer_id = int(row.get("customer_id") or 0)
        if not customer_id:
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer information is missing.",
            )

        try:
            from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo

            credit = float(CustomerAdvancesRepo(self.conn).get_balance(customer_id) or 0.0)
        except (ImportError, sqlite3.Error, TypeError, ValueError):
            _log.exception(
                "Could not check customer credit for customer_id=%s",
                customer_id,
            )
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer credit could not be checked.",
            )
        except Exception:
            _log.exception(
                "Unexpected error checking customer credit for customer_id=%s",
                customer_id,
            )
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer credit could not be checked.",
            )

        if credit <= 1e-9:
            return (
                True,
                payment_message,
                False,
                "Apply Credit unavailable: customer has no available credit.",
            )

        applicable = min(remaining, credit)
        return (
            True,
            payment_message,
            True,
            f"Apply Credit available: up to {fmt_money(applicable)}.",
        )

    def _build_model(self):
        """
        Build the table model using server-side search (preferred).
        Falls back to list_* if search API is unavailable.
        """
        try:
            if hasattr(self.repo, "count_sales"):
                self._total_sales = int(
                    self.repo.count_sales(
                        self._search_text,
                        doc_type=self._doc_type,
                        status=self._status_filter,
                    )
                )
            else:
                self._total_sales = 0
        except (TypeError, sqlite3.Error):
            _log.exception("Could not count sales for doc_type=%s", self._doc_type)
            self._total_sales = 0
        except Exception:
            _log.exception("Unexpected error counting sales for doc_type=%s", self._doc_type)
            self._total_sales = 0

        if self._page_offset >= self._total_sales:
            self._page_offset = max(
                0,
                ((self._total_sales - 1) // self.PAGE_SIZE) * self.PAGE_SIZE,
            )

        # Try repo.search_sales(query, doc_type=...)
        rows_to_use = None
        try:
            if hasattr(self.repo, "search_sales"):
                rows_to_use = list(
                    self.repo.search_sales(
                        self._search_text,
                        doc_type=self._doc_type,
                        status=self._status_filter,
                        limit=self.PAGE_SIZE,
                        offset=self._page_offset,
                    )
                )
        except TypeError:
            # some implementations might have different signature; try (query, doc_type) kw-agnostic
            try:
                rows_to_use = list(self.repo.search_sales(self._search_text, self._doc_type))
            except (TypeError, sqlite3.Error):
                _log.exception(
                    "Sales search fallback failed for doc_type=%s",
                    self._doc_type,
                )
                rows_to_use = None
            except Exception:
                _log.exception(
                    "Unexpected error in sales search fallback for doc_type=%s",
                    self._doc_type,
                )
                rows_to_use = None
        except sqlite3.Error:
            _log.exception("Sales search query failed for doc_type=%s", self._doc_type)
            rows_to_use = None
        except Exception:
            _log.exception("Unexpected error searching sales for doc_type=%s", self._doc_type)
            rows_to_use = None

        # Fallback behavior if search_sales is not available
        if rows_to_use is None:
            if self._doc_type == "quotation":
                try:
                    rows_to_use = list(
                        self.repo.list_quotations(
                            limit=self.PAGE_SIZE,
                            offset=self._page_offset,
                            status=self._status_filter,
                        )
                    )
                except sqlite3.Error:
                    _log.exception("Could not list quotations after sales search fallback")
                    rows_to_use = []
                except Exception:
                    _log.exception("Unexpected error listing quotations after sales search fallback")
                    rows_to_use = []
            else:
                rows_to_use = list(
                    self.repo.list_sales(
                        limit=self.PAGE_SIZE,
                        offset=self._page_offset,
                        status=self._status_filter,
                    )
                )

        if not self._total_sales:
            self._total_sales = len(rows_to_use)

        # Normalize quotations to keep table happy (no payments; show quotation_status or em dash)
        if self._doc_type == "quotation":
            norm = []
            for r in rows_to_use:
                d = dict(r)
                # Ensure all required fields exist for quotations
                d.setdefault("paid_amount", 0.0)
                d.setdefault("customer_id", 0)
                d.setdefault("order_discount", 0.0)
                d.setdefault("payment_status", "—")  # Default status for quotations
                qstat = d.get("quotation_status") or d.get("payment_status") or "—"
                d["payment_status"] = qstat
                norm.append(d)
            rows_to_use = norm

        self.base.set_doc_type(self._doc_type)
        self.base.replace(rows_to_use)
        self.proxy.set_doc_type(self._doc_type)
        if not self._table_initialized:
            self.view.tbl.resizeColumnsToContents()
            self.view.payments_tbl.resizeColumnsToContents()
            self._table_initialized = True
        self._sync_page_controls()

    def _prev_page(self):
        if self._page_offset <= 0:
            return
        self._page_offset = max(0, self._page_offset - self.PAGE_SIZE)
        self._reload()

    def _next_page(self):
        next_offset = self._page_offset + self.PAGE_SIZE
        if next_offset >= self._total_sales:
            return
        self._page_offset = next_offset
        self._reload()

    def _sync_page_controls(self):
        if not all(
            hasattr(self.view, attr)
            for attr in ("lbl_page", "btn_prev_page", "btn_next_page")
        ):
            return
        total_pages = max(1, (self._total_sales + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        current_page = min(total_pages, (self._page_offset // self.PAGE_SIZE) + 1)
        self.view.lbl_page.setText(f"Page {current_page} / {total_pages}")
        self.view.btn_prev_page.setEnabled(self._page_offset > 0)
        self.view.btn_next_page.setEnabled(
            self._page_offset + self.PAGE_SIZE < self._total_sales
        )

    def _reload(self):
        self._search_timer.stop()
        selected_sale_id = None
        selected_row = self._selected_row()
        if selected_row:
            selected_sale_id = str(selected_row.get("sale_id") or "")
        self._detail_summary_cache.clear()
        self._last_detail_key = None
        self._build_model()
        selected = False
        if selected_sale_id:
            selected = self._select_row_by_sale_id(selected_sale_id)
        if not selected and self.proxy.rowCount() > 0:
            self.view.tbl.selectRow(0)
            self.view.payments_tbl.selectRow(0)
            selected = True
        if not selected:
            self._update_action_states()
            self._sync_details(force=True)
        self._update_filter_summary()

    def _select_row_by_sale_id(self, sale_id: str) -> bool:
        if not sale_id:
            return False
        source_row = None
        try:
            if hasattr(self.base, "row_for_sale_id"):
                source_row = self.base.row_for_sale_id(sale_id)
        except Exception:
            source_row = None
        if source_row is None:
            return False
        source_index = self.base.index(int(source_row), 0)
        proxy_index = self.proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return False
        self.view.tbl.selectRow(proxy_index.row())
        payments_tbl = getattr(self.view, "payments_tbl", None)
        if payments_tbl is not None:
            payments_tbl.selectRow(proxy_index.row())
        try:
            self.view.tbl.scrollTo(proxy_index)
            if payments_tbl is not None:
                payments_tbl.scrollTo(proxy_index)
        except (AttributeError, RuntimeError):
            pass
        except Exception:
            _log.exception("Could not scroll restored sales selection into view")
        return True

    def _selected_row(self, table=None) -> dict | None:
        table = table or self.view.tbl
        try:
            idxs = table.selectionModel().selectedRows()
        except Exception:
            return None
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        row_data = self.base.at(src.row())

        # Convert to dict to ensure setdefault method is available
        if row_data:
            if not isinstance(row_data, dict):
                row_data = dict(row_data)
            row_data.setdefault("customer_id", 0)
            row_data.setdefault("date", "")
            row_data.setdefault("order_discount", 0.0)
            row_data.setdefault("total_amount", 0.0)

        return row_data

    def _sync_payment_tab_history(self, *args):
        row = self._selected_row(self.view.payments_tbl)
        if not row or self._doc_type != "sale":
            self.view.payments.set_rows([])
            return
        try:
            snapshot = self.repo.get_sale_detail_snapshot(str(row["sale_id"]))
            self.view.payments.set_rows(list(snapshot.get("payments") or []))
        except Exception:
            _log.exception(
                "Could not update sales payment tab for sale_id=%s",
                row.get("sale_id"),
            )
            self.view.payments.set_rows([])

    # --- small helper: fetch financials using calc view + header -----------
    def _fetch_sale_financials(self, sale_id: str) -> dict:
        """
        Returns a dict with:
          total_amount, paid_amount, advance_payment_applied,
          calculated_total_amount, remaining_due
        remaining_due = calculated_total_amount - paid_amount - advance_payment_applied (clamped ≥ 0)
        """
        summary = self._get_sale_detail_summary(sale_id)
        calc_total = float(summary.get("calculated_total_amount") or 0.0)
        paid = float(summary.get("paid_amount") or 0.0)
        adv = float(summary.get("advance_payment_applied") or 0.0)
        remaining = float(summary.get("remaining_due") or 0.0)
        return {
            "total_amount": float(summary.get("total_amount") or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "calculated_total_amount": calc_total,
            "remaining_due": remaining,
        }

    def _get_sale_detail_summary(self, sale_id: str) -> dict:
        if not hasattr(self, "_detail_summary_cache"):
            self._detail_summary_cache = {}
        cached = self._detail_summary_cache.get(str(sale_id))
        if cached is not None:
            return dict(cached)
        if not hasattr(self, "repo"):
            self.repo = SalesRepo(self.conn)
        summary = dict(self.repo.get_sale_detail_summary(str(sale_id)))
        self._detail_summary_cache[str(sale_id)] = dict(summary)
        return summary

    def _clear_detail_views(self):
        self.view.items.set_rows([])
        try:
            if hasattr(self.view, "payments"):
                self.view.payments.set_rows([])
        except (AttributeError, RuntimeError):
            _log.exception("Could not clear sales payments view")
        except Exception:
            _log.exception("Unexpected error clearing sales payments view")
        self.view.details.set_data(None)

    def _schedule_details_update(self, *, force: bool = False):
        self._detail_request_token += 1
        if force:
            self._sync_details_impl(force=True, token=self._detail_request_token)
            return
        self._detail_timer.start()

    def _run_deferred_detail_sync(self):
        self._sync_details_impl(token=self._detail_request_token)

    def _sync_details(self, *args, force: bool = False):
        token = None
        if args:
            token = args[0]
        return self._sync_details_impl(force=force, token=token)

    def _sync_details_impl(self, *, force: bool = False, token: int | None = None):
        if token is not None and token != self._detail_request_token:
            return
        r = self._selected_row()

        # default: nothing selected → clear subviews
        if not r:
            self._last_detail_key = None
            self._clear_detail_views()
            return

        detail_key = (self._doc_type, str(r.get("sale_id") or ""))
        if not force and detail_key == self._last_detail_key:
            return
        self._last_detail_key = detail_key

        try:
            if hasattr(self.repo, "get_sale_detail_snapshot"):
                snapshot = self.repo.get_sale_detail_snapshot(str(r["sale_id"]))
            else:
                snapshot = self._legacy_detail_snapshot(dict(r))
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            _log.exception("Could not load sales detail snapshot for sale_id=%s", r.get("sale_id"))
            self._last_detail_key = None
            self._clear_detail_views()
            self._update_action_states()
            return
        except Exception:
            _log.exception(
                "Unexpected error loading sales detail snapshot for sale_id=%s",
                r.get("sale_id"),
            )
            self._last_detail_key = None
            self._clear_detail_views()
            self._update_action_states()
            return

        if token is not None and token != self._detail_request_token:
            return

        detail_payload = self._detail_payload_from_snapshot(dict(r), snapshot)
        items = detail_payload.pop("_items", [])
        payments_rows = detail_payload.get("payments", [])

        self.view.items.set_rows(items)
        try:
            if hasattr(self.view, "payments"):
                self.view.payments.set_rows(payments_rows)
        except (AttributeError, RuntimeError):
            _log.exception("Could not update sales payments view")
        except Exception:
            _log.exception("Unexpected error updating sales payments view")

        try:
            if hasattr(self.view.details, "set_mode"):
                self.view.details.set_mode(self._doc_type)
        except (AttributeError, RuntimeError):
            _log.exception("Could not set sales details mode to %s", self._doc_type)
        except Exception:
            _log.exception("Unexpected error setting sales details mode to %s", self._doc_type)
        self.view.details.set_data(detail_payload)
        self._update_action_states(detail_payload)

    def _detail_payload_from_snapshot(self, selected_row: dict, snapshot: dict) -> dict:
        items = list(snapshot.get("items") or [])
        line_disc = sum(float(it["quantity"]) * float(it["item_discount"]) for it in items)
        header = dict(snapshot.get("header") or {})
        r = {**header, **selected_row}
        r["overall_discount"] = float(r.get("order_discount") or 0.0) + line_disc

        summary = dict(snapshot.get("summary") or {})
        r["returned_qty"] = float(summary.get("returned_qty", 0.0))
        r["returned_value"] = float(summary.get("returned_value", 0.0))
        r["gross_total_amount"] = float(
            summary.get("gross_total_amount", r.get("total_amount", 0.0))
        )
        r["net_total_amount"] = float(
            summary.get("net_total_amount", r.get("total_amount", 0.0))
        )
        payments_rows = list(snapshot.get("payments") or [])
        if self._doc_type == "sale":
            r["customer_credit_balance"] = snapshot.get("customer_credit_balance")
            r["returnable_lines"] = int(snapshot.get("returnable_lines") or 0)
            r["paid_amount"] = float(summary.get("paid_amount") or 0.0)
            r["advance_payment_applied"] = float(summary.get("advance_payment_applied") or 0.0)
            r["return_credit_amount"] = float(summary.get("return_credit_amount") or 0.0)
            r["calculated_total_amount"] = float(summary.get("calculated_total_amount") or 0.0)
            r["net_total_amount"] = r["calculated_total_amount"]
            r["paid_plus_credit"] = r["paid_amount"] + r["advance_payment_applied"]
            r["remaining_due"] = float(summary.get("remaining_due") or 0.0)
        else:
            payments_rows = []
            r.pop("customer_credit_balance", None)
            r["advance_payment_applied"] = 0.0
            r["paid_plus_credit"] = float(r.get("paid_amount") or 0.0)
            r["remaining_due"] = 0.0

        r["payments"] = payments_rows
        r["_items"] = items
        return r

    def _legacy_detail_snapshot(self, row: dict) -> dict:
        items = self.repo.list_items(row["sale_id"])
        summary = self._get_sale_detail_summary(str(row["sale_id"]))
        payments_rows: list[dict] = []
        customer_credit_balance = None
        returnable_lines = 0
        if self._doc_type == "sale":
            try:
                from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # type: ignore

                payments_rows = list(SalePaymentsRepo(self.conn).list_by_sale(row["sale_id"])) or []
            except (ImportError, sqlite3.Error):
                _log.exception("Could not load payments for sale_id=%s", row.get("sale_id"))
            try:
                from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo  # type: ignore

                customer_credit_balance = float(
                    CustomerAdvancesRepo(self.conn).get_balance(int(row.get("customer_id") or 0))
                    or 0.0
                )
            except (ImportError, sqlite3.Error, TypeError, ValueError):
                _log.exception("Could not load customer credit for sale_id=%s", row.get("sale_id"))
            try:
                remaining = get_returnable_quantities(self.conn, row["sale_id"])
                returnable_lines = sum(1 for qty in remaining.values() if float(qty) > 1e-9)
            except (sqlite3.Error, KeyError, TypeError, ValueError):
                _log.exception("Could not check return eligibility for sale_id=%s", row.get("sale_id"))
        return {
            "header": row,
            "items": [dict(item) for item in items],
            "summary": summary,
            "payments": [dict(payment) for payment in payments_rows],
            "customer_credit_balance": customer_credit_balance,
            "returnable_lines": returnable_lines,
        }

    # ---- helpers to open SaleForm with/without 'mode' ---------------------

    def _open_sale_form(self, *, initial: dict | None = None, as_quotation: bool = False) -> SaleForm | None:
        """
        Try to instantiate SaleForm with a few safe constructor variants.
        - If as_quotation=True, we first try passing mode='quotation', else fall back.
        - Keeps bank_accounts lazy path.
        Returns a dialog instance or None if all ctor attempts fail.
        """
        kwargs = {
            "customers": self.customers,
            "products": self.products,
            "sales_repo": self.repo,
            "db_path": self._db_path,
            "bank_accounts": self.bank_accounts,
            "can_view_margin": bool(
                self.user and str(self.user.get("role") or "").lower() == "admin"
            ),
        }
        if initial is not None:
            kwargs["initial"] = initial

        if as_quotation:
            # Prefer explicit mode kw first
            try:
                return SaleForm(self.view, **kwargs, mode="quotation")  # type: ignore[arg-type]
            except TypeError:
                pass

        # Fallback without mode kwarg
        try:
            return SaleForm(self.view, **kwargs)
        except TypeError:
            # Try progressively simpler ctor shapes
            try:
                kwargs2 = {"customers": self.customers, "products": self.products, "sales_repo": self.repo, "db_path": self._db_path}
                if initial is not None:
                    kwargs2["initial"] = initial
                return SaleForm(self.view, **kwargs2)
            except TypeError:
                try:
                    return SaleForm(self.view)
                except Exception:
                    return None

    # ---- local adapters for customer dialog/actions -----------------------

    def _list_company_bank_accounts(self) -> list[dict]:
        """
        Adapter used by payment dialogs. Returns list of {id, name} for
        active company bank accounts, mirroring the purchase controller.
        """
        try:
            rows: list[dict] = []
            # Preferred: use BankAccountsRepo, if available
            if self.bank_accounts and hasattr(self.bank_accounts, "list_company_bank_accounts"):
                rows = list(self.bank_accounts.list_company_bank_accounts())
            else:
                # Fallback: direct SQL, same shape purchase controller uses
                cur = self.conn.execute(
                    "SELECT account_id AS id, label AS name, bank_name, account_no "
                    "FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
                )
                rows = [dict(r) for r in cur.fetchall()]

            norm: list[dict] = []
            for r in rows or []:
                d = dict(r)
                _id = d.get("id") or d.get("account_id") or d.get("bank_account_id")
                display_parts = []
                for key in ("name", "account_name", "title", "account_title", "label"):
                    value = str(d.get(key) or "").strip()
                    if value:
                        display_parts.append(value)
                        break
                bank_name = str(d.get("bank_name") or "").strip()
                account_no = str(d.get("account_no") or "").strip()
                if bank_name:
                    display_parts.append(bank_name)
                if account_no:
                    display_parts.append(account_no)
                _name = " - ".join(display_parts)
                if _id is not None and _name:
                    norm.append({"id": int(_id), "name": str(_name)})
            return norm
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            _log.exception("Could not list company bank accounts for sales payment dialog")
            return []
        except Exception:
            _log.exception("Unexpected error listing company bank accounts for sales payment dialog")
            return []

    def _list_sales_for_customer(self, customer_id: int) -> list[dict]:
        """
        Adapter used by customer.money dialog. Shape: {sale_id, doc_no, date, total, paid}
        """
        # Prefer repo helper if exists
        try:
            if hasattr(self.repo, "list_sales_for_customer"):
                rows = list(self.repo.list_sales_for_customer(customer_id))
                out = []
                for r in rows:
                    d = dict(r)
                    out.append({
                        "sale_id": str(d.get("sale_id")),
                        "doc_no": str(d.get("sale_id")),
                        "date": str(d.get("date")),
                        "total": float(d.get("total_amount") or d.get("total") or 0.0),
                        "paid": float(d.get("paid_amount") or d.get("paid") or 0.0),
                        "advance_payment_applied": float(d.get("advance_payment_applied") or 0.0),
                        "remaining_due": float(d.get("remaining_due") or 0.0),
                    })
                return out
        except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError):
            _log.exception("Sales repository customer lookup failed for customer_id=%s", customer_id)
        except Exception:
            _log.exception("Unexpected sales repository customer lookup failure for customer_id=%s", customer_id)

        # Safe fallback SQL (keeps compatibility with existing schema used elsewhere in this module)
        try:
            cur = self.conn.execute(
                """
                SELECT s.sale_id, s.date,
                       srt.canonical_total_amount AS total,
                       srt.paid_amount AS paid,
                       srt.advance_payment_applied,
                       srt.remaining_due
                FROM sales s
                JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
                WHERE s.customer_id = ? AND s.doc_type = 'sale'
                ORDER BY date DESC, sale_id DESC
                LIMIT 200;
                """,
                (customer_id,),
            )
            out = []
            for row in cur.fetchall():
                out.append({
                    "sale_id": str(row["sale_id"]),
                    "doc_no": str(row["sale_id"]),
                    "date": str(row["date"]),
                    "total": float(row["total"]),
                    "paid": float(row["paid"]),
                    "advance_payment_applied": float(row["advance_payment_applied"]),
                    "remaining_due": float(row["remaining_due"]),
                })
            return out
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            _log.exception("Sales SQL fallback failed for customer_id=%s", customer_id)
            return []
        except Exception:
            _log.exception("Unexpected sales SQL fallback failure for customer_id=%s", customer_id)
            return []

    def _eligible_sales_for_application(self, customer_id: int) -> list[dict]:
        """
        Build a list of sales with remaining_due > 0 for apply-advance UI.
        Shape per input spec: at least {sale_id, date, remaining_due, total, paid}
        """
        rows = self._list_sales_for_customer(customer_id)
        out: list[dict] = []
        for r in rows:
            sid = str(r.get("sale_id") or "")
            if not sid:
                continue
            fin = self._fetch_sale_financials(sid)
            if fin["remaining_due"] > 1e-9:
                out.append({
                    "sale_id": sid,
                    "date": r.get("date"),
                    "remaining_due": fin["remaining_due"],
                    "total": fin["calculated_total_amount"],
                    "paid": fin["paid_amount"],
                })
        return out

    # ---- CRUD -------------------------------------------------------------

    def _add(self):
        # Use current view mode (Sales vs Quotations) when the user clicks
        # the module's own "Add" button.
        self._start_new_document(self._doc_type)

    def new_sale(self):
        """Start a new Sale, regardless of current mode."""
        self._start_new_document("sale")

    def new_quotation(self):
        """Start a new Quotation, regardless of current mode."""
        self._start_new_document("quotation")

    def _start_new_document(self, doc_type: str):
        """
        Shared helper for starting a new Sale or Quotation.
        doc_type: 'sale' or 'quotation'
        """
        doc_type = "quotation" if (doc_type or "sale").lower() == "quotation" else "sale"

        # Store doc_type so the handler method knows the context
        self._pending_doc_type = doc_type

        dlg = self._open_sale_form(as_quotation=(doc_type == "quotation"))
        if dlg is None:
            info(self.view, "Error", "Sale form could not be opened.")
            return

        # Set this as the active dialog and connect the accepted signal
        self.active_dialog = dlg
        self.active_dialog.accepted.connect(self._handle_add_dialog_accept)
        self.active_dialog.show()

    def _handle_add_dialog_accept(self):
        """Handle the accepted signal from the non-modal SaleForm"""
        if not self.active_dialog:
            return
        p = self.active_dialog.payload()
        if not p:
            return

        doc_type = getattr(self, '_pending_doc_type', 'sale')  # Use stored doc type

        if doc_type == "quotation":
            # Quotation creation: ID prefix QO, no inventory posting, no payments
            qid = ""

            h = SaleHeader(
                sale_id=qid,
                customer_id=p["customer_id"],
                date=p["date"],
                total_amount=p["total_amount"],
                order_discount=p["order_discount"],
                payment_status="—",          # display-only; payments disallowed
                paid_amount=0.0,
                advance_payment_applied=0.0,
                notes=p["notes"],
                created_by=self._current_user_id(),
                source_type="direct",
                source_id=None,
            )

            items = [
                SaleItem(
                    None,
                    qid,
                    it["product_id"],
                    it["quantity"],
                    it["uom_id"],
                    it["unit_price"],
                    it["item_discount"],
                )
                for it in p["items"]
            ]

            try:
                qid = self.repo.create_quotation(
                    h,
                    items,
                    quotation_status=p["quotation_status"],
                    expiry_date=p["expiry_date"],
                )
                info(self.view, "Saved", f"Quotation {qid} created.")

                # Check if this was called from print button
                should_print_after_save = p.get('_should_print', False)

                # Handle print request after saving
                if should_print_after_save:
                    self._print_quotation_invoice(qid)
            except Exception as e:
                info(self.view, "Error", f"Could not create quotation: {e}")
                return
            self._reload()
            self._sync_details()
            return

        # --- sale path ---
        sid = ""

        # Header: payment fields start at 0/unpaid. Roll-up comes from sale_payments.
        h = SaleHeader(
            sale_id=sid,
            customer_id=p["customer_id"],
            date=p["date"],
            total_amount=p["total_amount"],
            order_discount=p["order_discount"],
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=p["notes"],
            created_by=self._current_user_id(),
        )
        items = [
            SaleItem(
                None,
                sid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["unit_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]

        # Persist header + items + initial payment atomically
        init_amt = float(p.get("initial_payment") or 0.0)
        payment_info = None
        if init_amt > 0:
            method = p.get("initial_method") or "Cash"
            # Optional bank / instrument fields from the form payload
            bank_id = p.get("initial_bank_account_id")
            instr_no = (p.get("initial_instrument_no") or "").strip() if p.get("initial_instrument_no") else ""
            instr_type = p.get("initial_instrument_type")

            payment_info = {
                "sale_id": sid,
                "amount": init_amt,
                "method": method,
                "date": p["date"],
                "created_by": self._current_user_id(),
                "notes": "[Init payment]",
            }

            # Method-specific fields: align with SalePaymentsRepo expectations
            if method in ("Bank Transfer", "Cheque", "Cross Cheque"):
                if bank_id is not None:
                    payment_info["bank_account_id"] = int(bank_id)
                if instr_no:
                    payment_info["instrument_no"] = instr_no

            # Instrument type: prefer form payload; otherwise choose sensible defaults
            if instr_type:
                payment_info["instrument_type"] = instr_type
            else:
                if method == "Bank Transfer":
                    payment_info["instrument_type"] = "online"
                elif method in ("Cheque", "Cross Cheque"):
                    # Cheque and Cross Cheque share cross_cheque instrument_type
                    payment_info["instrument_type"] = "cross_cheque"
                else:
                    payment_info["instrument_type"] = "other"

        try:
            sid = self.repo.create_sale(h, items, payment_info)
            if payment_info:
                info(self.view, "Saved", f"Sale {sid} created and initial payment recorded.")
            else:
                info(self.view, "Saved", f"Sale {sid} created.")
        except (ValueError, sqlite3.Error) as e:
            info(self.view, "Error", f"Could not create sale:\n{e}")
            return
        except Exception:
            logging.exception("Unexpected error while creating sale %s", sid)
            info(self.view, "Error", "Could not create sale due to an unexpected error.")
            return

        # Check if this was called from print button
        should_print_after_save = p.get('_should_print', False)
        if should_print_after_save:
            self._print_sale_invoice(sid)

        self._reload()
        self._sync_details()

    def _edit(self):
        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a row to edit.")
            return

        doc_type = self._doc_type
        if doc_type == "sale" and not self._confirm_sale_edit_if_posted(r):
            return

        # Store doc_type and selected row so the handler method knows the context
        self._pending_doc_type = doc_type
        self._pending_edit_row = r

        items = self.repo.list_items(r["sale_id"])

        # Get complete header with customer information
        header_with_customer = self.repo.get_header_with_customer(r["sale_id"])

        init = {
            "sale_id": r["sale_id"],
            "customer_id": r["customer_id"],
            "customer_name": header_with_customer.get("customer_name") if header_with_customer else None,
            "date": r["date"],
            "quotation_status": (
                header_with_customer.get("quotation_status")
                if header_with_customer else r.get("quotation_status")
            ),
            "expiry_date": (
                header_with_customer.get("expiry_date")
                if header_with_customer else r.get("expiry_date")
            ),
            "order_discount": r.get("order_discount"),
            "notes": r.get("notes"),
            "items": [
                {
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "item_discount": it["item_discount"],
                }
                for it in items
            ],
        }

        dlg = self._open_sale_form(initial=init, as_quotation=(doc_type == "quotation"))
        if dlg is None:
            info(self.view, "Error", "Sale form could not be opened.")
            return

        # Set this as the active dialog and connect the accepted signal
        self.active_dialog = dlg
        self.active_dialog.accepted.connect(self._handle_edit_dialog_accept)
        self.active_dialog.show()

    def _confirm_sale_edit_if_posted(self, row: dict) -> bool:
        sid = row["sale_id"]
        payment_count = 0
        returned_qty = 0.0
        returned_value = 0.0

        try:
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # type: ignore
            pay_repo = SalePaymentsRepo(self._db_path)
            payment_count = len(list(pay_repo.list_by_sale(sid)) or [])
        except Exception:
            payment_count = 0

        try:
            rt = self.repo.sale_return_totals(sid)
            returned_qty = float(rt.get("qty", 0.0))
            returned_value = float(rt.get("value", 0.0))
        except Exception:
            returned_qty = 0.0
            returned_value = 0.0

        has_payments = payment_count > 0
        has_returns = returned_qty > 1e-9 or returned_value > 1e-9
        if not has_payments and not has_returns:
            return True

        risk_lines = []
        if has_payments:
            risk_lines.append(f"- Payments found: {payment_count}")
        if has_returns:
            risk_lines.append(f"- Returns found: {fmt_money(returned_value)}")

        message = (
            f"Sale {sid} already has downstream records.\n\n"
            + "\n".join(risk_lines)
            + "\n\nEditing the sale header or items can change totals, stock history, balances, and reports.\n"
              "Continue editing?"
        )
        answer = QMessageBox.question(
            self.view,
            "Edit Posted Sale?",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _handle_edit_dialog_accept(self):
        """Handle the accepted signal from the non-modal SaleForm during edit"""
        if not self.active_dialog:
            return
        p = self.active_dialog.payload()
        if not p:
            return

        doc_type = getattr(self, '_pending_doc_type', 'sale')  # Use stored doc type
        r = getattr(self, '_pending_edit_row', {})  # Use stored row data

        sid = r["sale_id"]

        if doc_type == "quotation":
            # Update quotation (no inventory posting). Use repo.update_quotation if available.
            if hasattr(self.repo, "update_quotation"):
                h = SaleHeader(
                    sale_id=sid,
                    customer_id=p["customer_id"],
                    date=p["date"],
                    total_amount=p["total_amount"],
                    order_discount=p["order_discount"],
                    payment_status=r.get("payment_status", "—"),
                    paid_amount=0.0,
                    advance_payment_applied=0.0,
                    notes=p["notes"],
                    created_by=self._current_user_id(),
                    source_type=r.get("source_type", "direct"),
                    source_id=r.get("source_id"),
                )
                items = [
                    SaleItem(
                        None,
                        sid,
                        it["product_id"],
                        it["quantity"],
                        it["uom_id"],
                        it["unit_price"],
                        it["item_discount"],
                    )
                    for it in p["items"]
                ]
                try:
                    self.repo.update_quotation(
                        h,
                        items,
                        quotation_status=p["quotation_status"],
                        expiry_date=p["expiry_date"],
                    )  # should not post inventory
                    info(self.view, "Saved", f"Quotation {sid} updated.")
                except Exception as e:
                    info(self.view, "Error", f"Could not update quotation: {e}")
                    return
            else:
                info(self.view, "Not available",
                     "Updating quotations requires SalesRepo.update_quotation(...).")
                return
            # Handle optional print-after-save for quotations
            should_print_after_save = p.get('_should_print', False)
            if should_print_after_save:
                self._print_quotation_invoice(sid)

            self._reload()
            self._sync_details()
            return

        # --- sale path ---
        h = SaleHeader(
            sale_id=sid,
            customer_id=p["customer_id"],
            date=p["date"],
            total_amount=p["total_amount"],
            order_discount=p["order_discount"],
            payment_status=r["payment_status"],
            paid_amount=r["paid_amount"],
            advance_payment_applied=0.0,
            notes=p["notes"],
            created_by=self._current_user_id(),
        )
        items = [
            SaleItem(
                None,
                sid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["unit_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]
        try:
            self.repo.update_sale(h, items)
        except (ValueError, sqlite3.Error) as e:
            info(self.view, "Error", f"Could not update sale:\n{e}")
            return
        except Exception:
            logging.exception("Unexpected error while updating sale %s", sid)
            info(self.view, "Error", "Could not update sale due to an unexpected error.")
            return

        # Check if this was called from print button
        should_print_after_save = p.get('_should_print', False)
        if should_print_after_save:
            self._print_sale_invoice(sid)
        else:
            info(self.view, "Saved", f"Sale {sid} updated.")

        self._reload()
        self._sync_details()

    def _delete(self):
        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a row to delete.")
            return
        sid = r["sale_id"]
        try:
            self.repo.delete_sale(sid)
        except (ValueError, sqlite3.Error) as e:
            info(self.view, "Error", f"Could not delete sale:\n{e}")
            return
        except Exception:
            logging.exception("Unexpected error while deleting sale %s", sid)
            info(self.view, "Error", "Could not delete sale due to an unexpected error.")
            return

        info(self.view, "Deleted", f"{r['sale_id']} removed.")
        self._reload()
        self._sync_details()

    # ---- Convert to Sale (from quotation mode) ----------------------------

    def _convert_to_sale(self):
        doc_type = self._doc_type
        if doc_type != "quotation":
            info(self.view, "Not a quotation", "Switch to Quotations to use Convert to Sale.")
            return

        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a quotation to convert.")
            return

        qo_id = r["sale_id"]
        if r.get("quotation_status") not in ("draft", "sent"):
            info(self.view, "Cannot Convert", f"Quotation {qo_id} has status '{r.get('quotation_status')}' and cannot be converted.")
            return

        date_for_so = today_str()  # you can change to reuse quotation date if you prefer
        try:
            # Perform DB-side conversion first (marks quotation, creates sale)
            so_id = self.repo.convert_quotation_to_sale(
                qo_id=qo_id,
                new_so_id=None,
                date=date_for_so,
                created_by=self._current_user_id(),
            )
        except Exception as e:
            info(self.view, "Error", f"Conversion failed: {e}")
            return

        # After conversion, open the new SALE in the SaleForm with the
        # initial payment section visible so the user can optionally
        # record an initial payment and/or print immediately.
        header_with_customer = self.repo.get_header_with_customer(so_id)
        items = self.repo.list_items(so_id)

        init = {
            "customer_id": header_with_customer.get("customer_id") if header_with_customer else r.get("customer_id"),
            "customer_name": header_with_customer.get("customer_name") if header_with_customer else r.get("customer_name"),
            "date": header_with_customer.get("date") if header_with_customer else date_for_so,
            "order_discount": header_with_customer.get("order_discount") if header_with_customer else r.get("order_discount"),
            "notes": header_with_customer.get("notes") if header_with_customer else r.get("notes"),
            "sale_id": so_id,
            "items": [
                {
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "item_discount": it["item_discount"],
                }
                for it in items
            ],
        }

        dlg = self._open_sale_form(initial=init, as_quotation=False)
        if dlg is None:
            info(self.view, "Error", "Sale form could not be opened after conversion.")
            self._reload()
            self._sync_details()
            return

        # Treat this like editing the newly created sale so our existing
        # handler (including optional print-after-save) can be reused.
        self._pending_doc_type = "sale"
        self._pending_edit_row = {
            "sale_id": so_id,
            "customer_id": init["customer_id"],
            "date": init["date"],
            "order_discount": init["order_discount"],
            "notes": init["notes"],
            "payment_status": header_with_customer.get("payment_status", "unpaid") if header_with_customer else "unpaid",
            "paid_amount": header_with_customer.get("paid_amount", 0.0) if header_with_customer else 0.0,
        }

        self.active_dialog = dlg
        self.active_dialog.accepted.connect(self._handle_edit_dialog_accept)
        self.active_dialog.show()

    # ---- Payments / Printing ---------------------------------------------

    def _on_payment_status_change_requested(self, payment_id: int, new_state: str):
        """
        Handle a request from the SaleDetails panel to update a payment's
        clearing_state (e.g., pending → cleared/bounced) for the current sale.
        """
        new = (new_state or "").lower()
        if new not in ("cleared", "bounced"):
            return
        try:
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # type: ignore
            pay_repo = SalePaymentsRepo(self._db_path)
            payment = pay_repo.get(payment_id)
            selected = self._selected_row()
            if (
                payment is None
                or selected is None
                or str(payment["sale_id"]) != str(selected["sale_id"])
                or str(payment["clearing_state"]).lower() != "pending"
            ):
                info(self.view, "Update failed", "Select a pending payment from the current sale.")
                self._sync_details()
                return
            target_label = "Cleared" if new == "cleared" else "Bounced"
            amount = fmt_money(float(payment["amount"] or 0.0))
            method = str(payment["method"] or "Unknown")
            answer = QMessageBox.question(
                self.view,
                "Confirm Payment State Change",
                (
                    f"Sale: {payment['sale_id']}\n"
                    f"Payment: #{payment_id}\n"
                    f"Method: {method}\n"
                    f"Amount: {amount}\n"
                    f"Current state: Pending\n"
                    f"New state: {target_label}\n\n"
                    "This changes the sale's financial history. Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            cleared_date = today_str() if new == "cleared" else None
            pay_repo.update_clearing_state(
                payment_id=payment_id,
                clearing_state=new,
                cleared_date=cleared_date,
            )
            self._reload()
            self._sync_details()
        except Exception as e:
            info(self.view, "Update failed", f"Could not update payment status:\n{e}")

    def _record_payment(self):
        """
        Open the customer payment UI for the selected sale (sales mode only).
        Route ONLY to the local Customer dialog + actions.
        """
        doc_type = self._doc_type
        if doc_type != "sale":
            info(self.view, "Not available", "Payments are not available for quotations.")
            return

        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a sale first.")
            return

        sale_id = str(row["sale_id"])
        customer_id = int(row.get("customer_id") or 0)
        customer_display = str(row.get("customer_name") or customer_id)

        # Only allow recording payments when there is a positive remaining
        # amount for this specific sale. This mirrors the purchase side where
        # the dialog is for clearing outstanding amounts, not creating credit.
        fin = self._fetch_sale_financials(sale_id)
        remaining = float(fin.get("remaining_due", 0.0))
        if remaining <= 1e-9:
            info(self.view, "Nothing to pay", "This sale has no remaining amount to receive.")
            return

        # Open a dedicated Sales payment form, mirroring the purchase payment
        # window but simplified to only use company bank accounts.
        try:
            from .payment_form import SalesPaymentForm  # type: ignore
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # type: ignore

            dlg = SalesPaymentForm(
                self.view,
                sale_id=sale_id,
                remaining=remaining,
                list_company_bank_accounts=self._list_company_bank_accounts,
            )
            if not dlg.exec():
                return
            payload = dlg.payload()
            if not payload:
                return

            repo = SalePaymentsRepo(self._db_path)
            repo.record_payment(
                sale_id=sale_id,
                amount=float(payload["amount"]),
                method=str(payload["method"]),
                date=payload["date"],
                bank_account_id=payload["bank_account_id"],
                instrument_no=payload["instrument_no"],
                notes=payload["notes"],
            )
            self._reload()
            self._sync_details()
            return
        except Exception as e:
            import logging
            logging.exception("Could not record payment")
            info(self.view, "Payment not recorded", f"Could not record payment:\n{e}")

    def _print(self):
        """
        Print the selected sale invoice.
        """
        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a row to print.")
            return

        doc_type = self._doc_type
        sale_id = row["sale_id"]

        if doc_type == "sale":
            self._print_sale_invoice(sale_id)
        elif doc_type == "quotation":
            self._print_quotation_invoice(sale_id)

        # After printing attempt, keep states fresh
        self._update_action_states()
        self._sync_details()

    # ---- Apply Credit to Sale (UPDATED) -----------------------------------

    def _on_apply_credit(self):
        """
        Apply existing customer credit to the currently selected SALE.

        Route ONLY to the local Customer dialog + actions.
        """
        if self._doc_type != "sale":
            info(self.view, "Not available", "Apply Credit is available for sales only.")
            return

        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a sale first.")
            return

        sale_id = str(row["sale_id"])
        customer_id = int(row.get("customer_id") or 0)
        if not customer_id:
            info(self.view, "Missing data", "Selected sale is missing customer information.")
            return

        _, _, credit_allowed, credit_message = self._financial_action_eligibility(row)
        if not credit_allowed:
            info(self.view, "Apply Credit unavailable", credit_message)
            self._update_action_states()
            return

        # Local dialog + actions (lazy import)
        try:
            from ..customer.receipt_dialog import open_payment_or_advance_form  # type: ignore
            from ..customer import actions as customer_actions  # type: ignore
            from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo

            payload = open_payment_or_advance_form(
                mode="apply_advance",
                customer_id=customer_id,
                sale_id=sale_id,
                defaults={
                    "list_sales_for_customer": self._list_sales_for_customer,
                    "sales": self._eligible_sales_for_application(customer_id),
                    "customer_display": f"{row.get('customer_name') or 'Customer'} (ID {customer_id})",
                    "get_available_advance": lambda cid: CustomerAdvancesRepo(self._db_path).get_balance(cid),
                    "get_sale_due": lambda sid: self._fetch_sale_financials(sid)["remaining_due"],
                },
            )
            if payload:
                result = customer_actions.apply_customer_advance(
                    db_path=self._db_path,
                    customer_id=customer_id,
                    sale_id=str(payload["sale_id"]),
                    with_ui=False,
                    form_defaults={
                        "customer_id": customer_id,
                        "sale_id": payload["sale_id"],
                        "amount": payload["amount"],
                        "date": payload.get("date"),
                        "notes": payload.get("notes"),
                        "created_by": payload.get("created_by"),
                    },
                )
                if not result or not result.success:
                    message = (
                        result.message
                        if result and result.message
                        else "Credit application was not recorded."
                    )
                    info(self.view, "Not saved", message)
                    return
                info(self.view, "Saved", "Credit application recorded.")
                self._reload()
                self._sync_details()
                return
        except Exception:
            info(
                self.view,
                "Apply Credit UI not available",
                "The local customer money dialog isn't available. "
                "Enable modules.customer.receipt_dialog or use the Customers module.",
            )
            self._update_action_states()
            self._sync_details()

    # ---- Returns ----------------------------------------------------------

    def _return(self, return_whole_order: bool = False):
        """
        Inventory: insert sale_return transactions.
        Money:
          - For 'refund now': insert a negative Cash payment via SalePaymentsRepo.
          - For the remainder: add a customer return credit via CustomerAdvancesRepo.
        Do NOT rewrite header totals/paid/status; DB and credit ledger are source of truth.
        """
        doc_type = self._doc_type
        if doc_type != "sale":
            info(self.view, "Not available", "Returns apply to sales only, not quotations.")
            return

        selected = self._selected_row()
        if not selected:
            info(self.view, "Select", "Select a sale first.")
            return

        return_allowed, return_message = self._return_eligibility(selected)
        if not return_allowed:
            info(self.view, "Return unavailable", return_message)
            self._update_action_states()
            return

        dlg = SaleReturnForm(self.view, repo=self.repo, sale_id=selected["sale_id"])
        if return_whole_order:
            dlg.chk_return_all.setChecked(True)

        # Store doc_type so the handler method knows the context
        self._pending_doc_type = doc_type
        self._pending_selected = selected

        # Set this as the active dialog and connect the accepted signal
        self.active_dialog = dlg
        self.active_dialog.accepted.connect(self._handle_return_dialog_accept)
        self.active_dialog.show()

    def _handle_return_dialog_accept(self):
        """Handle the accepted signal from the non-modal SaleReturnForm"""
        if not self.active_dialog:
            return
        p = self.active_dialog.payload()
        if not p:
            return

        doc_type = getattr(self, '_pending_doc_type', 'sale')  # Use stored doc type
        selected = getattr(self, '_pending_selected', None)  # Use stored selected data

        sid = p["sale_id"]
        items = self.repo.list_items(sid)
        by_id = {it["item_id"]: it for it in items}

        # Build inventory return lines
        lines = []
        for ln in p["lines"]:
            it = by_id.get(ln["item_id"])
            if not it:
                continue
            lines.append(
                {
                    "item_id": it["item_id"],
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "qty_return": float(ln["qty_return"]),
                }
            )

        requested_cash = float(p.get("cash_refund_now") or 0.0)
        return_date = p.get("return_date") or today_str()
        result = self.repo.record_return(
            sid=sid,
            date=return_date,
            created_by=self._current_user_id(),
            lines=lines,
            notes="[Return]",
            settlement={
                "cash_refund": requested_cash if p.get("refund_now") else 0.0,
                "refund_notes": "[Return refund]",
                "credit_notes": "[Return credit]",
            },
        )

        # Optional note if fully returned
        all_back = all(
            (
                float(
                    next((l["qty_return"] for l in p["lines"] if l["item_id"] == it["item_id"]), 0.0)
                )
                >= float(it["quantity"])
            )
            for it in items
        )
        if all_back:
            try:
                with self.conn:
                    self.conn.execute(
                        "UPDATE sales SET notes = COALESCE(notes,'') || ' [Full return]' WHERE sale_id=?",
                        (sid,),
                    )
            except Exception:
                pass

        # Summary
        cash_refund = float(result["cash_refund"])
        credit_part = float(result["credit_amount"])
        balance_reduction = min(
            float(result["return_value"]),
            float(result["remaining_due_before_return"]),
        )
        if cash_refund > 0:
            if credit_part > 0:
                info(
                    self.view,
                    "Saved",
                    f"Return recorded. Refunded {fmt_money(cash_refund)} in cash; "
                    f"{fmt_money(credit_part)} added to customer credit.",
                )
            else:
                info(self.view, "Saved", f"Return recorded. Refunded {fmt_money(cash_refund)} in cash.")
        elif credit_part > 0:
            info(self.view, "Saved", f"Return recorded. {fmt_money(credit_part)} added to customer credit.")
        else:
            info(self.view, "Saved", f"Return recorded. Balance reduced by {fmt_money(balance_reduction)}.")

        self._reload()
        self._sync_details()

    def _generate_invoice_html_content(self, sale_id: str) -> str:
        """Generate HTML content for sales invoice - shared between print and export methods."""
        import os
        from pathlib import Path
        from jinja2 import Template

        # Attempt to load template via configurable directory or filesystem path
        template_content = None

        # First, try configurable template directory attribute
        configured_template_dir = getattr(self, 'template_dir', None)
        if configured_template_dir:
            template_path = os.path.join(configured_template_dir, "sale_invoice.html")
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()
            except (FileNotFoundError, OSError):
                pass  # Try alternative methods

        # If not found via config, try to load from filesystem using a more robust path detection
        if template_content is None:
            try:
                # Define full_template_path before the try block to ensure it's always defined
                # Use pathlib for reliable path resolution relative to project root
                current_file_path = Path(__file__).resolve()  # Absolute path to current file
                project_root = current_file_path.parent.parent.parent  # Go up 3 levels to project root
                full_template_path = project_root / self.INVOICE_TEMPLATE_PATH

                with open(full_template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()
            except (FileNotFoundError, OSError) as e:
                error_msg = f"Template file not found at: {full_template_path}. Please ensure the invoice template exists. Error: {e}"
                logging.error(error_msg)
                raise FileNotFoundError(error_msg)

        if template_content is None:
            error_msg = "Could not load invoice template: all methods failed to find the template"
            logging.error(error_msg)
            raise FileNotFoundError(error_msg)

        # Prepare data for the template
        enriched_data = {"id": sale_id}

        # Fetch sale header data using repository
        header_row = self.repo.get_header_with_customer(sale_id)

        if header_row:
            doc_data = dict(header_row)
            # Map sale_id to id for template compatibility (matching purchase invoice template)
            doc_data['id'] = doc_data.get('sale_id', '')
            enriched_data['doc'] = doc_data
            enriched_data['customer'] = {
                'name': doc_data.get('customer_name', ''),
                'contact_info': doc_data.get('customer_contact_info', ''),
                'address': doc_data.get('customer_address', '')
            }

            # Fetch sale items using repository
            items_rows = self.repo.list_items(sale_id)

            items = []
            for row in items_rows:
                item_dict = dict(row)
                # Calculate line_total
                quantity = float(item_dict.get('quantity', 0.0))
                unit_price = float(item_dict.get('unit_price', 0.0))
                item_discount = float(item_dict.get('item_discount', 0.0))
                # Apply discount per unit: total_cost - (quantity * discount_per_unit)
                line_total = (quantity * unit_price) - (quantity * item_discount)
                item_dict['line_total'] = line_total

                # Calculate idx (row number)
                item_dict['idx'] = len(items) + 1

                # Map unit_name to uom_name for template compatibility
                if 'unit_name' in item_dict:
                    item_dict['uom_name'] = item_dict['unit_name']
                else:
                    item_dict['uom_name'] = 'N/A'

                items.append(item_dict)

            enriched_data['items'] = items

            # Calculate totals
            # Add back the quantity * item_discount per item to get subtotal before discounts
            subtotal_before_order_discount = sum(
                item['line_total'] + (float(item.get('quantity', 0.0)) * float(item.get('item_discount', 0.0)))
                for item in items
            )
            line_discount_total = sum(
                (float(item.get('quantity', 0.0)) * float(item.get('item_discount', 0.0)))
                for item in items
            )
            order_discount = float(doc_data.get('order_discount', 0.0))
            total = subtotal_before_order_discount - line_discount_total - order_discount

            enriched_data['totals'] = {
                'subtotal_before_order_discount': subtotal_before_order_discount,
                'line_discount_total': line_discount_total,
                'order_discount': order_discount,
                'total': total
            }

            # Keep gross invoice totals, but use the canonical net receivable for balance.
            position = self.repo.get_receivable_position(sale_id)
            paid_amount = float(position['paid_amount'])
            advance_payment_applied = float(position['advance_payment_applied'])
            remaining = float(position['remaining_due'])
            enriched_data['totals']['returned_value'] = float(position['returned_value'])
            enriched_data['totals']['net_total'] = float(position['net_total_amount'])

            return_rows = self.conn.execute(
                """
                SELECT
                  srs.return_date,
                  p.name AS product_name,
                  u.unit_name AS uom_name,
                  CAST(srs.returned_quantity AS REAL) AS returned_quantity,
                  CAST(srs.return_value AS REAL) AS return_value
                FROM sale_return_snapshots srs
                JOIN products p ON p.product_id = srs.product_id
                JOIN uoms u ON u.uom_id = srs.uom_id
                WHERE srs.sale_id = ?
                ORDER BY srs.return_date, srs.transaction_id
                """,
                (sale_id,),
            ).fetchall()
            enriched_data['returns'] = [dict(row) for row in return_rows]

            credit_row = self.conn.execute(
                """
                SELECT
                  COALESCE(SUM(CASE WHEN source_type='return_credit'
                                    THEN CAST(amount AS REAL) ELSE 0 END), 0.0)
                    AS return_credit,
                  COALESCE(SUM(CASE WHEN source_type='applied_to_sale'
                                    THEN -CAST(amount AS REAL) ELSE 0 END), 0.0)
                    AS applied_credit
                FROM customer_advances
                WHERE source_id = ?
                  AND source_type IN ('return_credit', 'applied_to_sale')
                """,
                (sale_id,),
            ).fetchone()
            enriched_data['return_credit'] = float(credit_row['return_credit'] or 0.0)
            enriched_data['applied_credit'] = float(
                credit_row['applied_credit'] or advance_payment_applied
            )

            enriched_data['paid_amount'] = paid_amount
            enriched_data['advance_payment_applied'] = advance_payment_applied
            enriched_data['remaining'] = remaining

            from ...database.repositories.company_info_repo import get_invoice_company_context
            enriched_data['company'] = get_invoice_company_context(self.conn)

            # Add payment status
            enriched_data['doc']['payment_status'] = doc_data.get('payment_status', 'Unpaid')

            # Get ALL payment rows for this sale so the invoice can show a
            # full payment history, not just the initial payment.
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo
            payments_repo = SalePaymentsRepo(self._db_path)

            raw_payments = list(payments_repo.list_by_sale(sale_id)) or []

            # Pre-load company bank labels to avoid querying inside the loop
            bank_labels: dict[int, str] = {}
            try:
                cur = self.conn.execute(
                    "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1"
                )
                bank_labels = {int(r["account_id"]): str(r["label"]) for r in cur.fetchall()}
            except Exception:
                bank_labels = {}

            payments: list[dict] = []
            for row in raw_payments:
                d = dict(row)
                amount = float(d.get("amount") or 0.0)
                d["amount"] = amount
                state = str(d.get("clearing_state") or "posted").lower()
                if amount < 0:
                    d["entry_type"] = "Payment Refund"
                elif state == "pending":
                    d["entry_type"] = "Pending Payment"
                elif state == "bounced":
                    d["entry_type"] = "Bounced Payment"
                else:
                    d["entry_type"] = "Payment"
                bid = d.get("bank_account_id")
                if bid is not None:
                    try:
                        d["bank_account_label"] = bank_labels.get(int(bid), "")
                    except Exception:
                        d["bank_account_label"] = ""
                else:
                    d["bank_account_label"] = ""
                payments.append(d)

            enriched_data["payments"] = payments

            # For backward compatibility, still expose the latest payment as
            # `initial_payment` (used by older templates).
            enriched_data["initial_payment"] = payments[-1] if payments else None

        # Create Jinja2 template and render
        template = Template(template_content, autoescape=True)
        html_content = template.render(**enriched_data)

        return html_content

    def _generate_quotation_html_content(self, quotation_id: str) -> str:
        """
        Generate HTML content for a QUOTATION invoice.
        Structure mirrors the sales invoice but without payments.
        """
        import os
        from pathlib import Path
        from jinja2 import Template

        # Load quotation template
        template_content = None
        try:
            current_file_path = Path(__file__).resolve()
            project_root = current_file_path.parent.parent.parent
            full_template_path = project_root / "resources/templates/invoices/quotation_invoice.html"
            with open(full_template_path, "r", encoding="utf-8") as f:
                template_content = f.read()
        except (FileNotFoundError, OSError) as e:
            error_msg = f"Quotation template file not found or unreadable: {e}"
            logging.error(error_msg)
            raise FileNotFoundError(error_msg)

        enriched_data: dict = {"id": quotation_id}

        header_row = self.repo.get_header_with_customer(quotation_id)
        if header_row:
            doc_data = dict(header_row)
            doc_data["id"] = doc_data.get("sale_id", "")
            doc_data["expiry_date"] = doc_data.get("expiry_date") or doc_data.get("date", "")
            enriched_data["doc"] = doc_data
            enriched_data["customer"] = {
                "name": doc_data.get("customer_name", ""),
                "contact_info": doc_data.get("customer_contact_info", ""),
                "address": doc_data.get("customer_address", ""),
            }

            # Items and totals (same computation as sales invoice)
            items_rows = self.repo.list_items(quotation_id)
            items: list[dict] = []
            for row in items_rows:
                item_dict = dict(row)
                quantity = float(item_dict.get("quantity", 0.0))
                unit_price = float(item_dict.get("unit_price", 0.0))
                item_discount = float(item_dict.get("item_discount", 0.0))
                line_total = (quantity * unit_price) - (quantity * item_discount)
                item_dict["line_total"] = line_total
                item_dict["idx"] = len(items) + 1
                if "unit_name" in item_dict:
                    item_dict["uom_name"] = item_dict["unit_name"]
                else:
                    item_dict["uom_name"] = "N/A"
                items.append(item_dict)
            enriched_data["items"] = items

            subtotal_before_order_discount = sum(
                it["line_total"]
                + (float(it.get("quantity", 0.0)) * float(it.get("item_discount", 0.0)))
                for it in items
            )
            line_discount_total = sum(
                float(it.get("quantity", 0.0)) * float(it.get("item_discount", 0.0))
                for it in items
            )
            order_discount = float(doc_data.get("order_discount", 0.0))
            total = subtotal_before_order_discount - line_discount_total - order_discount

            enriched_data["totals"] = {
                "subtotal_before_order_discount": subtotal_before_order_discount,
                "line_discount_total": line_discount_total,
                "order_discount": order_discount,
                "total": total,
            }

            from ...database.repositories.company_info_repo import get_invoice_company_context
            enriched_data["company"] = get_invoice_company_context(self.conn)

        template = Template(template_content, autoescape=True)
        return template.render(**enriched_data)

    def _sanitize_filename(self, filename: str, max_length: int = 100) -> str:
        """
        Sanitize a string for safe use as a filename.
        Removes unsafe characters, truncates to max_length, and provides UUID fallback for empty results.
        """
        # Remove or replace any path separators and other non-filename-safe characters
        sanitized = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
        # Trim to reasonable length to prevent issues with filesystem limits
        sanitized = sanitized[:max_length]
        # Fallback to a safe generated token if the result is empty
        if not sanitized or sanitized == "":
            sanitized = f"file_{uuid.uuid4().hex[:8]}"
        return sanitized

    def _print_sale_invoice(self, sale_id: str):
        """Print the sale invoice using WeasyPrint, writing to a temp folder
        with a stable filename equal to the sale_id. Old temp PDFs for sales
        are cleaned up automatically."""
        temp_pdf_path = None
        try:
            # Generate HTML content using the shared helper - this can raise various exceptions
            html_content = self._generate_invoice_html_content(sale_id)

            # Only try to import and use WeasyPrint after HTML is successfully generated
            try:
                from weasyprint import HTML, CSS
            except ImportError:
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
                return

            import tempfile
            import time
            # Temp directory dedicated to sale invoices
            temp_root = tempfile.gettempdir()
            pdf_dir = os.path.join(temp_root, "inventory_sales")
            os.makedirs(pdf_dir, exist_ok=True)

            # Cleanup old PDFs (> 1 day) in background
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

            # Use only the sale_id (sanitized) as filename
            sanitized_sale_id = self._sanitize_filename(sale_id, max_length=100)
            temp_pdf_path = os.path.join(pdf_dir, f"{sanitized_sale_id}.pdf")

            # Convert HTML to PDF with custom CSS for proper margins
            custom_css = CSS(string=self._INVOICE_PDF_CSS)

            html_doc = HTML(string=html_content)
            html_doc.write_pdf(temp_pdf_path, stylesheets=[custom_css])

            show_invoice_preview(self.view, temp_pdf_path, f"Sale Invoice {sale_id}")

        except Exception as e:
            info(self.view, "Error", f"Could not print invoice: {e}")

    def _print_quotation_invoice(self, quotation_id: str):
        """Print a quotation using the quotation invoice template. Uses the
        same temp-folder strategy as sales invoices."""
        temp_pdf_path = None
        try:
            html_content = self._generate_quotation_html_content(quotation_id)

            try:
                from weasyprint import HTML, CSS
            except ImportError:
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
                return

            import tempfile
            import time
            temp_root = tempfile.gettempdir()
            pdf_dir = os.path.join(temp_root, "inventory_quotations")
            os.makedirs(pdf_dir, exist_ok=True)

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

            sanitized_qid = self._sanitize_filename(quotation_id, max_length=100)
            temp_pdf_path = os.path.join(pdf_dir, f"{sanitized_qid}.pdf")

            custom_css = CSS(string=self._INVOICE_PDF_CSS)
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(temp_pdf_path, stylesheets=[custom_css])

            show_invoice_preview(self.view, temp_pdf_path, f"Quotation {quotation_id}")

        except Exception as e:
            info(self.view, "Error", f"Could not print quotation: {e}")
