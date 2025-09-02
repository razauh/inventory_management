from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel
import sqlite3

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
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        self.conn = conn
        self.user = current_user
        self.view = SalesView()

        # Controller-level state
        self._doc_type: str = "sale"   # 'sale' | 'quotation' (mirrors view toggle)
        self._search_text: str = ""    # current server-side search string

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
        # NEW: Apply Credit button (sales mode only)
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
                d.setdefault("paid_amount", 0.0)
                qstat = d.get("quotation_status") or d.get("payment_status") or "—"
                d["payment_status"] = qstat
                norm.append(d)
            rows_to_use = norm

        # Build model & wire to view
        self.base = SalesTableModel(rows_to_use)
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
        return self.base.at(src.row())

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
                kwargs2 = {"customers": self.customers, "products": self.products}
                if initial is not None:
                    kwargs2["initial"] = initial
                return SaleForm(self.view, **kwargs2)
            except TypeError:
                try:
                    return SaleForm(self.view)
                except Exception:
                    return None

    # ---- CRUD -------------------------------------------------------------

    def _add(self):
        doc_type = self._doc_type

        dlg = self._open_sale_form(as_quotation=(doc_type == "quotation"))
        if dlg is None:
            info(self.view, "Error", "Sale form could not be opened.")
            return

        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

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

        self._reload()
        self._sync_details()

    def _edit(self):
        r = self._selected_row()
        if not r:
            info(self.view, "Select", "Select a row to edit.")
            return

        doc_type = self._doc_type

        items = self.repo.list_items(r["sale_id"])
        init = {
            "customer_id": r["customer_id"],
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

        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

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
        """
        doc_type = self._doc_type
        if doc_type != "sale":
            info(self.view, "Not available", "Payments are not available for quotations.")
            return

        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a sale first.")
            return

        sale_id = row["sale_id"]

        # Prefer the dedicated payments dialog if present
        try:
            from ...payments.ui.customer_receipt_form import CustomerReceiptForm  # type: ignore

            dlg = None
            for args in (
                (self.view, sale_id, self._db_path),
                (self.view, sale_id, self.conn),
                (self.view, sale_id),
                (self.view,),
            ):
                try:
                    dlg = CustomerReceiptForm(*args)
                    break
                except TypeError:
                    dlg = None

            if dlg is None:
                raise RuntimeError("CustomerReceiptForm constructor not recognized.")

            if hasattr(dlg, "set_sale_id"):
                try:
                    dlg.set_sale_id(sale_id)
                except Exception:
                    pass

            dlg.exec()
            self._reload()
            self._sync_details()
            return
        except Exception:
            info(
                self.view,
                "Payments UI not available",
                "The payments dialog isn't wired in this build. "
                "Open the Payments module to record a receipt.",
            )
            # Even if dialog isn't available, keep UI in a sane state
            self._update_action_states()
            self._sync_details()

    def _print(self):
        """
        Route to the appropriate template based on mode.
        """
        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a row to print.")
            return

        doc_type = self._doc_type
        sale_id = row["sale_id"]

        # Choose template
        if doc_type == "quotation":
            template = "resources/templates/invoices/quotation_invoice.html"
            window_title = f"Quotation — {sale_id}"
        else:
            template = "resources/templates/invoices/sale_invoice.html"
            window_title = f"Sale Invoice — {sale_id}"

        # Try a printing controller first
        try:
            from ...printing.controller import PrintingController  # type: ignore

            pc = PrintingController(self.conn)
            if hasattr(pc, "preview_invoice"):
                pc.preview_invoice(template, {"sale_id": sale_id})
                return
            # Optional aliases if your controller has specialized methods
            if doc_type == "quotation" and hasattr(pc, "print_quotation"):
                pc.print_quotation(sale_id)
                return
            if doc_type == "sale" and hasattr(pc, "print_sale"):
                pc.print_sale(sale_id)
                return
            raise RuntimeError("No suitable printing method found on PrintingController.")
        except Exception:
            pass

        # Fallback to invoice preview widget if available
        try:
            from ...widgets.invoice_preview import InvoicePreview  # type: ignore
            w = InvoicePreview(template, {"sale_id": sale_id})
            w.setWindowTitle(window_title)
            w.show()  # non-modal
            return
        except Exception:
            info(
                self.view,
                "Printing not configured",
                "Printing/preview is not wired in this build. "
                "Use the Printing module to preview/print.",
            )

        # After printing attempt, keep states fresh
        self._update_action_states()
        self._sync_details()

    # ---- Apply Credit to Sale (NEW) ---------------------------------------

    def _on_apply_credit(self):
        """
        Apply existing customer credit to the currently selected SALE.

        Workflow:
          1) Validate selection and mode.
          2) Fetch customer's credit balance and sale remaining due.
          3) Open 'Apply Credit' UI (lazy import). If available, collect amount.
          4) Call CustomerAdvancesRepo.apply_credit_to_sale (amount stored as NEGATIVE).
          5) Reload & refresh view so totals reflect the change.
        """
        if self._doc_type != "sale":
            info(self.view, "Not available", "Apply Credit is available for sales only.")
            return

        row = self._selected_row()
        if not row:
            info(self.view, "Select", "Select a sale first.")
            return

        sale_id = row["sale_id"]
        customer_id = int(row.get("customer_id") or 0)
        if not customer_id:
            info(self.view, "Missing data", "Selected sale is missing customer information.")
            return

        # Fetch financials for this sale (includes advance_payment_applied)
        fin = self._fetch_sale_financials(sale_id)
        remaining_due = float(fin["remaining_due"])

        # Fetch customer's available credit balance via repo (lazy import path-based)
        try:
            from ...database.repositories.customer_advances_repo import CustomerAdvancesRepo  # type: ignore
            adv_repo = CustomerAdvancesRepo(self._db_path)
            credit_balance = float(adv_repo.get_balance(customer_id) or 0.0)
        except Exception as e:
            info(self.view, "Unavailable", f"Could not fetch customer credit balance: {e}")
            return

        if remaining_due <= 0.0:
            info(self.view, "Nothing due", "This sale has no remaining due.")
            return

        if credit_balance <= 0.0:
            info(self.view, "No credit", "Customer has no available credit to apply.")
            return

        # Prefer a dedicated UI if present (same one used in Customers module)
        try:
            from ...payments.ui.apply_advance_form import open_apply_advance_form  # type: ignore

            # Build a minimal 'sales' list matching expected shape of the dialog
            sales_payload = [{
                "sale_id": sale_id,
                "date": row.get("date"),
                "remaining_due": remaining_due,
                "total": float(fin["calculated_total_amount"]),
                "paid": float(fin["paid_amount"]),
            }]
            defaults = {
                "sale_id": sale_id,
                "amount_to_apply": min(remaining_due, credit_balance),
                "date": today_str(),
                "notes": "[Apply credit]",
            }
            form_payload = open_apply_advance_form(
                customer_id=customer_id,
                sales=sales_payload,
                defaults=defaults,
            )
            if not form_payload:
                return  # cancelled

            amt = form_payload.get("amount_to_apply")
            if amt is None or float(amt) <= 0:
                info(self.view, "Required", "Please enter a positive amount to apply.")
                return

            # Persist application (store negative amount in ledger)
            try:
                tx_id = adv_repo.apply_credit_to_sale(
                    customer_id=customer_id,
                    sale_id=sale_id,
                    amount=-abs(float(amt)),
                    date=form_payload.get("date"),
                    notes=form_payload.get("notes"),
                    created_by=(self.user["user_id"] if self.user else None),
                )
            except (ValueError, sqlite3.IntegrityError) as e:
                info(self.view, "Not applied", str(e))
                return

            info(self.view, "Saved", f"Credit application #{tx_id} recorded.")
            self._reload()
            self._sync_details()
            return

        except Exception:
            # No UI available; inform the user rather than guessing inputs
            info(
                self.view,
                "Apply Credit UI not available",
                "The Apply Credit dialog isn't wired in this build. "
                "Open the Customers module to apply credit from there.",
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

        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

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
