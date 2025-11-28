from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel
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
from ...database.repositories.customers_repo import CustomersRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str, fmt_money
import os
import tempfile
import datetime
from PySide6.QtCore import QStandardPaths


def new_sale_id(conn: sqlite3.Connection, date_str: str) -> str:
    d = date_str.replace("-", "")
    prefix = f"SO{d}-"
    row = conn.execute(
        "SELECT MAX(sale_id) AS m FROM sales WHERE sale_id LIKE ?",
        (prefix + "%",),
    ).fetchone()
    last = int(row["m"].split("-")[-1]) if row and row["m"] else 0
    return f"{prefix}{last+1:04d}"


def new_quotation_id(conn: sqlite3.Connection, date_str: str) -> str:
    """
    Quotation IDs use prefix QO + yyyymmdd + -NNNN
    """
    d = date_str.replace("-", "")
    prefix = f"QO{d}-"
    row = conn.execute(
        "SELECT MAX(sale_id) AS m FROM sales WHERE sale_id LIKE ?",
        (prefix + "%",),
    ).fetchone()
    last = int(row["m"].split("-")[-1]) if row and row["m"] else 0
    return f"{prefix}{last+1:04d}"


class SalesController(BaseModule):
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

        # Controller-level state
        self._doc_type: str = "sale"   # 'sale' | 'quotation' (mirrors view toggle)
        self._search_text: str = ""    # current server-side search string
        self.active_dialog = None      # Track active dialog for non-modal operation

        # Repos using the shared connection
        self.repo = SalesRepo(conn)
        self.customers = CustomersRepo(conn)
        self.products = ProductsRepo(conn)

        # Optional repo for bank accounts (lazy import; safe if missing)
        self.bank_accounts = None
        try:
            from ...database.repositories.bank_accounts_repo import BankAccountsRepo  # type: ignore
            self.bank_accounts = BankAccountsRepo(conn)
        except Exception:
            self.bank_accounts = None

        # Path for path-based repos (payments/advances)
        self._db_path = self._get_db_path_from_conn(conn)

        self._wire()
        self._reload()

    # ---- internals --------------------------------------------------------

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
        except Exception:
            pass
        return ":memory:"

    def get_widget(self) -> QWidget:
        return self.view

    # ---- wiring / model ---------------------------------------------------

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.btn_return.clicked.connect(self._return)

        # Server-side search: on change, refetch from repo
        self.view.search.textChanged.connect(self._on_search_changed)

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
        # Let the model update its headers for the new document type
        self.base.set_doc_type(self._doc_type)
        # Let the details widget know (if it supports this)
        try:
            if hasattr(self.view, "details") and hasattr(self.view.details, "set_mode"):
                self.view.details.set_mode(self._doc_type)
        except Exception:
            pass
        self._update_action_states()
        self._reload()

    def _on_search_changed(self, text: str):
        self._search_text = text or ""
        self._reload()

    def _on_selection_changed(self, *_):
        # Enable/disable buttons then refresh details
        self._update_action_states()
        self._sync_details()

    def _update_action_states(self):
        """Guard toolbar buttons by selection and mode."""
        selected = self._selected_row() is not None

        # Always available
        if hasattr(self.view, "btn_edit"):
            self.view.btn_edit.setEnabled(selected)
        if hasattr(self.view, "btn_print"):
            self.view.btn_print.setEnabled(selected)

        # Sales-only actions
        allow_sales = (self._doc_type == "sale") and selected
        if hasattr(self.view, "btn_return"):
            self.view.btn_return.setEnabled(allow_sales)
        if hasattr(self.view, "btn_record_payment"):
            self.view.btn_record_payment.setEnabled(allow_sales)
        if hasattr(self.view, "btn_apply_credit"):
            self.view.btn_apply_credit.setEnabled(allow_sales)

        # Quotation-only action
        allow_convert = (self._doc_type == "quotation") and selected
        if hasattr(self.view, "btn_convert"):
            self.view.btn_convert.setEnabled(allow_convert)

    def _build_model(self):
        """
        Build the table model using server-side search (preferred).
        Falls back to list_* if search API is unavailable.
        """
        # Try repo.search_sales(query, doc_type=...)
        rows_to_use = None
        try:
            if hasattr(self.repo, "search_sales"):
                rows_to_use = list(self.repo.search_sales(self._search_text, doc_type=self._doc_type))
        except TypeError:
            # some implementations might have different signature; try (query, doc_type) kw-agnostic
            try:
                rows_to_use = list(self.repo.search_sales(self._search_text, self._doc_type))
            except Exception:
                rows_to_use = None
        except Exception:
            rows_to_use = None

        # Fallback behavior if search_sales is not available
        if rows_to_use is None:
            if self._doc_type == "quotation":
                try:
                    rows_to_use = list(self.repo.list_quotations())
                except Exception:
                    rows_to_use = []
            else:
                rows_to_use = list(self.repo.list_sales())

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

        # Build model & wire to view
        self.base = SalesTableModel(rows_to_use, doc_type=self._doc_type)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # no client-side filtering; server-side fetch above
        self.view.tbl.setModel(self.proxy)
        self.view.tbl.resizeColumnsToContents()

        # Selection model is recreated with each setModel; connect handlers every time
        sel = self.view.tbl.selectionModel()
        sel.selectionChanged.connect(self._on_selection_changed)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.tbl.selectRow(0)
        # Ensure buttons are correctly enabled/disabled and details are fresh
        self._update_action_states()
        self._sync_details()

    def _selected_row(self) -> dict | None:
        try:
            idxs = self.view.tbl.selectionModel().selectedRows()
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

    # --- small helper: fetch financials using calc view + header -----------
    def _fetch_sale_financials(self, sale_id: str) -> dict:
        """
        Returns a dict with:
          total_amount, paid_amount, advance_payment_applied,
          calculated_total_amount, remaining_due
        remaining_due = calculated_total_amount - paid_amount - advance_payment_applied (clamped ≥ 0)
        """
        row = self.conn.execute(
            """
            SELECT
              s.total_amount,
              COALESCE(s.paid_amount, 0.0)              AS paid_amount,
              COALESCE(s.advance_payment_applied, 0.0)  AS advance_payment_applied,
              COALESCE(sdt.calculated_total_amount, s.total_amount) AS calculated_total_amount
            FROM sales s
            LEFT JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id
            WHERE s.sale_id = ?;
            """,
            (sale_id,),
        ).fetchone()
        if not row:
            return {
                "total_amount": 0.0,
                "paid_amount": 0.0,
                "advance_payment_applied": 0.0,
                "calculated_total_amount": 0.0,
                "remaining_due": 0.0,
            }
        calc_total = float(row["calculated_total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        adv = float(row["advance_payment_applied"] or 0.0)
        remaining = max(0.0, calc_total - paid - adv)
        return {
            "total_amount": float(row["total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "calculated_total_amount": calc_total,
            "remaining_due": remaining,
        }

    def _sync_details(self, *args):
        r = self._selected_row()

        # default: nothing selected → clear subviews
        if not r:
            self.view.items.set_rows([])
            try:
                if hasattr(self.view, "payments"):
                    self.view.payments.set_rows([])
            except Exception:
                pass
            self.view.details.set_data(None)
            return

        # Always load item rows for the selected sale/quotation
        items = self.repo.list_items(r["sale_id"])
        line_disc = sum(float(it["quantity"]) * float(it["item_discount"]) for it in items)
        r = dict(r)
        r["overall_discount"] = float(r.get("order_discount") or 0.0) + line_disc

        # Returns summary for details panel (quotations naturally zero)
        try:
            rt = self.repo.sale_return_totals(r["sale_id"])
            r["returned_qty"] = float(rt.get("qty", 0.0))
            r["returned_value"] = float(rt.get("value", 0.0))
            r["net_after_returns"] = max(0.0, float(r.get("total_amount", 0.0)) - r["returned_value"])
        except Exception:
            r["returned_qty"] = 0.0
            r["returned_value"] = 0.0
            r["net_after_returns"] = float(r.get("total_amount", 0.0))

        self.view.items.set_rows(items)

        # ---- payments + customer credit (sales only) ----
        payments_rows: list[dict] = []
        if self._doc_type == "sale":
            # Payments list
            try:
                from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # type: ignore
                pay_repo = SalePaymentsRepo(self._db_path)
                payments_rows = list(pay_repo.list_by_sale(r["sale_id"])) or []
            except Exception:
                payments_rows = []

            # Customer credit balance
            try:
                from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo  # type: ignore
                adv_repo = CustomerAdvancesRepo(self._db_path)
                bal = adv_repo.get_balance(int(r.get("customer_id") or 0))
                r["customer_credit_balance"] = float(bal or 0.0)
            except Exception:
                r["customer_credit_balance"] = None

            # Financials including credit applied (NEW: include advance_payment_applied)
            fin = self._fetch_sale_financials(r["sale_id"])
            r["advance_payment_applied"] = fin["advance_payment_applied"]
            r["calculated_total_amount"] = fin["calculated_total_amount"]
            r["paid_plus_credit"] = fin["paid_amount"] + fin["advance_payment_applied"]
            r["remaining_due"] = fin["remaining_due"]
        else:
            # Quotation: explicitly pass empty payments and no credit balance
            payments_rows = []
            r.pop("customer_credit_balance", None)
            # Keep remaining_due aligned to quotations (0 by design)
            r["advance_payment_applied"] = 0.0
            r["paid_plus_credit"] = float(r.get("paid_amount") or 0.0)
            r["remaining_due"] = 0.0

        # Attach payments to the details payload
        r["payments"] = payments_rows

        # Feed the compact payments table on the left, if present
        try:
            if hasattr(self.view, "payments"):
                self.view.payments.set_rows(payments_rows)
        except Exception:
            pass

        # Finally update the details panel and its mode (if supported)
        try:
            if hasattr(self.view.details, "set_mode"):
                self.view.details.set_mode(self._doc_type)
        except Exception:
            pass
        self.view.details.set_data(r)

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
        Adapter used by customer.money dialog. Tries common repo shapes; returns list of {id, name}.
        """
        # Try repo methods if present
        try:
            if self.bank_accounts:
                for attr in ("list_accounts", "list", "list_all", "all"):
                    if hasattr(self.bank_accounts, attr):
                        rows = list(getattr(self.bank_accounts, attr)())
                        # Try to normalize to {id, name}
                        norm = []
                        for r in rows:
                            d = dict(r)
                            _id = d.get("id") or d.get("account_id") or d.get("bank_account_id")
                            _name = d.get("name") or d.get("account_name") or d.get("title")
                            if _id is not None and _name is not None:
                                norm.append({"id": int(_id), "name": str(_name)})
                        if norm:
                            return norm
        except Exception:
            pass
        # Fallback empty list
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
                    })
                return out
        except Exception:
            pass

        # Safe fallback SQL (keeps compatibility with existing schema used elsewhere in this module)
        try:
            cur = self.conn.execute(
                """
                SELECT sale_id, date, total_amount AS total, COALESCE(paid_amount,0.0) AS paid
                FROM sales
                WHERE customer_id = ?
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
                })
            return out
        except Exception:
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
        doc_type = self._doc_type

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
            qid = new_quotation_id(self.conn, p["date"])

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
                created_by=(self.user["user_id"] if self.user else None),
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
                self.repo.create_quotation(h, items)
                info(self.view, "Saved", f"Quotation {qid} created.")

                # Check if this was called from print or PDF export button
                should_print_after_save = p.get('_should_print', False)
                should_export_pdf_after_save = p.get('_should_export_pdf', False)

                # Handle print or PDF export request after saving (for now, just notify user about limitations)
                if should_print_after_save or should_export_pdf_after_save:
                    info(self.view, "Not Implemented", "Quotation printing/PDF export not yet implemented.")
            except Exception as e:
                info(self.view, "Error", f"Could not create quotation: {e}")
            self._reload()
            self._sync_details()
            return

        # --- sale path ---
        sid = new_sale_id(self.conn, p["date"])

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
            created_by=(self.user["user_id"] if self.user else None),
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

        # Persist header + items (inventory is posted by repo for sales)
        self.repo.create_sale(h, items)

        # Initial payment via SalePaymentsRepo (no header math)
        init_amt = float(p.get("initial_payment") or 0.0)
        if init_amt > 0:
            try:
                from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # lazy import
                pay_repo = SalePaymentsRepo(self._db_path)

                method = p.get("initial_method") or "Cash"
                kwargs = {
                    "sale_id": sid,
                    "amount": init_amt,
                    "method": method,
                    "date": p["date"],
                    "created_by": (self.user["user_id"] if self.user else None),
                    "notes": "[Init payment]",
                }

                # Method-specific fields
                if method == "Bank Transfer":
                    kwargs["bank_account_id"] = int(p["initial_bank_account_id"])
                    kwargs["instrument_no"] = p["initial_instrument_no"]
                    kwargs["instrument_type"] = p.get("initial_instrument_type", "online")
                else:
                    kwargs["instrument_type"] = "other"

                pay_repo.record_payment(**kwargs)
                info(self.view, "Saved", f"Sale {sid} created and initial payment recorded.")
            except Exception as e:
                # Sale is created; payment failed → notify clearly
                info(self.view, "Saved (with note)",
                     f"Sale {sid} created. Initial payment was not recorded: {e}")
        else:
            info(self.view, "Saved", f"Sale {sid} created.")

        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)

        # Handle print or PDF export request after saving
        if should_print_after_save:
            self._print_sale_invoice(sid)
        elif should_export_pdf_after_save:
            self._export_sale_invoice_to_pdf(sid)

        self._reload()
        self._sync_details()

    def _edit(self):
        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a row to edit.")
            return

        doc_type = self._doc_type

        # Store doc_type and selected row so the handler method knows the context
        self._pending_doc_type = doc_type
        self._pending_edit_row = r

        items = self.repo.list_items(r["sale_id"])

        # Get complete header with customer information
        header_with_customer = self.repo.get_header_with_customer(r["sale_id"])

        init = {
            "customer_id": r["customer_id"],
            "customer_name": header_with_customer.get("customer_name") if header_with_customer else None,
            "date": r["date"],
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
                    created_by=(self.user["user_id"] if self.user else None),
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
                    self.repo.update_quotation(h, items)  # should not post inventory
                    info(self.view, "Saved", f"Quotation {sid} updated.")
                except Exception as e:
                    info(self.view, "Error", f"Could not update quotation: {e}")
            else:
                info(self.view, "Not available",
                     "Updating quotations requires SalesRepo.update_quotation(...).")
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
            created_by=(self.user["user_id"] if self.user else None),
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
        self.repo.update_sale(h, items)

        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)

        # Handle print or PDF export request after saving
        if should_print_after_save:
            self._print_sale_invoice(sid)
        elif should_export_pdf_after_save:
            self._export_sale_invoice_to_pdf(sid)
        else:
            info(self.view, "Saved", f"Sale {sid} updated.")

        self._reload()
        self._sync_details()

    def _delete(self):
        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a row to delete.")
            return
        self.repo.delete_sale(r["sale_id"])
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
        date_for_so = today_str()  # you can change to reuse quotation date if you prefer
        so_id = new_sale_id(self.conn, date_for_so)

        try:
            self.repo.convert_quotation_to_sale(
                qo_id=qo_id,
                new_so_id=so_id,
                date=date_for_so,
                created_by=(self.user["user_id"] if self.user else None),
            )
            info(self.view, "Converted", f"{qo_id} → {so_id} created.")
        except Exception as e:
            info(self.view, "Error", f"Conversion failed: {e}")

        self._reload()
        self._sync_details()

    # ---- Payments / Printing ---------------------------------------------

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

        # Local dialog + actions (lazy import)
        try:
            from ...customer.receipt_dialog import open_payment_or_advance_form  # type: ignore
            from ...customer import actions as customer_actions  # type: ignore

            payload = open_payment_or_advance_form(
                mode="receipt",
                customer_id=customer_id,
                sale_id=sale_id,
                defaults={
                    "list_company_bank_accounts": self._list_company_bank_accounts,
                    "list_sales_for_customer": self._list_sales_for_customer,
                    "customer_display": customer_display,
                },
            )
            if payload:
                _ = customer_actions.receive_payment(
                    db_path=self._db_path,
                    sale_id=sale_id,
                    customer_id=customer_id,
                    with_ui=False,
                    form_defaults=payload,
                )
                self._reload()
                self._sync_details()
                return
        except Exception:
            info(
                self.view,
                "Payments UI not available",
                "The local customer money dialog isn't available. "
                "Enable modules.customer.receipt_dialog or use the Customers module.",
            )
            self._update_action_states()
            self._sync_details()

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

        # For now, only handle sales (not quotations)
        if doc_type == "sale":
            self._print_sale_invoice(sale_id)
        elif doc_type == "quotation":
            info(self.view, "Not Implemented", "Quotation printing not yet implemented.")

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

        # Local dialog + actions (lazy import)
        try:
            from ...customer.receipt_dialog import open_payment_or_advance_form  # type: ignore
            from ...customer import actions as customer_actions  # type: ignore

            payload = open_payment_or_advance_form(
                mode="apply_advance",
                customer_id=customer_id,
                sale_id=None,
                defaults={
                    "list_sales_for_customer": self._list_sales_for_customer,
                    "sales": self._eligible_sales_for_application(customer_id),
                },
            )
            if payload:
                _ = customer_actions.apply_customer_advance(
                    db_path=self._db_path,
                    customer_id=customer_id,
                    sale_id=str(payload["sale_id"]),
                    with_ui=False,
                    form_defaults={
                        "customer_id": customer_id,
                        "sale_id": payload["sale_id"],
                        "amount_to_apply": payload["amount"],
                        "date": payload.get("date"),
                        "notes": payload.get("notes"),
                        "created_by": payload.get("created_by"),
                    },
                )
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

    def _return(self):
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
        if selected:
            dlg = SaleReturnForm(self.view, repo=self.repo, sale_id=selected["sale_id"])
        else:
            dlg = SaleReturnForm(self.view, repo=self.repo)

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

        # 1) Inventory transactions
        self.repo.record_return(
            sid=sid,
            date=today_str(),
            created_by=(self.user["user_id"] if self.user else None),
            lines=lines,
            notes="[Return]",
        )

        # 2) Money side
        refund_amount = float(p.get("refund_amount") or 0.0)  # already order-discount prorated
        hdr = self.repo.get_header(sid) or {}
        paid_before = float(hdr.get("paid_amount") or 0.0)
        customer_id = int(hdr.get("customer_id") or 0)

        cash_refund = 0.0
        credit_part = refund_amount

        if p.get("refund_now"):
            cash_refund = min(refund_amount, paid_before)
            credit_part = max(0.0, refund_amount - cash_refund)

            if cash_refund > 0:
                try:
                    from ...database.repositories.sale_payments_repo import SalePaymentsRepo  # lazy import
                    pay_repo = SalePaymentsRepo(self._db_path)
                    pay_repo.record_payment(
                        sale_id=sid,
                        date=today_str(),
                        amount=-abs(cash_refund),
                        method="Cash",
                        instrument_type="other",
                        notes="[Return refund]",
                        created_by=(self.user["user_id"] if self.user else None),
                    )
                except Exception as e:
                    info(
                        self.view,
                        "Refund warning",
                        f"Inventory return saved, but cash refund could not be recorded: {e}",
                    )

        if credit_part > 0 and customer_id:
            try:
                from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo  # lazy import
                adv_repo = CustomerAdvancesRepo(self._db_path)
                adv_repo.add_return_credit(
                    customer_id=customer_id,
                    amount=credit_part,
                    sale_id=sid,
                    date=today_str(),
                    notes="[Return credit]",
                    created_by=(self.user["user_id"] if self.user else None),
                )
            except Exception as e:
                info(
                    self.view,
                    "Credit warning",
                    f"Inventory return saved, but customer credit could not be recorded: {e}",
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
        if p.get("refund_now"):
            if credit_part > 0:
                info(
                    self.view,
                    "Saved",
                    f"Return recorded. Refunded {fmt_money(cash_refund)} in cash; "
                    f"{fmt_money(credit_part)} added to customer credit.",
                )
            else:
                info(self.view, "Saved", f"Return recorded. Refunded {fmt_money(cash_refund)} in cash.")
        else:
            info(self.view, "Saved", f"Return recorded. {fmt_money(refund_amount)} added to customer credit.")

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

            # Get customer payment details using repository
            from ...database.repositories.sale_payments_repo import SalePaymentsRepo
            payments_repo = SalePaymentsRepo(self._db_path)

            # Get the latest payment directly using the dedicated method
            latest_payment = payments_repo.get_latest_payment_for_sale(sale_id)

            # Calculate paid amount and remaining
            paid_amount = float(doc_data.get('paid_amount', 0.0))
            total_amount = float(doc_data.get('total_amount', 0.0))
            advance_payment_applied = float(doc_data.get('advance_payment_applied', 0.0))
            # Calculate remaining properly by accounting for advance payments
            remaining = max(0.0, total_amount - paid_amount - advance_payment_applied)

            enriched_data['paid_amount'] = paid_amount
            enriched_data['advance_payment_applied'] = advance_payment_applied
            enriched_data['remaining'] = remaining

            # Get latest payment details and enhance with account names
            if latest_payment:
                latest_payment = dict(latest_payment)  # Convert to dict for modification

                # Add bank account labels if available
                if latest_payment.get('bank_account_id'):
                    try:
                        # Query the bank account directly from the database
                        bank_account_row = self.conn.execute(
                            "SELECT label FROM company_bank_accounts WHERE account_id = ?",
                            (latest_payment['bank_account_id'],)
                        ).fetchone()
                        if bank_account_row:
                            latest_payment['bank_account_label'] = bank_account_row['label']
                        else:
                            latest_payment['bank_account_label'] = 'N/A'
                    except Exception:
                        latest_payment['bank_account_label'] = 'N/A'

                enriched_data['initial_payment'] = latest_payment
            else:
                enriched_data['initial_payment'] = None

            # Add company info
            company_row = self.conn.execute(
                "SELECT company_name, logo_path FROM company_info WHERE company_id = 1"
            ).fetchone()

            if company_row:
                enriched_data['company'] = {
                    'name': company_row['company_name'],
                    'logo_path': company_row['logo_path']
                }
            else:
                enriched_data['company'] = {
                    'name': 'Your Company Name',
                    'logo_path': None
                }

            # Add payment status
            enriched_data['doc']['payment_status'] = doc_data.get('payment_status', 'Unpaid')

        # Create Jinja2 template and render
        template = Template(template_content, autoescape=True)
        html_content = template.render(**enriched_data)

        return html_content

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
        """Print the sale invoice using WeasyPrint for better rendering"""
        temp_pdf_path = None  # Initialize to None to ensure it's available in finally block
        try:
            # Generate HTML content using the shared helper - this can raise various exceptions
            html_content = self._generate_invoice_html_content(sale_id)

            # Only try to import and use WeasyPrint after HTML is successfully generated
            try:
                from weasyprint import HTML, CSS
            except ImportError:
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
                return

            # Sanitize the sale_id to prevent path traversal attacks in temp file prefix
            sanitized_sale_id = self._sanitize_filename(sale_id, max_length=50)  # Shorter for temp prefix

            # Create PDF in temporary location with proper naming
            temp_pdf_fd, temp_pdf_path = tempfile.mkstemp(suffix='.pdf', prefix=f'{sanitized_sale_id}_')
            os.close(temp_pdf_fd)  # Close the file descriptor

            # Convert HTML to PDF with custom CSS for proper margins
            # Use shared CSS constant from class
            custom_css = CSS(string=self._INVOICE_PDF_CSS)

            html_doc = HTML(string=html_content)
            html_doc.write_pdf(temp_pdf_path, stylesheets=[custom_css])

            # Open the PDF in default PDF viewer (to allow printing)
            import subprocess
            import sys
            import platform

            if platform.system() == 'Windows':
                os.startfile(temp_pdf_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', temp_pdf_path])
            else:  # Linux and other Unix-like
                subprocess.run(['xdg-open', temp_pdf_path])

            info(self.view, "Print", "A temporary PDF was created and opened for printing.")

        except Exception as e:
            # Check if this is specifically an ImportError for WeasyPrint (shouldn't happen with new structure)
            # but keep this for safety
            if "weasyprint" in str(e).lower():
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
            else:
                info(self.view, "Error", f"Could not print invoice: {e}")
        finally:
            # Ensure temporary file is removed after some time to allow PDF viewer to access it
            # Use a background thread to delay the deletion
            try:
                if temp_pdf_path is not None:
                    import threading
                    import time

                    def delayed_delete(file_path):
                        # Wait for a few seconds to allow the PDF viewer to open the file
                        time.sleep(5)
                        try:
                            os.remove(file_path)
                        except OSError:
                            # If file removal fails, silently ignore
                            # since the primary operation (printing) has already happened
                            pass

                    # Start the delayed deletion in a background thread
                    deletion_thread = threading.Thread(target=delayed_delete, args=(temp_pdf_path,))
                    deletion_thread.daemon = True  # Make it a daemon thread so it doesn't prevent program exit
                    deletion_thread.start()
            except Exception:
                # If setting up delayed deletion fails, silently ignore
                pass

    def _export_sale_invoice_to_pdf(self, sale_id: str):
        """Export the sale invoice to PDF using WeasyPrint for better rendering"""
        try:
            # Generate HTML content using the shared helper - this can raise various exceptions
            html_content = self._generate_invoice_html_content(sale_id)

            # Only try to import and use WeasyPrint after HTML is successfully generated
            try:
                from weasyprint import HTML, CSS
            except ImportError:
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
                return

            # Determine the desktop path and create SIs (Sale Invoices) subdirectory
            desktop_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            pdfs_dir = os.path.join(desktop_path, "SIs")

            # Create the directory if it doesn't exist
            os.makedirs(pdfs_dir, exist_ok=True)

            # Sanitize the sale_id to prevent path traversal attacks
            sanitized_sale_id = self._sanitize_filename(sale_id, max_length=100)

            # Create a unique filename by appending a timestamp to avoid collisions
            # Use Pakistani Standard Time (PKT) for the timestamp
            import zoneinfo
            pk_time = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Karachi"))
            timestamp = pk_time.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # YYYYMMDD_HHMMSS_mmm format
            file_name = f"{sanitized_sale_id}_{timestamp}.pdf"
            file_path = os.path.join(pdfs_dir, file_name)

            # Convert HTML to PDF using WeasyPrint with custom CSS for proper margins
            # Use shared CSS constant from class
            custom_css = CSS(string=self._INVOICE_PDF_CSS)

            html_doc = HTML(string=html_content)
            html_doc.write_pdf(file_path, stylesheets=[custom_css])

            info(self.view, "Exported", f"Sale invoice exported to: {file_path}")

        except Exception as e:
            # Check if this is specifically an ImportError for WeasyPrint (shouldn't happen with new structure)
            # but keep this for safety
            if "weasyprint" in str(e).lower():
                info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
            else:
                info(self.view, "Error", f"Could not export invoice to PDF: {e}")

