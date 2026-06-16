from __future__ import annotations

import sqlite3
import logging
from typing import Any, Optional, Dict, List

from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PySide6.QtWidgets import QWidget

from ..base_module import BaseModule
from .view import CustomerView
from .form import CustomerForm
from .model import CustomersTableModel
from ...database.repositories.customers_repo import CustomersRepo
from ...utils.ui_helpers import info


class CustomerController(BaseModule):
    """
    Customers controller with payment/credit actions and enriched details.

    Key behavior:
      - Right pane shows core fields + credit balance + recent activity.
      - Receipts enforce sale_id refers to a real SALE (not quotation) for this customer.
      - UI and actions are imported lazily to keep startup fast.

    Refactor:
      - Introduces _preflight() and _lazy_attr() to remove repeated boilerplate
        across payment/credit/history action handlers.
      - Adds local adapters for bank accounts and customer sales to support dialogs.
    """
    PAGE_SIZE = 100

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.repo = CustomersRepo(conn)
        self.view = CustomerView()
        self._search_timer = QTimer(self.view)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._pending_search = ""
        self._page_offset = 0
        self._total_customers = 0
        self._columns_sized = False
        self._last_detail_customer_id: int | None = None
        self._build_model()
        self._wire()
        self._reload()

    # ------------------------------------------------------------------ #
    # BaseModule API
    # ------------------------------------------------------------------ #

    def get_widget(self) -> QWidget:
        return self.view

    # ------------------------------------------------------------------ #
    # Wiring & model
    # ------------------------------------------------------------------ #

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.search.textChanged.connect(self._queue_filter)
        self._search_timer.timeout.connect(lambda: self._apply_filter(self._pending_search))
        self.view.btn_prev_page.clicked.connect(self._prev_page)
        self.view.btn_next_page.clicked.connect(self._next_page)

        # Payments/credit/history actions
        self.view.btn_record_advance.clicked.connect(self._on_record_advance)
        self.view.btn_apply_advance.clicked.connect(self._on_apply_advance)
        self.view.btn_history.clicked.connect(self._on_payment_history)
        if hasattr(self.view, "btn_print_history"):
            self.view.btn_print_history.clicked.connect(self._on_history_print)


    def _build_model(self):
        self.base = CustomersTableModel([])
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        sel = self.view.table.selectionModel()
        sel.selectionChanged.connect(self._update_details)

    def _reload(self):
        selected_id = self._selected_id()
        query = self._pending_search.strip()
        self._total_customers = self.repo.count_customers(query)
        if self._page_offset >= self._total_customers:
            self._page_offset = max(0, ((self._total_customers - 1) // self.PAGE_SIZE) * self.PAGE_SIZE)
        rows = self.repo.list_customers(
            search=query,
            limit=self.PAGE_SIZE,
            offset=self._page_offset,
        )
        self.base.replace(rows)
        if not self._columns_sized:
            self.view.table.resizeColumnsToContents()
            self._columns_sized = True
        self._last_detail_customer_id = None
        self._sync_table_state(selected_id)

    # ------------------------------------------------------------------ #
    # Helpers: selection & details
    # ------------------------------------------------------------------ #

    def _queue_filter(self, text: str):
        self._pending_search = text
        self._search_timer.start()

    def _apply_filter(self, text: str):
        self._pending_search = text
        self._page_offset = 0
        self._reload()

    def _prev_page(self):
        if self._page_offset <= 0:
            return
        self._page_offset = max(0, self._page_offset - self.PAGE_SIZE)
        self._reload()

    def _next_page(self):
        next_offset = self._page_offset + self.PAGE_SIZE
        if next_offset >= self._total_customers:
            return
        self._page_offset = next_offset
        self._reload()

    def _sync_page_controls(self) -> None:
        total_pages = max(1, (self._total_customers + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        current_page = min(total_pages, (self._page_offset // self.PAGE_SIZE) + 1)
        self.view.lbl_page.setText(f"Page {current_page} / {total_pages}")
        self.view.btn_prev_page.setEnabled(self._page_offset > 0)
        self.view.btn_next_page.setEnabled(self._page_offset + self.PAGE_SIZE < self._total_customers)

    def _loaded_count(self) -> int:
        return self.base.rowCount()

    def _status_text(self, query: str) -> str:
        loaded = self._loaded_count()
        total = int(self._total_customers or 0)
        if total <= 0:
            return "No customers match this search." if query else "No customers available."
        label = "match(es)" if query else "customer(s)"
        return f"Showing {loaded} of {total} {label}"

    def _sync_table_state(self, selected_id: Optional[int]) -> None:
        query = self._pending_search.strip()
        self._sync_page_controls()
        selection_model = self.view.table.selectionModel()
        if selection_model is not None:
            selection_model.blockSignals(True)
        try:
            if self.base.rowCount() > 0:
                self._select_customer_id(selected_id)
                self.view.list_status.setText(self._status_text(query))
            else:
                self.view.table.clearSelection()
                self.view.list_status.setText(self._status_text(query))
        finally:
            if selection_model is not None:
                selection_model.blockSignals(False)
        self._last_detail_customer_id = None
        self._update_details()

    def _select_customer_id(self, customer_id: Optional[int]) -> None:
        target_row = None
        if customer_id is not None:
            for row in range(self.base.rowCount()):
                source_index = self.base.index(row, 0)
                if self.base.at(row).customer_id != customer_id:
                    continue
                proxy_index = self.proxy.mapFromSource(source_index)
                if proxy_index.isValid():
                    target_row = proxy_index.row()
                    break
        if target_row is None and self.proxy.rowCount() > 0:
            target_row = 0
        if target_row is None:
            self.view.table.clearSelection()
            return
        self.view.table.selectRow(target_row)

    def _selected_id(self) -> int | None:
        selection_model = self.view.table.selectionModel()
        if selection_model is None:
            return None
        idxs = selection_model.selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row()).customer_id

    def _selected_customer(self):
        selection_model = self.view.table.selectionModel()
        if selection_model is None:
            return None
        idxs = selection_model.selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row())

    def _db_path_from_conn(self) -> Optional[str]:
        """
        Resolve the file path for the 'main' database. Returns None for in-memory DB.
        """
        row = self.conn.execute("PRAGMA database_list;").fetchone()
        # row: (seq, name, file)
        if not row:
            return None
        _, name, path = row
        return path if name == "main" and path else None

    def _details_enrichment(self, customer_id: int) -> Dict[str, Any]:
        snapshot = self.repo.get_detail_snapshot(customer_id) or {}
        return {
            "credit_balance": float(snapshot.get("credit_balance") or 0.0),
            "sales_count": int(snapshot.get("sales_count") or 0),
            "open_due_sum": float(snapshot.get("open_due_sum") or 0.0),
            "last_sale_date": snapshot.get("last_sale_date"),
            "last_payment_date": snapshot.get("last_payment_date"),
            "last_advance_date": snapshot.get("last_advance_date"),
        }

    def _update_details(self, *args):
        customer = self._selected_customer()
        if not customer:
            self._last_detail_customer_id = None
            self.view.details.set_data(None)
            self._set_actions_enabled(False)
            return

        cid = int(customer.customer_id)
        if cid == self._last_detail_customer_id:
            self._set_actions_enabled(True)
            return

        payload = {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "contact_info": customer.contact_info,
            "address": customer.address,
        }
        try:
            snapshot = self.repo.get_detail_snapshot(cid)
            if snapshot:
                payload.update(snapshot)
            else:
                self._last_detail_customer_id = None
                self.view.details.set_data(None)
                self._set_actions_enabled(False)
                return
        except sqlite3.Error:
            payload["financial_error"] = True

        self._last_detail_customer_id = cid
        self.view.details.set_data(payload)
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool):
        self.view.btn_edit.setEnabled(enabled)
        # Optional delete remains unchanged/commented in base code.
        self.view.btn_record_advance.setEnabled(enabled)
        self.view.btn_apply_advance.setEnabled(enabled)
        # History popup is allowed as long as something is selected
        has_selection = self._selected_id() is not None
        self.view.btn_history.setEnabled(has_selection)
        self.view.btn_print_history.setEnabled(has_selection)

    # ------------------------------------------------------------------ #
    # Small helpers to reduce repetition
    # ------------------------------------------------------------------ #

    def _preflight(self, *, require_file_db: bool = True) -> tuple[Optional[int], Optional[str]]:
        """
        Common pre-checks for action handlers.

        Returns (customer_id, db_path). Any None means the caller should bail.
        - require_file_db: ensure database is file-backed (payments/credits need this)
        """
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer first.")
            return None, None

        db_path: Optional[str]
        if require_file_db:
            db_path = self._ensure_db_path_or_toast()
            if not db_path:
                return None, None
        else:
            db_path = self._db_path_from_conn() or ":memory:"

        return cid, db_path

    def _lazy_attr(self, dotted: str, *, toast_title: str, on_fail: str) -> Any | None:
        """
        Lazy-import a symbol using a dotted path (e.g., 'pkg.mod.func' or 'pkg.mod.Class').
        Shows a toast if import fails and returns None.
        """
        try:
            module_path, attr_name = dotted.rsplit(".", 1)
            mod = __import__(module_path, fromlist=[attr_name])
            return getattr(mod, attr_name)
        except Exception as e:
            info(self.view, toast_title, f"{on_fail} ({e})")
            return None

    # ------------------------------------------------------------------ #
    # CRUD (unchanged behavior)
    # ------------------------------------------------------------------ #

    def _add(self):
        dlg = CustomerForm(self.view, dup_check=self.repo.has_duplicate_name)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return
        cid = self.repo.create(**p)
        info(self.view, "Saved", f"Customer #{cid} created.")
        self._reload()

    def _edit(self):
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer to edit.")
            return
        current = self.repo.get(cid)
        dlg = CustomerForm(self.view, initial=current.__dict__, dup_check=self.repo.has_duplicate_name)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return
        self.repo.update(cid, **p)
        info(self.view, "Saved", f"Customer #{cid} updated.")
        self._reload()

    def _delete(self):
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer to delete.")
            return
        self.repo.delete(cid)
        info(self.view, "Deleted", f"Customer #{cid} removed.")
        self._reload()

    # ------------------------------------------------------------------ #
    # Adapters required by dialogs
    # ------------------------------------------------------------------ #

    def _list_company_bank_accounts(self) -> List[Dict[str, Any]]:
        """
        Return active company bank accounts as [{id, name}].
        """
        rows = self.conn.execute(
            """
            SELECT account_id AS id,
                   COALESCE(label, bank_name || ' ending ' || substr(account_no, -4)) AS name
            FROM company_bank_accounts
            WHERE is_active = 1
            ORDER BY name ASC;
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _list_sales_for_customer(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Return sales for a customer with totals/paid to compute remaining.
        """
        rows = self.conn.execute(
            """
            SELECT
              s.sale_id,
              s.doc_no,
              s.date,
              srt.canonical_total_amount AS total,
              srt.paid_amount AS paid,
              srt.advance_payment_applied AS advance_payment_applied,
              srt.remaining_due AS remaining_due
            FROM sales s
            JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
            WHERE s.customer_id = ? AND s.doc_type = 'sale'
            ORDER BY s.date DESC, s.sale_id DESC;
            """,
            (customer_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _eligible_sales_for_application(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Return list of sales with remaining due > 0 for the customer.
        (Used to seed 'apply advance' UI when needed.)
        """
        rows = self.conn.execute(
            """
            SELECT
              s.sale_id,
              s.date,
              srt.canonical_total_amount AS total_calc,
              srt.paid_amount AS paid_amount,
              srt.advance_payment_applied AS advance_payment_applied,
              srt.remaining_due AS remaining_due
            FROM sales s
            JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
            WHERE s.customer_id = ? AND s.doc_type = 'sale'
            ORDER BY s.date DESC, s.sale_id DESC;
            """,
            (customer_id,),
        ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            remaining = float(r["remaining_due"] or 0.0)
            if remaining > 0:
                out.append(
                    {
                        "sale_id": r["sale_id"],
                        "date": r["date"],
                        "remaining_due": remaining,
                        "total": float(r["total_calc"] or 0.0),
                        "paid": float(r["paid_amount"] or 0.0),
                        "advance_payment_applied": float(r["advance_payment_applied"] or 0.0),
                    }
                )
        return out

    # ------------------------------------------------------------------ #
    # Payment / Credit Actions
    # ------------------------------------------------------------------ #

    def _ensure_db_path_or_toast(self) -> Optional[str]:
        db_path = self._db_path_from_conn()
        if not db_path:
            info(
                self.view,
                "Unavailable",
                "This action requires a file-backed database. In-memory databases are not supported for payments.",
            )
            return None
        return db_path

    def _on_history_print(self):
        """
        Print a simple customer statement based on the same history payload
        used for the Payment History window.
        """
        cid, db_path = self._preflight(require_file_db=True)
        if not cid or not db_path:
            return

        from .history import CustomerHistoryService
        from jinja2 import Template
        import os
        import tempfile
        import time
        import subprocess
        import sys
        from weasyprint import HTML, CSS

        try:
            svc = CustomerHistoryService(db_path)
            payload = svc.full_history(cid)
        except Exception as e:
            info(self.view, "Error", f"Could not load customer history:\n{e}")
            return

        # Load template (TODO: move to a centralized template loader / config)
        from importlib import resources as importlib_resources
        try:
            template_content = importlib_resources.files(
                "inventory_management.resources.templates.invoices"
            ).joinpath("customer_history.html").read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, ModuleNotFoundError) as e:
            info(self.view, "Error", f"Cannot load customer history template:\n{e}")
            return

        # Basic customer info from repo
        cust = self.repo.get(cid)
        customer_data = {
            "id": cid,
            "name": getattr(cust, "name", ""),
            "contact_info": getattr(cust, "contact_info", ""),
            "address": getattr(cust, "address", ""),
        }

        summary = payload.get("summary") or {}
        events = payload.get("timeline") or []

        template = Template(template_content, autoescape=True)
        html = template.render(
            customer=customer_data,
            summary=summary,
            events=events,
        )

        # Temp dir for customer statements
        temp_root = tempfile.gettempdir()
        pdf_dir = os.path.join(temp_root, "inventory_customer_history")
        os.makedirs(pdf_dir, exist_ok=True)

        # Cleanup old PDFs (>1 day)
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

        file_path = os.path.join(pdf_dir, f"customer_{cid}.pdf")

        try:
            css = CSS(string="body { font-family: Arial, Helvetica, sans-serif; font-size: 11px; }")
            HTML(string=html).write_pdf(file_path, stylesheets=[css])
        except Exception as e:
            info(self.view, "Error", f"Could not generate statement PDF:\n{e}")
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(file_path)  # type: ignore[attr-defined]
            elif sys.platform.startswith("darwin"):
                subprocess.run(["open", file_path], timeout=5)
            else:
                subprocess.run(["xdg-open", file_path], timeout=5)
        except subprocess.TimeoutExpired:
            info(self.view, "Print", f"Statement PDF saved to: {file_path} (viewer timed out).")
        except Exception:
            info(self.view, "Print", f"Statement PDF saved to: {file_path}")

    def sale_belongs_to_customer_and_is_sale(self, sale_id: int, customer_id: int) -> bool:
        try:
            row = self.conn.execute(
                "SELECT customer_id, doc_type FROM sales WHERE sale_id = ?;",
                (int(sale_id),),
            ).fetchone()
        except sqlite3.DatabaseError as e:
            logging.getLogger(__name__).error(
                "Error checking sale %s for customer %s: %s",
                sale_id,
                customer_id,
                e,
                exc_info=True,
            )
            return False
        except Exception as e:
            logging.getLogger(__name__).error(
                "Unexpected error checking sale %s for customer %s: %s",
                sale_id,
                customer_id,
                e,
                exc_info=True,
            )
            return False

        if not row:
            return False
        return int(row["customer_id"]) == int(customer_id) and row["doc_type"] == "sale"

    # -- Record Advance (Deposit / Credit) --

    def _on_record_advance(self):
        cid, db_path = self._preflight(require_file_db=True)
        if not cid or not db_path:
            return

        record_customer_advance = self._lazy_attr(
            "inventory_management.modules.customer.actions.record_customer_advance",
            toast_title="Error",
            on_fail="Could not load actions.record_customer_advance",
        )
        if not record_customer_advance:
            return

        form_defaults = {
            "customer_display": self._customer_display(cid),
            "list_company_bank_accounts": self._list_company_bank_accounts,
            "get_available_advance": lambda customer_id: self._details_enrichment(customer_id).get("credit_balance", 0.0),
        }
        result = record_customer_advance(
            db_path=db_path,
            customer_id=cid,
            with_ui=True,
            form_defaults=form_defaults,
        )
        if not result or not result.success:
            if result and result.message:
                info(self.view, "Not saved", result.message)
            return

        payload = result.payload or {}
        info(
            self.view,
            "Saved",
            f"Recorded {float(payload.get('amount') or 0):,.2f} customer credit "
            f"for {self._customer_display(cid)} by {payload.get('method') or 'unknown method'}.",
        )
        self._reload()

    # -- Apply Advance to a Sale --

    def _on_apply_advance(self):
        cid, db_path = self._preflight(require_file_db=True)
        if not cid or not db_path:
            return

        apply_customer_advance = self._lazy_attr(
            "inventory_management.modules.customer.actions.apply_customer_advance",
            toast_title="Error",
            on_fail="Could not load actions.apply_customer_advance",
        )
        if not apply_customer_advance:
            return

        # Provide sales list; dialog may also query via adapter
        form_defaults = {
            "sales": self._eligible_sales_for_application(cid),
            "list_sales_for_customer": self._list_sales_for_customer,
            "get_available_advance": lambda customer_id: self._details_enrichment(customer_id).get("credit_balance", 0.0),
            "get_sale_due": lambda sale_id: next(
                (row["remaining_due"] for row in self._list_sales_for_customer(cid) if str(row["sale_id"]) == str(sale_id)),
                0.0,
            ),
            "customer_display": self._customer_display(cid),
        }
        result = apply_customer_advance(
            db_path=db_path,
            customer_id=cid,
            sale_id=None,           # allow dialog to select the sale
            with_ui=True,
            form_defaults=form_defaults,
        )
        if not result:
            # Log the server-side error
            import logging
            logging.error(f"Apply advance failed - result is None. Customer ID: {cid}, Form defaults keys: {list(form_defaults.keys()) if form_defaults else 'None'}")
            # Show a safe error message to the user
            info(self.view, "Error", "An unexpected error occurred while applying the advance.")
            return
        elif not result.success:
            # Check if this is a simple cancellation (no actual error)
            # When users cancel the dialog, we get result.success=False with no specific error message
            if not result.message:  # If no specific message, likely just a cancellation
                # Don't show an error - user simply cancelled
                return
            # Otherwise, it's a real error
            # Log the server-side error with details
            import logging
            logging.error(f"Apply advance failed - result.success is False. Customer ID: {cid}, Result: {result}")
            # Show the error message to the user
            info(self.view, "Error", result.message)
            return

        self._reload()  # Reload the UI to reflect changes

        # Show success confirmation to user
        success_msg = "Customer credit applied successfully."
        if result and hasattr(result, 'payload') and result.payload:
            # If the result has payload with amount info, include it in the message
            amount_applied = result.payload.get('amount') if isinstance(result.payload, dict) else None
            if amount_applied:
                sale_id = result.payload.get("sale_id")
                success_msg = f"Applied {float(amount_applied):,.2f} of customer credit to sale {sale_id}."
        info(self.view, "Success", success_msg)

    def _customer_display(self, customer_id: int) -> str:
        customer = self.repo.get(customer_id)
        name = customer.name if customer else "Customer"
        return f"{name} (ID {customer_id})"

    # -- Payment / Credit History --

    def _on_payment_history(self):
        cid, db_path = self._preflight(require_file_db=False)
        if not cid:
            return

        open_payment_history = self._lazy_attr(
            "inventory_management.modules.customer.actions.open_payment_history",
            toast_title="Error",
            on_fail="Could not load actions.open_payment_history",
        )
        if not open_payment_history:
            return

        result = open_payment_history(
            db_path=db_path or ":memory:",
            customer_id=cid,
            with_ui=True,
        )
        if not result or not result.success:
            info(self.view, "History unavailable", result.message if result else "Customer history could not be loaded.")
