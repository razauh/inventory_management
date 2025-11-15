from __future__ import annotations

import sqlite3
from typing import Any, Optional, Dict, List

from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
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
      - Loads active customers by default (customers.is_active = 1).
      - Right pane shows core fields + credit balance + recent activity.
      - Action buttons (Receive Payment, Record Advance, Apply Advance, Payment History)
        are disabled for inactive customers (history is allowed even if inactive).
      - Receipts enforce sale_id refers to a real SALE (not quotation) for this customer.
      - UI and actions are imported lazily to keep startup fast.

    Refactor:
      - Introduces _preflight() and _lazy_attr() to remove repeated boilerplate
        across payment/credit/history action handlers.
      - Adds local adapters for bank accounts and customer sales to support dialogs.
    """

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.repo = CustomersRepo(conn)
        self.view = CustomerView()
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
        self.view.search.textChanged.connect(self._apply_filter)

        # Payments/credit/history actions
        self.view.btn_receive_payment.clicked.connect(self._on_receive_payment)
        self.view.btn_record_advance.clicked.connect(self._on_record_advance)
        self.view.btn_apply_advance.clicked.connect(self._on_apply_advance)
        self.view.btn_payment_history.clicked.connect(self._on_payment_history)

        # Optional: Update Clearing button (wire only if present on the view)
        if hasattr(self.view, "btn_update_clearing"):
            self.view.btn_update_clearing.clicked.connect(self._on_update_clearing)

    def _build_model(self):
        # Active-only by default
        rows = self.repo.list_customers(active_only=True)
        self.base = CustomersTableModel(rows)

        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        self.view.table.resizeColumnsToContents()

        # selection model is NEW after setModel → connect every time (no disconnects)
        sel = self.view.table.selectionModel()
        sel.selectionChanged.connect(self._update_details)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.table.selectRow(0)
        # ensure right pane updates even if no selection event fired yet
        self._update_details()

    # ------------------------------------------------------------------ #
    # Helpers: selection & details
    # ------------------------------------------------------------------ #

    def _apply_filter(self, text: str):
        # Client-side filter (fast, preserves existing UX).
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_id(self) -> int | None:
        idxs = self.view.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row()).customer_id

    def _current_row(self) -> dict | None:
        cid = self._selected_id()
        cust = self.repo.get(cid) if cid else None
        return cust.__dict__ if cust else None

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

    def _fetch_is_active(self, customer_id: int) -> int:
        r = self.conn.execute(
            "SELECT is_active FROM customers WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        return int(r["is_active"]) if r and r["is_active"] is not None else 1

    def _details_enrichment(self, customer_id: int) -> Dict[str, Any]:
        """
        Compute credit balance & activity snapshot directly via SQL.
        """
        # credit balance
        bal_row = self.conn.execute(
            "SELECT balance FROM v_customer_advance_balance WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        credit_balance = float(bal_row["balance"]) if bal_row else 0.0

        # sales count + open due sum (use calculated_total_amount, and subtract advance_payment_applied)
        summary_row = self.conn.execute(
            """
            SELECT
              COUNT(*) AS sales_count,
              COALESCE(SUM(
                CASE
                  WHEN (
                    COALESCE(sdt.calculated_total_amount, s.total_amount)
                    - COALESCE(s.paid_amount, 0)
                    - COALESCE(s.advance_payment_applied, 0)
                  ) > 0
                  THEN (
                    COALESCE(sdt.calculated_total_amount, s.total_amount)
                    - COALESCE(s.paid_amount, 0)
                    - COALESCE(s.advance_payment_applied, 0)
                  )
                  ELSE 0
                END
              ), 0.0) AS open_due_sum
            FROM sales s
            LEFT JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
            WHERE s.customer_id = ? AND s.doc_type = 'sale';
            """,
            (customer_id,),
        ).fetchone()
        sales_count = int(summary_row["sales_count"] if summary_row else 0)
        open_due_sum = float(summary_row["open_due_sum"] if summary_row else 0.0)

        # recent activity dates
        last_sale_date = self.conn.execute(
            "SELECT MAX(date) AS d FROM sales WHERE customer_id=? AND doc_type='sale';",
            (customer_id,),
        ).fetchone()
        last_payment_date = self.conn.execute(
            """
            SELECT MAX(sp.date) AS d
            FROM sale_payments sp
            JOIN sales s ON s.sale_id = sp.sale_id
            WHERE s.customer_id = ?;
            """,
            (customer_id,),
        ).fetchone()
        last_advance_date = self.conn.execute(
            "SELECT MAX(tx_date) AS d FROM customer_advances WHERE customer_id=?;",
            (customer_id,),
        ).fetchone()

        return {
            "credit_balance": credit_balance,
            "sales_count": sales_count,
            "open_due_sum": open_due_sum,
            "last_sale_date": last_sale_date["d"] if last_sale_date and last_sale_date["d"] else None,
            "last_payment_date": last_payment_date["d"] if last_payment_date and last_payment_date["d"] else None,
            "last_advance_date": last_advance_date["d"] if last_advance_date and last_advance_date["d"] else None,
        }

    def _update_details(self, *args):
        payload = self._current_row()
        if not payload:
            self.view.details.set_data(None)
            # disable actions if nothing selected
            self._set_actions_enabled(False)
            return

        cid = int(payload["customer_id"])
        # add is_active + enrichment (credit & activity)
        try:
            is_active = self._fetch_is_active(cid)
        except sqlite3.Error:
            is_active = 1

        payload["is_active"] = is_active
        try:
            payload.update(self._details_enrichment(cid))
        except sqlite3.Error:
            # Non-fatal; keep basic payload
            pass

        self.view.details.set_data(payload)
        # enable/disable action buttons based on active flag
        self._set_actions_enabled(bool(is_active))

    def _set_actions_enabled(self, enabled: bool):
        # Editing customer info follows the same active flag
        self.view.btn_edit.setEnabled(enabled)
        # Optional delete remains unchanged/commented in base code.
        self.view.btn_receive_payment.setEnabled(enabled)
        self.view.btn_record_advance.setEnabled(enabled)
        self.view.btn_apply_advance.setEnabled(enabled)
        # History is allowed as long as something is selected
        self.view.btn_payment_history.setEnabled(True if self._selected_id() else False)
        # Optional clearing button mirrors enabled state (if present)
        if hasattr(self.view, "btn_update_clearing"):
            self.view.btn_update_clearing.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    # Small helpers to reduce repetition
    # ------------------------------------------------------------------ #

    def _preflight(self, *, require_active: bool = True, require_file_db: bool = True) -> tuple[Optional[int], Optional[str]]:
        """
        Common pre-checks for action handlers.

        Returns (customer_id, db_path). Any None means the caller should bail.
        - require_active: ensure selected customer is active
        - require_file_db: ensure database is file-backed (payments/credits need this)
        """
        cid = self._selected_id()
        if not cid:
            info(self.view, "Select", "Please select a customer first.")
            return None, None

        if require_active and not self._fetch_is_active(cid):
            info(self.view, "Inactive", "This customer is inactive. Enable the customer to proceed.")
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
        dlg = CustomerForm(self.view)
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
        dlg = CustomerForm(self.view, initial=current.__dict__)
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
                   COALESCE(label, bank_name || ' ' || account_no) AS name
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
              COALESCE(sdt.calculated_total_amount, s.total_amount) AS total,
              COALESCE(s.paid_amount, 0.0) AS paid
            FROM sales s
            LEFT JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
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
              COALESCE(sdt.calculated_total_amount, s.total_amount) AS total_calc,
              COALESCE(s.paid_amount, 0) AS paid_amount
            FROM sales s
            LEFT JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
            WHERE s.customer_id = ? AND s.doc_type = 'sale'
            ORDER BY s.date DESC, s.sale_id DESC;
            """,
            (customer_id,),
        ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            remaining = float(r["total_calc"] or 0.0) - float(r["paid_amount"] or 0.0)
            if remaining > 0:
                out.append(
                    {
                        "sale_id": r["sale_id"],
                        "date": r["date"],
                        "remaining_due": remaining,
                        "total": float(r["total_calc"] or 0.0),
                        "paid": float(r["paid_amount"] or 0.0),
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

    def _sale_belongs_to_customer_and_is_sale(self, sale_id: str, customer_id: int) -> bool:
        row = self.conn.execute(
            "SELECT customer_id, doc_type FROM sales WHERE sale_id = ?;",
            (sale_id,),
        ).fetchone()
        if not row:
            return False
        return int(row["customer_id"]) == int(customer_id) and row["doc_type"] == "sale"

    # -- Receive Payment --

    def _on_receive_payment(self):
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
        if not cid or not db_path:
            return

        # Use local dialog to gather payload so the user can PICK the sale (legacy UX).
        open_payment_or_advance_form = self._lazy_attr(
            "inventory_management.modules.customer.receipt_dialog.open_payment_or_advance_form",
            toast_title="Unavailable",
            on_fail="Receipt dialog is not available.",
        )
        if not open_payment_or_advance_form:
            return

        form_defaults = {
            "list_company_bank_accounts": self._list_company_bank_accounts,
            "list_sales_for_customer": self._list_sales_for_customer,
            "customer_display": str(cid),
        }
        payload = open_payment_or_advance_form(
            mode="receipt",
            customer_id=cid,
            sale_id=None,           # allow the dialog to present the sale picker (legacy UX)
            defaults=form_defaults,
        )
        if not payload:
            return  # cancelled

        sale_id = payload.get("sale_id")
        if not sale_id:
            info(self.view, "Required", "Please select a sale to receive payment.")
            return

        # Guard: must be a real SALE for this customer (not a quotation)
        if not self._sale_belongs_to_customer_and_is_sale(sale_id, cid):
            info(self.view, "Invalid", "Payments can only be recorded against SALES belonging to this customer.")
            return

        # Persist via the actions layer (no additional UI)
        receive_payment = self._lazy_attr(
            "inventory_management.modules.customer.actions.receive_payment",
            toast_title="Error",
            on_fail="Could not load actions.receive_payment",
        )
        if not receive_payment:
            return

        result = receive_payment(
            db_path=db_path,
            sale_id=str(sale_id),
            customer_id=cid,
            with_ui=False,
            form_defaults=payload,  # already validated by dialog; actions will recheck required keys
        )
        if not result or not result.success:
            info(self.view, "Not saved", (result.message if result else "Unknown error"))
            return

        info(self.view, "Saved", f"Payment #{result.id} recorded.")
        self._reload()

    # -- Record Advance (Deposit / Credit) --

    def _on_record_advance(self):
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
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
            # Optional: you can pass today() or created_by here if desired
            "customer_display": str(cid),
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

        info(self.view, "Saved", f"Advance #{result.id} recorded.")
        self._reload()

    # -- Apply Advance to a Sale --

    def _on_apply_advance(self):
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
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
            "customer_display": str(cid),
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
        success_msg = f"Advance applied successfully."
        if result and hasattr(result, 'payload') and result.payload:
            # If the result has payload with amount info, include it in the message
            amount_applied = result.payload.get('amount') if isinstance(result.payload, dict) else None
            if amount_applied:
                success_msg = f"Advance of {amount_applied} applied successfully."
        info(self.view, "Success", success_msg)

    # -- Update Clearing (optional button) --

    def _on_update_clearing(self):
        """
        Optional handler for a 'Update Clearing' toolbar button if your view provides it.
        Implement a tiny prompt dialog to collect payment_id, state, cleared_date, notes.
        """
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
        if not cid or not db_path:
            return

        # Small, generic prompt utility could live elsewhere; for now, import lazily if you have one.
        # Expect a dict like: {"payment_id": int, "clearing_state": str, "cleared_date": str|None, "notes": str|None}
        prompt_update = self._lazy_attr(
            "inventory_management.modules.shared.prompts.prompt_update_clearing",  # hypothetical optional prompt
            toast_title="Unavailable",
            on_fail="Clearing prompt is not available.",
        )
        if not prompt_update:
            return
        data = prompt_update(parent=self.view)
        if not data:
            return

        update_receipt_clearing = self._lazy_attr(
            "inventory_management.modules.customer.actions.update_receipt_clearing",
            toast_title="Error",
            on_fail="Could not load actions.update_receipt_clearing",
        )
        if not update_receipt_clearing:
            return

        result = update_receipt_clearing(
            db_path=db_path,
            payment_id=int(data.get("payment_id")),
            clearing_state=str(data.get("clearing_state")),
            cleared_date=data.get("cleared_date"),
            notes=data.get("notes"),
        )
        if not result or not result.success:
            info(self.view, "Not updated", (result.message if result else "Unknown error"))
            return

        info(self.view, "Updated", result.message or "Receipt clearing updated.")
        self._reload()

    # -- Payment / Credit History --

    def _on_payment_history(self):
        # History is allowed even if customer is inactive; file DB not strictly required
        cid, db_path = self._preflight(require_active=False, require_file_db=False)
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
        # Removed message display to prevent popup
        # if result and result.message:
        #     # Optionally surface a non-fatal message (e.g., UI fallback not available)
        #     info(self.view, "Info", result.message)
