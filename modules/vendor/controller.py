from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
import sqlite3
from typing import Optional

from ..base_module import BaseModule
from .view import VendorView
from .form import VendorForm
from .model import VendorsTableModel
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.purchases_repo import PurchasesRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str


class VendorController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = VendorsRepo(conn)
        self.vadv = VendorAdvancesRepo(conn)
        self.vbank = VendorBankAccountsRepo(conn)  # <-- bank accounts repo
        self.ppay = PurchasePaymentsRepo(conn)     # payments repo for statement flow
        self.view = VendorView()
        self._wire()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.search.textChanged.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_vendors()
        self.base_model = VendorsTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base_model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # search across all columns
        self.view.table.setModel(self.proxy)
        self.view.table.resizeColumnsToContents()
        # IMPORTANT: selectionModel() is NEW after setModel; re-connect every time
        sel = self.view.table.selectionModel()
        try:
            sel.selectionChanged.disconnect(self._update_details)
        except (TypeError, RuntimeError):
            pass
        sel.selectionChanged.connect(self._update_details)

    def _reload(self):
        self._build_model()
        # auto-select first row so details populate immediately
        if self.proxy.rowCount() > 0:
            self.view.table.selectRow(0)
        else:
            self.view.details.clear()

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_id(self) -> int | None:
        idxs = self.view.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base_model.at(src.row()).vendor_id

    def _current_vendor_row(self) -> dict | None:
        vid = self._selected_id()
        return self.repo.get(vid).__dict__ if vid else None

    def _update_details(self, *args):
        self.view.details.set_data(self._current_vendor_row())

    # ---------- Helper: list open purchases for selected vendor ----------
    def _open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        """
        Returns purchases with positive remaining balance:
        balance = total_amount - paid_amount - advance_payment_applied
        """
        sql = """
        SELECT
            p.purchase_id,
            p.date,
            CAST(p.total_amount AS REAL)    AS total_amount,
            CAST(p.paid_amount AS REAL)     AS paid_amount,
            CAST(p.advance_payment_applied AS REAL) AS advance_payment_applied,
            (CAST(p.total_amount AS REAL) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) AS balance
        FROM purchases p
        WHERE p.vendor_id = ?
          AND (CAST(p.total_amount AS REAL) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) > 1e-9
        ORDER BY DATE(p.date) DESC, p.purchase_id DESC
        """
        return self.conn.execute(sql, (vendor_id,)).fetchall()

    # Public helper for UI to fetch open purchases of current vendor
    def list_open_purchases(self) -> list[dict]:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self._open_purchases_for_vendor(vid)

    # ---------- Action: grant (manual) vendor credit ----------
    def grant_vendor_credit(
        self,
        *,
        amount: float,
        date: Optional[str] = None,
        notes: Optional[str] = None,
        source_id: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> None:
        """
        Manually grant credit to the selected vendor (e.g., adjustments or credit notes not tied to an immediate return).
        Writes a POSITIVE amount to vendor_advances (source_type='return_credit').

        UI can call this directly with form inputs. Does not mutate purchase headers; triggers handle balances.
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            info(self.view, "Invalid amount", "Enter a valid positive amount to grant as credit.")
            return
        if amt <= 0:
            info(self.view, "Invalid amount", "Amount must be greater than zero.")
            return

        try:
            self.vadv.grant_credit(
                vendor_id=vid,
                amount=amt,
                date=date or today_str(),
                notes=notes,
                created_by=created_by,
                source_id=source_id,
            )
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not grant vendor credit:\n{e}")
            return

        info(self.view, "Saved", f"Granted vendor credit of {amt:g}.")
        self._reload()

    # ---------- Action: apply existing vendor credit to an open purchase ----------
    def apply_vendor_credit_to_purchase(
        self,
        *,
        purchase_id: str,
        amount: float,
        date: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> None:
        """
        Symmetrical action from vendor profile:
        Apply available vendor credit to a specific open purchase.

        - Validates vendor selection and that the purchase belongs to that vendor.
        - `amount` must be positive; triggers prevent overdrawing credit.
        - Does NOT update header money fields directly; DB triggers roll up.
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        # Basic validation of amount
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            info(self.view, "Invalid amount", "Enter a valid positive amount to apply as credit.")
            return
        if amt <= 0:
            info(self.view, "Invalid amount", "Amount must be greater than zero.")
            return

        # Ensure the purchase belongs to this vendor and is open
        open_rows = self._open_purchases_for_vendor(vid)
        open_ids = {r["purchase_id"] for r in open_rows}
        if purchase_id not in open_ids:
            info(self.view, "Not allowed", "Selected purchase is not open for this vendor or does not belong to it.")
            return

        # Apply credit (schema trigger handles overdraw + header rollup)
        try:
            self.vadv.apply_credit_to_purchase(
                vendor_id=vid,
                purchase_id=purchase_id,
                amount=amt,
                date=date or today_str(),
                notes=notes,
                created_by=created_by,  # pass through if provided; else NULL
            )
        except sqlite3.IntegrityError as e:
            # Typically 'Insufficient vendor credit' from trigger
            info(self.view, "Credit not applied", f"Could not apply vendor credit:\n{e}")
            return
        except sqlite3.OperationalError as e:
            info(self.view, "Credit not applied", f"A database error occurred:\n{e}")
            return

        info(self.view, "Saved", f"Applied vendor credit of {amt:g} to {purchase_id}.")
        # No header mutation here; triggers handle it. Reload vendor list/details.
        self._reload()

    # =========================
    # Vendor Bank Accounts API
    # (for future UI usage)
    # =========================
    def list_bank_accounts(self, active_only: bool = True) -> list[dict]:
        """List bank accounts for the currently selected vendor."""
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self.vbank.list(vid, active_only=active_only)

    def create_bank_account(self, data: dict) -> Optional[int]:
        """Create a bank account for the selected vendor."""
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return None
        try:
            return self.vbank.create(vid, data)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not create bank account:\n{e}")
            return None

    def update_bank_account(self, account_id: int, data: dict) -> bool:
        """Update a vendor bank account."""
        try:
            return self.vbank.update(account_id, data) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not update bank account:\n{e}")
            return False

    def deactivate_bank_account(self, account_id: int) -> bool:
        """Deactivate (or delete if unreferenced) a vendor bank account."""
        try:
            return self.vbank.deactivate(account_id) > 0
        except sqlite3.OperationalError as e:
            info(self.view, "Not saved", f"Could not deactivate bank account:\n{e}")
            return False

    def set_primary_bank_account(self, account_id: int) -> bool:
        """Mark an account as primary for the selected vendor."""
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return False
        try:
            return self.vbank.set_primary(vid, account_id) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not set primary account:\n{e}")
            return False

    # -------- Provider used by purchase payment flow --------
    def get_primary_vendor_bank_account(self, vendor_id: Optional[int] = None) -> Optional[dict]:
        """
        Return the default/primary bank account dict for a vendor (None if not present).
        Useful to pre-populate the purchase payment flow with a vendor's receiving account.
        """
        vid = vendor_id or self._selected_id()
        if not vid:
            return None
        accounts = self.vbank.list(vid, active_only=True)
        for acc in accounts:
            if int(acc.get("is_primary") or 0) == 1:
                return acc
        return None

    def get_primary_vendor_bank_account_id(self, vendor_id: Optional[int] = None) -> Optional[int]:
        """
        Return the vendor_bank_account_id of the primary account (or None).
        """
        acc = self.get_primary_vendor_bank_account(vendor_id)
        return int(acc["vendor_bank_account_id"]) if acc and acc.get("vendor_bank_account_id") is not None else None

    # ---------- Statement orchestration ----------
    def build_vendor_statement(
        self,
        vendor_id: int,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_opening: bool = True,
        show_return_origins: bool = False,
    ) -> dict:
        """
        Build a vendor statement over a date range.

        Notes:
        - Purchase headers already reflect CLEARED-ONLY cash rollups (paid_amount).
        - Here, we also include ONLY payments whose clearing_state='cleared' so
          the statement reconciles with headers/aging.
        """
        # --- Opening balances (credit reduces payable) ---
        opening_credit = 0.0
        opening_payable = 0.0
        if include_opening and date_from:
            opening_credit = float(self.vadv.get_opening_balance(vendor_id, date_from))
            opening_payable -= opening_credit  # credit reduces what we owe

        rows: list[dict] = []

        # 1) Purchases (header rows only, date-filtered)
        prep = PurchasesRepo(self.conn)
        for p in prep.list_purchases_by_vendor(vendor_id, date_from, date_to):
            rows.append({
                "date": p["date"],
                "type": "Purchase",
                "doc_id": p["purchase_id"],
                "reference": {},
                "amount_effect": float(p["total_amount"]),  # increases payable
            })

        # 2) Cash/payments — CLEARED-ONLY
        for pay in self.ppay.list_payments_for_vendor(vendor_id, date_from, date_to):
            if str(pay["clearing_state"] or "").lower() != "cleared":
                continue  # ignore posted/pending/bounced
            amt = float(pay["amount"])
            row_type = "Cash Payment" if amt > 0 else "Refund"
            rows.append({
                "date": pay["date"],
                "type": row_type,
                "doc_id": pay["purchase_id"],
                "reference": {
                    "payment_id": pay["payment_id"],
                    "method": pay["method"],
                    "instrument_no": pay["instrument_no"],
                    "instrument_type": pay["instrument_type"],
                    "bank_account_id": pay["bank_account_id"],
                    "vendor_bank_account_id": pay["vendor_bank_account_id"],
                    "ref_no": pay["ref_no"],
                    "clearing_state": pay["clearing_state"],
                },
                # payments reduce payable; refunds are negative amounts and still reduce payable
                "amount_effect": (-abs(amt) if amt < 0 else -amt),
            })

        # 3) Credit ledger (already date-filtered)
        credit_note_rows_to_enrich: list[tuple[int, dict]] = []
        for a in self.vadv.list_ledger(vendor_id, date_from, date_to):
            amt = float(a["amount"])
            src_type = (a["source_type"] or "").lower()
            if src_type == "return_credit":
                row = {
                    "date": a["tx_date"],
                    "type": "Credit Note",
                    "doc_id": a["source_id"],
                    "reference": {"tx_id": a["tx_id"]},
                    "amount_effect": -amt,  # reduces payable
                }
                rows.append(row)
                if show_return_origins and a["source_id"]:
                    credit_note_rows_to_enrich.append((a["tx_id"], row))
            elif src_type == "applied_to_purchase":
                rows.append({
                    "date": a["tx_date"],
                    "type": "Credit Applied",
                    "doc_id": a["source_id"],
                    "reference": {"tx_id": a["tx_id"]},
                    "amount_effect": -abs(amt),  # amount stored negative => reduce payable by abs
                })
            else:
                # Fallback (treat other positive credits as reducing payable)
                rows.append({
                    "date": a["tx_date"],
                    "type": "Credit Note",
                    "doc_id": a["source_id"],
                    "reference": {"tx_id": a["tx_id"]},
                    "amount_effect": -amt,
                })

        # Optional enrichment: return origins (descriptive only)
        if show_return_origins and credit_note_rows_to_enrich:
            for _tx_id, row in credit_note_rows_to_enrich:
                pid = row.get("doc_id")
                if pid:
                    try:
                        lines = prep.list_return_values_by_purchase(pid)
                        if lines:
                            row.setdefault("reference", {})["lines"] = list(lines)
                    except Exception:
                        # Non-fatal: enrichment is optional
                        pass

        # 4) Sort and running balance (type order + stable tie-break)
        type_order = {"Purchase": 1, "Cash Payment": 2, "Refund": 3, "Credit Note": 4, "Credit Applied": 5}
        def tie_value(r: dict):
            ref = r.get("reference", {}) or {}
            return r.get("doc_id") or ref.get("payment_id") or ref.get("tx_id") or ""
        rows.sort(key=lambda r: (r["date"], type_order.get(r["type"], 9), tie_value(r)))

        # Running balance & totals
        balance = opening_payable
        totals = {"purchases": 0.0, "cash_paid": 0.0, "refunds": 0.0, "credit_notes": 0.0, "credit_applied": 0.0}
        out_rows: list[dict] = []
        for r in rows:
            balance += float(r["amount_effect"])
            rr = dict(r)
            rr["balance_after"] = balance
            out_rows.append(rr)
            if r["type"] == "Purchase":
                totals["purchases"] += abs(float(r["amount_effect"]))
            elif r["type"] == "Cash Payment":
                totals["cash_paid"] += abs(float(r["amount_effect"]))
            elif r["type"] == "Refund":
                totals["refunds"] += abs(float(r["amount_effect"]))
            elif r["type"] == "Credit Note":
                totals["credit_notes"] += abs(float(r["amount_effect"]))
            elif r["type"] == "Credit Applied":
                totals["credit_applied"] += abs(float(r["amount_effect"]))

        closing_balance = balance

        return {
            "vendor_id": vendor_id,
            "period": {"from": date_from, "to": date_to},
            "opening_credit": opening_credit,
            "opening_payable": opening_payable,
            "rows": out_rows,
            "totals": totals,
            "closing_balance": closing_balance,
        }

    # CRUD
    def _add(self):
        dlg = VendorForm(self.view)
        if not dlg.exec():
            return
        payload = dlg.payload()
        if not payload:
            return
        vid = self.repo.create(**payload)
        info(self.view, "Saved", f"Vendor #{vid} created.")
        self._reload()

    def _edit(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor to edit.")
            return
        current = self.repo.get(vid)
        dlg = VendorForm(self.view, initial=current.__dict__)
        if not dlg.exec():
            return
        payload = dlg.payload()
        if not payload:
            return
        self.repo.update(vid, **payload)
        info(self.view, "Saved", f"Vendor #{vid} updated.")
        self._reload()

    def _delete(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor to delete.")
            return
        self.repo.delete(vid)
        info(self.view, "Deleted", f"Vendor #{vid} removed.")
        self._reload()
