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
      - UI modules are imported lazily to keep startup fast.

    Refactor:
      - Introduces _preflight() and _lazy_attr() to remove repeated boilerplate
        across payment/credit/history action handlers.
    """

    def __init__(self, conn: sqlite3.Connection):
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

        open_receipt_form = self._lazy_attr(
            "payments.ui.customer_receipt_form.open_receipt_form",
            toast_title="Unavailable",
            on_fail="Receipt form UI is not available. Please install payments.ui.customer_receipt_form.",
        )
        if not open_receipt_form:
            return

        form_payload = open_receipt_form(customer_id=cid, sale_id=None, defaults=None)
        if not form_payload:
            return  # cancelled

        sale_id = form_payload.get("sale_id")
        if not sale_id:
            info(self.view, "Required", "Please select a sale to receive payment.")
            return

        # Guard: must be a real SALE for this customer (not a quotation)
        if not self._sale_belongs_to_customer_and_is_sale(sale_id, cid):
            info(self.view, "Invalid", "Payments can only be recorded against SALES belonging to this customer.")
            return

        SalePaymentsRepo = self._lazy_attr(
            "inventory_management.database.repositories.sale_payments_repo.SalePaymentsRepo",
            toast_title="Error",
            on_fail="Could not load SalePaymentsRepo",
        )
        if not SalePaymentsRepo:
            return

        repo = SalePaymentsRepo(db_path)
        try:
            payment_id = repo.record_payment(
                sale_id=sale_id,
                amount=float(form_payload.get("amount", 0) or 0),
                method=str(form_payload.get("method") or ""),
                date=form_payload.get("date"),
                bank_account_id=form_payload.get("bank_account_id"),
                instrument_type=form_payload.get("instrument_type"),
                instrument_no=form_payload.get("instrument_no"),
                instrument_date=form_payload.get("instrument_date"),
                deposited_date=form_payload.get("deposited_date"),
                cleared_date=form_payload.get("cleared_date"),
                clearing_state=form_payload.get("clearing_state"),
                ref_no=form_payload.get("ref_no"),
                notes=form_payload.get("notes"),
                created_by=form_payload.get("created_by"),
            )
        except (ValueError, sqlite3.IntegrityError) as e:
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Payment #{payment_id} recorded.")
        self._reload()

    # -- Record Advance (Deposit / Credit) --

    def _on_record_advance(self):
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
        if not cid or not db_path:
            return

        open_record_advance_form = self._lazy_attr(
            "payments.ui.customer_advance_form.open_record_advance_form",
            toast_title="Unavailable",
            on_fail="Advance form UI is not available. Please install payments.ui.customer_advance_form.",
        )
        if not open_record_advance_form:
            return

        form_payload = open_record_advance_form(customer_id=cid, defaults=None)
        if not form_payload:
            return  # cancelled

        CustomerAdvancesRepo = self._lazy_attr(
            "inventory_management.database.repositories.customer_advances_repo.CustomerAdvancesRepo",
            toast_title="Error",
            on_fail="Could not load CustomerAdvancesRepo",
        )
        if not CustomerAdvancesRepo:
            return

        repo = CustomerAdvancesRepo(db_path)
        try:
            tx_id = repo.grant_credit(
                customer_id=cid,
                amount=float(form_payload.get("amount", 0) or 0),
                date=form_payload.get("date"),
                notes=form_payload.get("notes"),
                created_by=form_payload.get("created_by"),
            )
        except (ValueError, sqlite3.IntegrityError) as e:
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Advance #{tx_id} recorded.")
        self._reload()

    # -- Apply Advance to a Sale --

    def _eligible_sales_for_application(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Return list of sales with remaining due > 0 for the customer.
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

    def _on_apply_advance(self):
        cid, db_path = self._preflight(require_active=True, require_file_db=True)
        if not cid or not db_path:
            return

        open_apply_advance_form = self._lazy_attr(
            "payments.ui.apply_advance_form.open_apply_advance_form",
            toast_title="Unavailable",
            on_fail="Apply-advance UI is not available. Please install payments.ui.apply_advance_form.",
        )
        if not open_apply_advance_form:
            return

        sales = self._eligible_sales_for_application(cid)
        form_payload = open_apply_advance_form(customer_id=cid, sales=sales, defaults=None)
        if not form_payload:
            return  # cancelled

        sale_id = form_payload.get("sale_id")
        amt = form_payload.get("amount_to_apply")
        if not sale_id or amt is None:
            info(self.view, "Required", "Please select a sale and enter an amount to apply.")
            return

        # Guard: ensure sale is valid for this customer and a real sale
        if not self._sale_belongs_to_customer_and_is_sale(sale_id, cid):
            info(self.view, "Invalid", "Credit can only be applied to SALES belonging to this customer.")
            return

        CustomerAdvancesRepo = self._lazy_attr(
            "inventory_management.database.repositories.customer_advances_repo.CustomerAdvancesRepo",
            toast_title="Error",
            on_fail="Could not load CustomerAdvancesRepo",
        )
        if not CustomerAdvancesRepo:
            return

        repo = CustomerAdvancesRepo(db_path)
        try:
            tx_id = repo.apply_credit_to_sale(
                customer_id=cid,
                sale_id=sale_id,
                amount=-abs(float(amt)),  # store as negative
                date=form_payload.get("date"),
                notes=form_payload.get("notes"),
                created_by=form_payload.get("created_by"),
            )
        except (ValueError, sqlite3.IntegrityError) as e:
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Advance application #{tx_id} recorded.")
        self._reload()

    # -- Payment / Credit History --

    def _on_payment_history(self):
        # History is allowed even if customer is inactive; file DB not strictly required
        cid, db_path = self._preflight(require_active=False, require_file_db=False)
        if not cid:
            return

        CustomerHistoryService = self._lazy_attr(
            "inventory_management.modules.customer.history.CustomerHistoryService",
            toast_title="Error",
            on_fail="Could not load history service",
        )
        if not CustomerHistoryService:
            return

        history_service = CustomerHistoryService(db_path or ":memory:")
        history_payload = history_service.full_history(cid)

        open_customer_history = self._lazy_attr(
            "payments.ui.payment_history_view.open_customer_history",
            toast_title="Unavailable",
            on_fail="Payment History UI is not available.",
        )
        if not open_customer_history:
            info(
                self.view,
                "Unavailable",
                "Payment History UI is not available. Returning data to logs/console.",
            )
            # Optional: print(history_payload)
            return

        open_customer_history(customer_id=cid, history=history_payload)
