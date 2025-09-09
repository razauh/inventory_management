from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
import sqlite3, datetime
from typing import Optional

from ..base_module import BaseModule
from .view import PurchaseView
from .model import PurchasesTableModel
from .form import PurchaseForm
from .return_form import PurchaseReturnForm
from .payments import PurchasePaymentDialog
from ...database.repositories.purchases_repo import PurchasesRepo, PurchaseHeader, PurchaseItem
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.products_repo import ProductsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str


def new_purchase_id(conn: sqlite3.Connection, date_str: str) -> str:
    # prefix by selected business date
    d = date_str.replace("-", "")
    prefix = f"PO{d}-"
    row = conn.execute("SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?", (prefix + "%",)).fetchone()
    if row and row["m"]:
        try:
            last = int(row["m"].split("-")[-1])
        except Exception:
            last = 0
    else:
        last = 0
    return f"{prefix}{last+1:04d}"


class PurchaseController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        self.conn = conn
        self.user = current_user
        self.view = PurchaseView()
        self.repo = PurchasesRepo(conn)
        self.payments = PurchasePaymentsRepo(conn)
        self.vadv = VendorAdvancesRepo(conn)
        self.vendors = VendorsRepo(conn)
        self.products = ProductsRepo(conn)
        self._wire()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.btn_return.clicked.connect(self._return)
        self.view.btn_pay.clicked.connect(self._payment)
        self.view.search.textChanged.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_purchases()
        self.base = PurchasesTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.tbl.setModel(self.proxy)
        self.view.tbl.resizeColumnsToContents()
        sel = self.view.tbl.selectionModel()
        try:
            sel.selectionChanged.disconnect(self._sync_details)
        except (TypeError, RuntimeError):
            pass
        sel.selectionChanged.connect(self._sync_details)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.tbl.selectRow(0)
        else:
            self.view.details.set_data(None)
            self.view.items.set_rows([])

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_row_dict(self) -> dict | None:
        idxs = self.view.tbl.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row())

    def _sync_details(self, *args):
        row = self._selected_row_dict()
        self.view.details.set_data(row)
        if row:
            self.view.items.set_rows(self.repo.list_items(row["purchase_id"]))
        else:
            self.view.items.set_rows([])

    # --- helper: returnable qty per item_id for a purchase ---
    def _returnable_map(self, purchase_id: str) -> dict[int, float]:
        sql = """
        SELECT
          pi.item_id,
          CAST(pi.quantity AS REAL) -
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='purchase_return'
              AND it.reference_table='purchases'
              AND it.reference_id = pi.purchase_id
              AND it.reference_item_id = pi.item_id
          ), 0.0) AS returnable
        FROM purchase_items pi
        WHERE pi.purchase_id=?
        """
        rows = self.conn.execute(sql, (purchase_id,)).fetchall()
        return {int(r["item_id"]): float(r["returnable"]) for r in rows}

    # --- helper: fetch a payment and ensure it belongs to selected purchase ---
    def _get_payment(self, payment_id: int) -> Optional[dict]:
        row = self._selected_row_dict()
        if not row:
            return None
        sql = """
        SELECT *
        FROM purchase_payments
        WHERE payment_id=? AND purchase_id=?
        """
        r = self.conn.execute(sql, (payment_id, row["purchase_id"])).fetchone()
        # Normalize to plain dict so downstream code can safely use .get(...)
        return dict(r) if r is not None else None

    # --- helper: financials for purchase (for open-purchases adapter) ---
    def _fetch_purchase_financials(self, purchase_id: str) -> dict:
        """
        Returns: total_amount, paid_amount, advance_payment_applied, calculated_total_amount, remaining_due
        remaining_due = calculated_total_amount - paid_amount - advance_payment_applied (clamped ≥ 0)
        """
        row = self.conn.execute(
            """
            SELECT
              p.total_amount,
              COALESCE(p.paid_amount, 0.0)              AS paid_amount,
              COALESCE(p.advance_payment_applied, 0.0)  AS advance_payment_applied,
              COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?;
            """,
            (purchase_id,),
        ).fetchone()
        if not row:
            return {
                "total_amount": 0.0,
                "paid_amount": 0.0,
                "advance_payment_applied": 0.0,
                "calculated_total_amount": 0.0,
                "remaining_due": 0.0,
            }
        calc = float(row["calculated_total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        adv = float(row["advance_payment_applied"] or 0.0)
        rem = max(0.0, calc - paid - adv)
        return {
            "total_amount": float(row["total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "calculated_total_amount": calc,
            "remaining_due": rem,
        }

    # -------- CRUD --------
    def _add(self):
        dlg = PurchaseForm(self.view, vendors=self.vendors, products=self.products)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

        pid = new_purchase_id(self.conn, p["date"])

        # Build header (totals will be recalculated inside repo.create_purchase; payment fields are enforced to unpaid/0)
        h = PurchaseHeader(
            purchase_id=pid,
            vendor_id=p["vendor_id"],
            date=p["date"],
            total_amount=p.get("total_amount", 0.0),
            order_discount=p.get("order_discount", 0.0),
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=p.get("notes"),
            created_by=(self.user["user_id"] if self.user else None),
        )
        items = [
            PurchaseItem(
                None,
                pid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["purchase_price"],
                it["sale_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]

        # 1) Create purchase (header + items + inventory with sequential txn_seq)
        self.repo.create_purchase(h, items)

        # 2) Optional initial payment
        #    Prefer the new nested contract if present; fall back to legacy flat fields for backward compatibility.
        ip = p.get("initial_payment")
        if isinstance(ip, dict) and float(ip.get("amount") or 0.0) > 0:
            try:
                self.payments.record_payment(
                    purchase_id=pid,
                    amount=float(ip["amount"]),
                    method=ip["method"],
                    bank_account_id=ip.get("bank_account_id"),
                    vendor_bank_account_id=ip.get("vendor_bank_account_id"),
                    instrument_type=ip.get("instrument_type"),
                    instrument_no=ip.get("instrument_no"),
                    instrument_date=ip.get("instrument_date"),
                    deposited_date=ip.get("deposited_date"),
                    cleared_date=ip.get("cleared_date"),
                    clearing_state=ip.get("clearing_state"),
                    ref_no=ip.get("ref_no"),
                    notes=ip.get("notes"),
                    date=ip.get("date") or p["date"],
                    created_by=(self.user["user_id"] if self.user else None),
                )
            except sqlite3.IntegrityError as e:
                info(
                    self.view,
                    "Payment not recorded",
                    f"Purchase {pid} was created, but the initial payment could not be saved:\n{e}",
                )
            except sqlite3.OperationalError as e:
                info(
                    self.view,
                    "Payment not recorded",
                    f"Purchase {pid} was created, but the initial payment hit a database error:\n{e}",
                )
        else:
            # Legacy flat fields path (kept to avoid breaking older forms/controllers)
            initial_paid = float(p.get("initial_payment") or 0.0)
            if initial_paid > 0:
                method = p.get("initial_method") or "Cash"
                bank_account_id = p.get("initial_bank_account_id")
                vendor_bank_account_id = p.get("initial_vendor_bank_account_id")

                instrument_type = p.get("initial_instrument_type")
                if not instrument_type:
                    if method == "Bank Transfer":
                        instrument_type = "online"
                    elif method == "Cheque":
                        instrument_type = "cross_cheque"
                    elif method == "Cash Deposit":
                        instrument_type = "cash_deposit"
                    else:
                        instrument_type = None

                instrument_no = p.get("initial_instrument_no")
                instrument_date = p.get("initial_instrument_date")
                deposited_date = p.get("initial_deposited_date")
                cleared_date = p.get("initial_cleared_date")
                clearing_state = p.get("initial_clearing_state")
                ref_no = p.get("initial_ref_no")
                pay_notes = p.get("initial_payment_notes")

                try:
                    self.payments.record_payment(
                        purchase_id=pid,
                        amount=initial_paid,
                        method=method,
                        bank_account_id=bank_account_id,
                        vendor_bank_account_id=vendor_bank_account_id if method in ("Bank Transfer", "Cheque", "Cash Deposit") else None,
                        instrument_type=instrument_type,
                        instrument_no=instrument_no,
                        instrument_date=instrument_date,
                        deposited_date=deposited_date,
                        cleared_date=cleared_date,
                        clearing_state=clearing_state,
                        ref_no=ref_no,
                        notes=pay_notes,
                        date=p["date"],
                        created_by=(self.user["user_id"] if self.user else None),
                    )
                except sqlite3.IntegrityError as e:
                    info(
                        self.view,
                        "Payment not recorded",
                        f"Purchase {pid} was created, but the initial payment could not be saved:\n{e}",
                    )
                except sqlite3.OperationalError as e:
                    info(
                        self.view,
                        "Payment not recorded",
                        f"Purchase {pid} was created, but the initial payment hit a database error:\n{e}",
                    )

        # 3) Optional initial vendor credit application
        init_credit = float(p.get("initial_credit_amount") or 0.0)
        if init_credit > 0:
            try:
                self.vadv.apply_credit_to_purchase(
                    vendor_id=p["vendor_id"],
                    purchase_id=pid,
                    amount=init_credit,
                    date=p["date"],
                    notes=p.get("initial_credit_notes"),
                    created_by=(self.user["user_id"] if self.user else None),
                )
            except sqlite3.IntegrityError as e:
                info(self.view, "Credit not applied", f"Purchase {pid} was created, but vendor credit could not be applied:\n{e}")
            except sqlite3.OperationalError as e:
                info(self.view, "Credit not applied", f"Purchase {pid} was created, but a database error occurred while applying credit:\n{e}")

        info(self.view, "Saved", f"Purchase {pid} created.")
        self._reload()

    def _edit(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to edit.")
            return
        # existing items + header
        items = self.repo.list_items(row["purchase_id"])
        init = {
            "vendor_id": row["vendor_id"],
            "date": row["date"],
            "order_discount": row["order_discount"],
            "notes": row.get("notes"),
            "items": [
                {
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "quantity": it["quantity"],
                    "purchase_price": it["purchase_price"],
                    "sale_price": it["sale_price"],
                    "item_discount": it["item_discount"],
                }
                for it in items
            ],
        }
        dlg = PurchaseForm(self.view, vendors=self.vendors, products=self.products, initial=init)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return
        pid = row["purchase_id"]
        h = PurchaseHeader(
            purchase_id=pid,
            vendor_id=p["vendor_id"],
            date=p["date"],
            total_amount=p["total_amount"],
            order_discount=p["order_discount"],
            payment_status=row["payment_status"],
            paid_amount=row["paid_amount"],
            advance_payment_applied=row["advance_payment_applied"],
            notes=p["notes"],
            created_by=(self.user["user_id"] if self.user else None),
        )
        items = [
            PurchaseItem(
                None,
                pid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["purchase_price"],
                it["sale_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]
        self.repo.update_purchase(h, items)
        info(self.view, "Saved", f"Purchase {pid} updated.")
        self._reload()

    def _delete(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to delete.")
            return
        self.repo.delete_purchase(row["purchase_id"])
        info(self.view, "Deleted", f'Purchase {row["purchase_id"]} removed.')
        self._reload()

    # -------- Returns --------
    def _return(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to return items from.")
            return

        pid = row["purchase_id"]
        items = self.repo.list_items(pid)

        # Compute returnable map and attach to rows (form can show/validate)
        returnable = self._returnable_map(pid)
        items_for_form = []
        for it in items:
            it2 = dict(it)
            it2["returnable"] = float(returnable.get(it["item_id"], 0.0))
            items_for_form.append(it2)

        dlg = PurchaseReturnForm(self.view, items_for_form)
        if not dlg.exec():
            return
        payload = dlg.payload()
        if not payload:
            return

        # map lines to include product_id + uom_id from original items
        by_id = {it["item_id"]: it for it in items}
        lines = []
        for ln in payload["lines"]:
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

        # Pass settlement info (refund/credit_note + instrument meta) straight to repo
        settlement = payload.get("settlement")

        try:
            self.repo.record_return(
                pid=pid,
                date=payload["date"],
                created_by=(self.user["user_id"] if self.user else None),
                lines=lines,
                notes=payload.get("notes"),
                settlement=settlement,
            )
        except (ValueError, sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Return not recorded", f"Could not record return:\n{e}")
            return

        info(self.view, "Saved", "Return recorded.")
        self._reload()

    # -------- Vendor credit action (UI can wire this later) --------
    def apply_vendor_credit(self, *, amount: float, date: Optional[str] = None, notes: Optional[str] = None):
        """
        Apply existing vendor credit to the selected purchase.
        - Positive `amount` is required.
        - Does NOT touch header money fields; DB triggers roll up advance_payment_applied.

        Intended to be called from a future UI action (e.g. a button/menu).
        """
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to apply vendor credit.")
            return

        try:
            amt = float(amount)
        except (TypeError, ValueError):
            info(self.view, "Invalid amount", "Enter a valid positive amount to apply as credit.")
            return

        if amt <= 0:
            info(self.view, "Invalid amount", "Amount must be greater than zero.")
            return

        when = date or today_str()
        try:
            self.vadv.apply_credit_to_purchase(
                vendor_id=int(row["vendor_id"]),
                purchase_id=row["purchase_id"],
                amount=amt,
                date=when,
                notes=notes,
                created_by=(self.user["user_id"] if self.user else None),
            )
        except sqlite3.IntegrityError as e:
            # Likely insufficient credit (trigger trg_vendor_advances_no_overdraw)
            info(self.view, "Credit not applied", f"Could not apply vendor credit:\n{e}")
            return
        except sqlite3.OperationalError as e:
            info(self.view, "Credit not applied", f"A database error occurred:\n{e}")
            return

        info(self.view, "Saved", f"Applied vendor credit of {amt:g} to {row['purchase_id']}.")
        self._reload()

    # -------- Payments (UPDATED to use Vendor money dialog) --------
    def _payment(self):
        """
        Record a payment (or refund) using PurchasePaymentsRepo.

        Preferred: open the vendor money dialog (mode="payment") and forward its payload to the repo.
        Fallback: keep the legacy amount-only dialog to avoid breaking existing flows.
        """
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to record payment.")
            return

        purchase_id = str(row["purchase_id"])
        vendor_id = int(row.get("vendor_id") or 0)
        vendor_display = str(row.get("vendor_name") or vendor_id)

        # --- Preferred path: new vendor money dialog (lazy import) ---
        try:
            from ...vendor.payment_dialog import open_vendor_money_form  # type: ignore

            payload = open_vendor_money_form(
                mode="payment",
                vendor_id=vendor_id,
                purchase_id=purchase_id,  # allow the dialog to pick if you pass None
                defaults={
                    "list_company_bank_accounts": self._list_company_bank_accounts,
                    "list_vendor_bank_accounts": self._list_vendor_bank_accounts,
                    "list_open_purchases_for_vendor": self._list_open_purchases_for_vendor,
                    "vendor_display": vendor_display,
                },
            )
            if payload:
                try:
                    self.payments.record_payment(
                        purchase_id=str(payload.get("purchase_id") or purchase_id),
                        amount=float(payload.get("amount")),
                        method=payload.get("method"),
                        bank_account_id=payload.get("bank_account_id"),
                        vendor_bank_account_id=payload.get("vendor_bank_account_id"),
                        instrument_type=payload.get("instrument_type"),
                        instrument_no=payload.get("instrument_no"),
                        instrument_date=payload.get("instrument_date"),
                        deposited_date=payload.get("deposited_date"),
                        cleared_date=payload.get("cleared_date"),
                        clearing_state=payload.get("clearing_state"),
                        ref_no=payload.get("ref_no"),
                        notes=payload.get("notes"),
                        date=payload.get("date") or today_str(),
                        created_by=(self.user["user_id"] if self.user else None),
                    )
                except (TypeError, ValueError):
                    info(self.view, "Payment not recorded", "Incomplete form data returned from Vendor dialog.")
                    return
                except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
                    info(self.view, "Payment not recorded", f"Could not record payment:\n{e}")
                    return

                info(self.view, "Saved", "Payment recorded.")
                self._reload()
                return
        except Exception:
            # Fall through to legacy path
            pass

        # --- Fallback: legacy amount-only dialog (kept for compatibility) ---
        dlg = PurchasePaymentDialog(
            self.view,
            current_paid=float(row["paid_amount"]),
            total=float(row["total_amount"]),
        )
        if not dlg.exec():
            return
        amount = dlg.payload()
        if not amount:
            return

        # Legacy path always used Cash / posted; keep that behavior unchanged.
        method = "Cash"
        bank_account_id = None
        vendor_bank_account_id = None
        instrument_type = None
        instrument_no = None
        instrument_date = None
        deposited_date = None
        cleared_date = None
        clearing_state = None
        ref_no = None
        notes = None
        pay_date = today_str()

        try:
            self.payments.record_payment(
                purchase_id=purchase_id,
                amount=float(amount),
                method=method,
                bank_account_id=bank_account_id,
                vendor_bank_account_id=vendor_bank_account_id,
                instrument_type=instrument_type,
                instrument_no=instrument_no,
                instrument_date=instrument_date,
                deposited_date=deposited_date,
                cleared_date=cleared_date,
                clearing_state=clearing_state,
                ref_no=ref_no,
                notes=notes,
                date=pay_date,
                created_by=(self.user["user_id"] if self.user else None),
            )
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Payment not recorded", f"Could not record payment:\n{e}")
            return

        info(self.view, "Saved", f"Transaction of {float(amount):g} recorded.")
        self._reload()

    # -------- Clearing endpoints (pending → cleared / bounced) --------
    def mark_payment_cleared(self, payment_id: int, *, cleared_date: Optional[str] = None, notes: Optional[str] = None):
        """
        Mark a pending payment as CLEARED.
        - Requires the payment to belong to the currently selected purchase.
        - Sets cleared_date to today if not provided.
        """
        pay = self._get_payment(payment_id)
        if not pay:
            info(self.view, "Not found", "Select a purchase and a valid payment to clear.")
            return
        if (pay.get("clearing_state") or "posted") != "pending":
            info(self.view, "Not allowed", "Only pending payments can be marked as cleared.")
            return

        when = cleared_date or today_str()
        try:
            changed = self.payments.update_clearing_state(
                payment_id=payment_id,
                clearing_state="cleared",
                cleared_date=when,
                notes=notes,
            )
            if not changed:
                info(self.view, "No change", "Payment was not updated.")
                return
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Update failed", f"Could not mark payment cleared:\n{e}")
            return

        info(self.view, "Saved", f"Payment #{payment_id} marked as cleared.")
        self._reload()

    def mark_payment_bounced(self, payment_id: int, *, notes: Optional[str] = None):
        """
        Mark a pending payment as BOUNCED.
        - Requires the payment to belong to the currently selected purchase.
        - Does not set cleared_date.
        """
        pay = self._get_payment(payment_id)
        if not pay:
            info(self.view, "Not found", "Select a purchase and a valid payment to mark bounced.")
            return
        if (pay.get("clearing_state") or "posted") != "pending":
            info(self.view, "Not allowed", "Only pending payments can be marked as bounced.")
            return

        try:
            changed = self.payments.update_clearing_state(
                payment_id=payment_id,
                clearing_state="bounced",
                cleared_date=None,
                notes=notes,
            )
            if not changed:
                info(self.view, "No change", "Payment was not updated.")
                return
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Update failed", f"Could not mark payment bounced:\n{e}")
            return

        info(self.view, "Saved", f"Payment #{payment_id} marked as bounced.")
        self._reload()

    # -------- Adapters for Vendor dialog defaults (lazy, safe) --------
    def _list_company_bank_accounts(self) -> list[dict]:
        """
        Returns [{id, name}] for company bank accounts.
        Lazy-imports a bank accounts repo if present. Safe empty list on failure.
        """
        try:
            from ...database.repositories.bank_accounts_repo import BankAccountsRepo  # type: ignore
            repo = BankAccountsRepo(self.conn)
            # Try common method names
            for attr in ("list_accounts", "list", "list_all", "all"):
                if hasattr(repo, attr):
                    rows = list(getattr(repo, attr)())
                    out = []
                    for r in rows:
                        d = dict(r)
                        _id = d.get("id") or d.get("account_id") or d.get("bank_account_id")
                        _name = d.get("name") or d.get("account_name") or d.get("title")
                        if _id is not None and _name is not None:
                            out.append({"id": int(_id), "name": str(_name)})
                    if out:
                        return out
        except Exception:
            pass
        return []

    def _list_vendor_bank_accounts(self, vendor_id: int) -> list[dict]:
        """
        Returns [{id, name}] for a vendor's bank accounts (if your app supports it).
        Safe empty list on failure or if repo not present.
        """
        try:
            from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo  # type: ignore
            repo = VendorBankAccountsRepo(self.conn)
            rows = []
            for attr in ("list_by_vendor", "list_for_vendor", "list"):
                if hasattr(repo, attr):
                    try:
                        rows = list(getattr(repo, attr)(vendor_id))
                    except TypeError:
                        # some repos use keyword arg
                        try:
                            rows = list(getattr(repo, attr)(vendor_id=vendor_id))
                        except Exception:
                            rows = []
                    break
            out = []
            for r in rows:
                d = dict(r)
                _id = d.get("id") or d.get("vendor_bank_account_id") or d.get("account_id")
                _name = d.get("name") or d.get("account_name") or d.get("title") or d.get("iban") or d.get("account_no")
                if _id is not None and _name is not None:
                    out.append({"id": int(_id), "name": str(_name)})
            return out
        except Exception:
            return []

    def _list_open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        """
        Returns a list of open purchases for a vendor with remaining due > 0.
        Shape: {purchase_id, date, total, paid, remaining_due}
        """
        out: list[dict] = []
        try:
            cur = self.conn.execute(
                "SELECT purchase_id, date, total_amount AS total, COALESCE(paid_amount,0) AS paid, COALESCE(advance_payment_applied,0) AS adv "
                "FROM purchases WHERE vendor_id = ? ORDER BY date DESC, purchase_id DESC LIMIT 300;",
                (vendor_id,),
            )
            for row in cur.fetchall():
                pid = str(row["purchase_id"])
                fin = self._fetch_purchase_financials(pid)
                if fin["remaining_due"] > 1e-9:
                    out.append(
                        {
                            "purchase_id": pid,
                            "date": str(row["date"]),
                            "total": float(fin["calculated_total_amount"]),
                            "paid": float(fin["paid_amount"]),
                            "remaining_due": float(fin["remaining_due"]),
                        }
                    )
        except Exception:
            return []
        return out
