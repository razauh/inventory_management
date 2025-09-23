from PySide6.QtWidgets import QWidget, QDialog, QFormLayout, QDialogButtonBox, QLineEdit, QDateEdit, QVBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QDate
import sqlite3
from typing import Optional, Any, Dict, List
from ..base_module import BaseModule
from .view import VendorView
from .form import VendorForm
from .model import VendorsTableModel
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.purchases_repo import PurchasesRepo
from ...utils import ui_helpers as uih
from ...utils.helpers import today_str

# Attempt to import optional domain errors (guarded so we don't assume presence)
try:  # type: ignore[attr-defined]
    # e.g., raised when applying > available credit or > remaining due
    from ...database.repositories.vendor_advances_repo import OverapplyVendorAdvanceError  # type: ignore
except Exception:  # pragma: no cover
    OverapplyVendorAdvanceError = None  # type: ignore

try:  # type: ignore[attr-defined]
    # e.g., raised when a payment would overpay a purchase
    from ...database.repositories.purchase_payments_repo import OverpayPurchaseError  # type: ignore
except Exception:  # pragma: no cover
    OverpayPurchaseError = None  # type: ignore

_EPS = 1e-9  # numeric tolerance for float math


# Keep a module-level alias so tests that patch `vendor_controller.info`
# still capture messages, while calls ALSO go through `uih.info` so
# tests that patch `ui_helpers.info` work too.
def info(parent, title: str, text: str):
    return uih.info(parent, title, text)


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

        # New money actions (guarded so we don't break older views)
        if hasattr(self.view, "btn_record_payment"):
            self.view.btn_record_payment.clicked.connect(self._on_record_payment)
        if hasattr(self.view, "btn_record_advance"):
            self.view.btn_record_advance.clicked.connect(self._on_record_advance_dialog)
        if hasattr(self.view, "btn_apply_advance"):
            self.view.btn_apply_advance.clicked.connect(self._on_apply_advance_dialog)
        if hasattr(self.view, "btn_update_clearing"):
            self.view.btn_update_clearing.clicked.connect(self._on_update_clearing)

        # Optional list buttons (if your view exposes them)
        if hasattr(self.view, "btn_list_vendor_payments"):
            self.view.btn_list_vendor_payments.clicked.connect(self._on_list_vendor_payments)
        if hasattr(self.view, "btn_list_purchase_payments"):
            self.view.btn_list_purchase_payments.clicked.connect(self._on_list_purchase_payments)
        if hasattr(self.view, "btn_list_pending_instruments"):
            self.view.btn_list_pending_instruments.clicked.connect(self._on_list_pending_instruments)

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

    # ---------- Adapters used by dialogs (company bank, vendor bank, open purchases) ----------
    def _list_company_bank_accounts(self) -> List[Dict[str, Any]]:
        sql = """
        SELECT account_id AS id,
               COALESCE(label, bank_name || ' ' || account_no) AS name
        FROM company_bank_accounts
        WHERE is_active = 1
        ORDER BY name ASC;
        """
        try:
            rows = self.conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _list_vendor_bank_accounts(self, vendor_id: int) -> List[Dict[str, Any]]:
        try:
            rows = self.vbank.list(vendor_id, active_only=True)
            out: List[Dict[str, Any]] = []
            for r in rows:
                out.append({
                    "id": int(r["vendor_bank_account_id"]),
                    "name": r.get("label") or (r.get("bank_name") or "") + " " + (r.get("account_no") or ""),
                })
            return out
        except Exception:
            return []

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

    def _list_open_purchases_for_vendor(self, vendor_id: int) -> List[Dict[str, Any]]:
        """
        Adapter for dialog: normalize keys to {purchase_id, doc_no, date, total, paid}
        """
        try:
            rows = self._open_purchases_for_vendor(vendor_id)
            out: List[Dict[str, Any]] = []
            for r in rows:
                total = float(r["total_amount"] or 0.0)
                paid = float(r["paid_amount"] or 0.0)
                out.append({
                    "purchase_id": r["purchase_id"],
                    "doc_no": r["purchase_id"],
                    "date": r["date"],
                    "total": total,
                    "paid": paid,
                })
            return out
        except Exception:
            return []

    # Public helper for UI to fetch open purchases of current vendor
    def list_open_purchases(self) -> list[dict]:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self._open_purchases_for_vendor(vid)

    # ---------- Helpers ----------
    def _purchase_belongs_to_vendor(self, purchase_id: str, vendor_id: int) -> bool:
        row = self.conn.execute(
            "SELECT vendor_id FROM purchases WHERE purchase_id=?;",
            (purchase_id,),
        ).fetchone()
        return bool(row) and int(row["vendor_id"]) == int(vendor_id)

    def _remaining_due_for_purchase(self, purchase_id: str) -> float:
        """
        Compute remaining due using header numbers that (per schema) reflect trigger math:
          remaining = total_amount - paid_amount - advance_payment_applied
        """
        row = self.conn.execute(
            """
            SELECT
                CAST(total_amount AS REAL) AS total_amount,
                CAST(paid_amount AS REAL) AS paid_amount,
                CAST(advance_payment_applied AS REAL) AS advance_payment_applied
            FROM purchases
            WHERE purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        if not row:
            return 0.0
        total = float(row["total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        applied = float(row["advance_payment_applied"] or 0.0)
        remaining = total - paid - applied
        return max(0.0, remaining)

    def _vendor_credit_balance(self, vendor_id: int) -> float:
        try:
            return float(self.vadv.get_balance(vendor_id))
        except Exception:
            return 0.0

    # ========================= Money actions (Dialogs + Repo) =========================

    def _on_record_payment(self):
        """
        Open vendor money dialog in 'payment' mode, then persist via PurchasePaymentsRepo.
        Orchestration update:
          - Pre-check remaining due to avoid obvious overpay.
          - Catch domain errors (if exposed) and surface DB integrity errors.
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        # Lazy import the new unified dialog
        try:
            from .payment_dialog import open_vendor_money_form  # type: ignore
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor payment dialog is not available:\n{e}")
            return

        defaults = {
            "list_company_bank_accounts": self._list_company_bank_accounts,
            "list_vendor_bank_accounts": self._list_vendor_bank_accounts,
            "list_open_purchases_for_vendor": self._list_open_purchases_for_vendor,
            "today": today_str,
            "vendor_display": str(vid),
        }

        payload = open_vendor_money_form(
            mode="payment",
            vendor_id=vid,
            purchase_id=None,  # let user pick the purchase
            defaults=defaults,
        )
        if not payload:
            return

        purchase_id = payload.get("purchase_id")
        if not purchase_id:
            info(self.view, "Required", "Please select a purchase.")
            return

        if not self._purchase_belongs_to_vendor(purchase_id, vid):
            info(self.view, "Invalid", "Purchase does not belong to the selected vendor.")
            return

        # ---- Pre-check remaining due (consistency with trigger math) ----
        amount = float(payload.get("amount", 0) or 0.0)
        method = str(payload.get("method") or "")
        remaining = self._remaining_due_for_purchase(str(purchase_id))
        if method.lower() != "cash" and amount - remaining > _EPS:
            info(self.view, "Too much", f"Amount exceeds remaining due ({remaining:.2f}).")
            return

        try:
            pid = self.ppay.record_payment(
                purchase_id=str(purchase_id),
                amount=amount,
                method=method,
                date=payload.get("date"),
                bank_account_id=payload.get("bank_account_id"),
                vendor_bank_account_id=payload.get("vendor_bank_account_id"),
                instrument_type=payload.get("instrument_type"),
                instrument_no=payload.get("instrument_no"),
                instrument_date=payload.get("instrument_date"),
                deposited_date=payload.get("deposited_date"),
                cleared_date=payload.get("cleared_date"),
                clearing_state=payload.get("clearing_state"),
                notes=payload.get("notes"),
                created_by=payload.get("created_by"),
            )
        except Exception as e:
            # Catch domain error first (if available), then fall back to sqlite errors or generic
            if OverpayPurchaseError and isinstance(e, OverpayPurchaseError):  # type: ignore
                info(self.view, "Not saved", str(e))
                return
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not saved", str(e))
                return
            # Unexpected but still surface it so we don't swallow DB errors
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Payment #{pid} recorded.")
        self._reload()

    def _on_record_advance_dialog(self):
        """
        Open vendor money dialog in 'advance' mode, then persist via VendorAdvancesRepo.
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        try:
            from .payment_dialog import open_vendor_money_form  # type: ignore
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor money dialog is not available:\n{e}")
            return

        payload = open_vendor_money_form(
            mode="advance",
            vendor_id=vid,
            purchase_id=None,
            defaults={"vendor_display": str(vid), "today": today_str},
        )
        if not payload:
            return

        try:
            tx_id = self.vadv.grant_credit(
                vendor_id=vid,
                amount=float(payload.get("amount", 0) or 0),
                date=payload.get("date"),
                notes=payload.get("notes"),
                created_by=payload.get("created_by"),
                source_id=None,
            )
        except Exception as e:
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not saved", str(e))
                return
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Advance #{tx_id} recorded.")
        self._reload()

    def _on_apply_advance_dialog(self):
        """
        Open vendor money dialog in 'apply_advance' mode, then persist via VendorAdvancesRepo.
        Orchestration update:
          - Pre-check both vendor credit balance and purchase remaining due.
          - Catch domain errors (e.g., OverapplyVendorAdvanceError) plus DB integrity errors.
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        try:
            from .payment_dialog import open_vendor_money_form  # type: ignore
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor money dialog is not available:\n{e}")
            return

        defaults = {
            "list_open_purchases_for_vendor": self._list_open_purchases_for_vendor,
            "today": today_str,
            "vendor_display": str(vid),
        }
        payload = open_vendor_money_form(
            mode="apply_advance",
            vendor_id=vid,
            purchase_id=None,
            defaults=defaults,
        )
        if not payload:
            return

        purchase_id = payload.get("purchase_id")
        amt = payload.get("amount")
        if not purchase_id or amt is None:
            info(self.view, "Required", "Please select a purchase and enter amount.")
            return

        if not self._purchase_belongs_to_vendor(purchase_id, vid):
            info(self.view, "Invalid", "Purchase does not belong to the selected vendor.")
            return

        amount = float(amt)
        # ---- Pre-checks: credit balance & remaining due ----
        remaining = self._remaining_due_for_purchase(str(purchase_id))
        credit_bal = self._vendor_credit_balance(int(vid))
        allowable = min(credit_bal, remaining)
        if amount - allowable > _EPS:
            info(self.view, "Too much", f"Amount exceeds available credit or remaining due (max {allowable:.2f}).")
            return

        try:
            tx_id = self.vadv.apply_credit_to_purchase(
                vendor_id=vid,
                purchase_id=str(purchase_id),
                amount=amount,
                date=payload.get("date"),
                notes=payload.get("notes"),
                created_by=payload.get("created_by"),
            )
        except Exception as e:
            # Prefer domain error message if the repo mapped constraints
            if OverapplyVendorAdvanceError and isinstance(e, OverapplyVendorAdvanceError):  # type: ignore
                info(self.view, "Not saved", str(e))
                return
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not saved", str(e))
                return
            # Unexpected: still surface the message; do not swallow
            info(self.view, "Not saved", str(e))
            return

        info(self.view, "Saved", f"Advance application #{tx_id} recorded.")
        self._reload()

    # ---------- Clearing state update ----------
    def _on_update_clearing(self):
        """
        Prompt for a payment_id, clearing_state, optional cleared_date & notes,
        and call PurchasePaymentsRepo.update_clearing_state(...).
        """
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        # Tiny inline prompt dialog to keep this file self-contained.
        class ClearingDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Update Clearing State")
                self._payload = None

                self.paymentId = QLineEdit()
                self.paymentId.setPlaceholderText("Payment ID (int)")
                self.stateCombo = QComboBox()
                self.stateCombo.addItems(["posted", "pending", "cleared", "bounced"])
                self.clearedDate = QDateEdit()
                self.clearedDate.setCalendarPopup(True)
                self.clearedDate.setDisplayFormat("yyyy-MM-dd")
                self.clearedDate.setDate(QDate.currentDate())
                self.notes = QLineEdit()
                self.notes.setPlaceholderText("Notes (optional)")

                form = QFormLayout()
                form.addRow("Payment ID*", self.paymentId)
                form.addRow("Clearing State*", self.stateCombo)
                form.addRow("Cleared Date", self.clearedDate)
                form.addRow("Notes", self.notes)

                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                btns.accepted.connect(self._on_ok)
                btns.rejected.connect(self.reject)

                lay = QVBoxLayout(self)
                lay.addLayout(form)
                lay.addWidget(btns)

            def _on_ok(self):
                pid_txt = self.paymentId.text().strip()
                if not pid_txt:
                    return
                try:
                    pid = int(pid_txt)
                except ValueError:
                    return
                state = self.stateCombo.currentText()
                date_str = self.clearedDate.date().toString("yyyy-MM-dd") if state == "cleared" else None
                self._payload = {
                    "payment_id": pid,
                    "clearing_state": state,
                    "cleared_date": date_str,
                    "notes": (self.notes.text().strip() or None),
                }
                self.accept()

            def payload(self):
                return self._payload

        dlg = ClearingDialog(self.view)
        if not dlg.exec():
            return
        data = dlg.payload()
        if not data:
            return

        try:
            updated = self.ppay.update_clearing_state(
                payment_id=int(data["payment_id"]),
                clearing_state=str(data["clearing_state"]),
                cleared_date=data.get("cleared_date"),
                notes=data.get("notes"),
            )
        except (ValueError, sqlite3.IntegrityError) as e:
            info(self.view, "Not updated", str(e))
            return

        if updated <= 0:
            info(self.view, "Not updated", "No payment updated.")
            return
        info(self.view, "Updated", "Payment clearing updated.")
        self._reload()

    # ---------- Lists / exports ----------
    def _on_list_vendor_payments(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        # Minimal UX: just count/fetch; you can wire to a table dialog if you have one.
        rows = self.ppay.list_payments_for_vendor(vid, date_from=None, date_to=None)
        info(self.view, "Payments", f"Found {len(rows)} payment(s) for vendor.")

    def _on_list_purchase_payments(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        # Tiny prompt for purchase id
        pid = self._prompt_text("Enter Purchase ID")
        if not pid:
            return
        rows = self.ppay.list_payments_for_purchase(pid)
        info(self.view, "Payments", f"Found {len(rows)} payment(s) for purchase {pid}.")

    def _on_list_pending_instruments(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        rows = self.ppay.list_pending_instruments(vid)
        info(self.view, "Pending", f"Found {len(rows)} pending instrument(s).")

    def _prompt_text(self, title: str) -> Optional[str]:
        # very small inline line-edit prompt
        class _Prompt(QDialog):
            def __init__(self, parent=None, title="Enter"):
                super().__init__(parent)
                self.setWindowTitle(title)
                self._val = None
                self.line = QLineEdit()
                form = QFormLayout()
                form.addRow(QLabel(title), self.line)
                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                btns.accepted.connect(self._on_ok)
                btns.rejected.connect(self.reject)
                lay = QVBoxLayout(self)
                lay.addLayout(form)
                lay.addWidget(btns)

            def _on_ok(self):
                self._val = self.line.text().strip()
                self.accept()

            def value(self):
                return self._val

        dlg = _Prompt(self.view, title=title)
        if not dlg.exec():
            return None
        return dlg.value()

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

    # CRUD
    def _add(self):
        form = VendorForm(self.view)
        # Connect new signals (form is in create mode; buttons disabled until a vendor exists)
        form.manageBankAccounts.connect(self._open_vendor_bank_accounts_dialog)
        form.grantVendorCredit.connect(self._open_grant_credit_dialog)
        if not form.exec():
            return
        payload = form.payload()
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
        form = VendorForm(self.view, initial=current.__dict__)
        # Connect new signals (enabled in edit mode because vendor_id is known)
        form.manageBankAccounts.connect(self._open_vendor_bank_accounts_dialog)
        form.grantVendorCredit.connect(self._open_grant_credit_dialog)
        if not form.exec():
            return
        payload = form.payload()
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

    # ---------- Signal handlers ----------
    def _open_vendor_bank_accounts_dialog(self, vendor_id: int):
        """Open the vendor bank accounts dialog (lazy import to keep dependencies optional)."""
        try:
            # Lazy import to avoid hard dependency if dialog isn't packaged everywhere
            from .bank_accounts_dialog import VendorBankAccountsDialog  # type: ignore
        except Exception as e:
            info(self.view, "Not available", f"Bank Accounts dialog is unavailable:\n{e}")
            return
        try:
            dlg = VendorBankAccountsDialog(self.view, conn=self.conn, vendor_id=int(vendor_id))
        except TypeError:
            # Fallback: try common alternative signatures
            try:
                dlg = VendorBankAccountsDialog(self.view, vendor_id=int(vendor_id))
            except Exception as e:
                info(self.view, "Error", f"Cannot open Bank Accounts dialog:\n{e}")
                return
        dlg.exec()
        # After managing accounts, details might change (e.g., primary flag)
        self._reload()

    def _open_grant_credit_dialog(self, vendor_id: int):
        """Tiny inline dialog to grant vendor credit."""
        class GrantCreditDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Grant Vendor Credit")
                self._payload = None
                self.amount = QLineEdit()
                self.amount.setPlaceholderText("Amount (> 0)")
                self.date = QDateEdit()
                self.date.setCalendarPopup(True)
                self.date.setDate(QDate.fromString(today_str(), "yyyy-MM-dd"))
                self.notes = QLineEdit()
                self.notes.setPlaceholderText("Notes (optional)")
                form = QFormLayout()
                form.addRow("Amount*", self.amount)
                form.addRow("Date*", self.date)
                form.addRow("Notes", self.notes)
                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                btns.accepted.connect(self._on_ok)
                btns.rejected.connect(self.reject)
                lay = QVBoxLayout(self)
                lay.addLayout(form)
                lay.addWidget(btns)

            def _on_ok(self):
                try:
                    amt = float(self.amount.text())
                except (TypeError, ValueError):
                    return
                if amt <= 0:
                    return
                self._payload = {
                    "amount": amt,
                    "date": self.date.date().toString("yyyy-MM-dd"),
                    "notes": (self.notes.text().strip() or None),
                }
                self.accept()

            def payload(self):
                return self._payload

        dlg = GrantCreditDialog(self.view)
        if not dlg.exec():
            return
        data = dlg.payload()
        if not data:
            return
        try:
            self.vadv.grant_credit(
                vendor_id=int(vendor_id),
                amount=float(data["amount"]),
                date=data["date"],
                notes=data.get("notes"),
                created_by=None,
                source_id=None,
            )
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not grant vendor credit:\n{e}")
            return
        info(self.view, "Saved", f"Granted vendor credit of {float(data['amount']):g}.")
        self._reload()
