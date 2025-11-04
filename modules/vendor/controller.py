from PySide6.QtWidgets import QWidget, QDialog, QFormLayout, QDialogButtonBox, QLineEdit, QDateEdit, QVBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QDate, QItemSelectionModel
import sqlite3
from typing import Optional, Any, Dict, List
from ..base_module import BaseModule
from .view import VendorView
from .form import VendorForm
from .model import VendorsTableModel
from .bank_accounts_dialog import AccountEditDialog
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.purchases_repo import PurchasesRepo
from ...utils import ui_helpers as uih
from ...utils.helpers import today_str
try:
    from ...database.repositories.vendor_advances_repo import OverapplyVendorAdvanceError
except Exception:
    OverapplyVendorAdvanceError = None
try:
    from ...database.repositories.purchase_payments_repo import OverpayPurchaseError
except Exception:
    OverpayPurchaseError = None
_EPS = 1e-9
def info(parent, title: str, text: str):
    return uih.info(parent, title, text)
class VendorController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = VendorsRepo(conn)
        self.vadv = VendorAdvancesRepo(conn)
        self.vbank = VendorBankAccountsRepo(conn)
        self.ppay = PurchasePaymentsRepo(conn)
        self.view = VendorView()
        from .model import VendorBankAccountsTableModel
        acc_model = VendorBankAccountsTableModel([])
        self.view.accounts_table.setModel(acc_model)
        sm = self.view.accounts_table.selectionModel()
        if sm:
            sm.selectionChanged.connect(self._update_acc_buttons_enabled)
        self._set_acc_buttons_enabled(False)
        self._hook_acc_selection_enablement()
        self._wire()
        self._reload()
    def get_widget(self) -> QWidget:
        return self.view
    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.search.textChanged.connect(self._apply_filter)
        if hasattr(self.view, "btn_record_payment"):
            self.view.btn_record_payment.clicked.connect(self._on_record_payment)
        if hasattr(self.view, "btn_record_advance"):
            self.view.btn_record_advance.clicked.connect(self._on_record_advance_dialog)
        if hasattr(self.view, "btn_apply_advance"):
            self.view.btn_apply_advance.clicked.connect(self._on_apply_advance_dialog)
        if hasattr(self.view, "btn_update_clearing"):
            self.view.btn_update_clearing.clicked.connect(self._on_update_clearing)
        if hasattr(self.view, "btn_grant_credit"):
            try:
                self.view.btn_grant_credit.clicked.disconnect()
            except Exception:
                pass
            self.view.btn_grant_credit.clicked.connect(self._open_grant_credit_dialog)
        if hasattr(self.view, "btn_list_vendor_payments"):
            self.view.btn_list_vendor_payments.clicked.connect(self._on_list_vendor_payments)
        if hasattr(self.view, "btn_list_purchase_payments"):
            self.view.btn_list_purchase_payments.clicked.connect(self._on_list_purchase_payments)
        if hasattr(self.view, "btn_list_pending_instruments"):
            self.view.btn_list_pending_instruments.clicked.connect(self._on_list_pending_instruments)
        self.view.btn_acc_add.clicked.connect(self._acc_add)
        self.view.btn_acc_edit.clicked.connect(self._acc_edit)
        self.view.btn_acc_deactivate.clicked.connect(self._acc_deactivate)
        self.view.btn_acc_set_primary.clicked.connect(self._acc_set_primary)
    def _build_model(self):
        rows = self.repo.list_vendors()
        self.base_model = VendorsTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base_model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.table.setModel(self.proxy)
        self.view.table.resizeColumnsToContents()
        sel = self.view.table.selectionModel()
        try:
            sel.selectionChanged.disconnect(self._update_details)
        except (TypeError, RuntimeError):
            pass
        sel.selectionChanged.connect(self._update_details)
    def _reload(self):
        self._build_model()
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
    def _update_details(self, *args, **kwargs):
        vid = self._selected_id()
        self.view.details.set_data(self._current_vendor_row())
        credit = 0.0
        try:
            if vid:
                raw = self.vadv.get_balance(int(vid))
                credit = float(raw) if raw is not None else 0.0
        except Exception:
            credit = 0.0
        if hasattr(self.view, "details") and hasattr(self.view.details, "set_credit"):
            self.view.details.set_credit(credit)
        self._reload_accounts(vid)
        self._hook_acc_selection_enablement()
        self._update_acc_buttons_enabled()
    def _list_company_bank_accounts(self) -> List[Dict[str, Any]]:
        try:
            # Use the repository to get company bank accounts
            from ...database.repositories.company_bank_accounts_repo import CompanyBankAccountsRepo
            repo = CompanyBankAccountsRepo(self.conn)
            rows = repo.list_active()
            return [{"id": int(r["account_id"]), "name": r.get("label") or (r.get("bank_name", "") + " " + r.get("account_no", ""))} for r in rows]
        except Exception:
            return []
    def _list_vendor_bank_accounts(self, vendor_id: int) -> List[Dict[str, Any]]:
        try:
            rows = self.vbank.list(vendor_id, active_only=True)
            out: List[Dict[str, Any]] = []
            for r in rows:
                out.append({"id": int(r["vendor_bank_account_id"]), "name": r.get("label") or (r.get("bank_name") or "") + " " + (r.get("account_no") or "")})
            return out
        except Exception:
            return []
    def _open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        return self.repo.get_open_purchases_for_vendor(vendor_id)
    def _list_open_purchases_for_vendor(self, vendor_id: int) -> List[Dict[str, Any]]:
        try:
            rows = self._open_purchases_for_vendor(vendor_id)
            out: List[Dict[str, Any]] = []
            for r in rows:
                total = float(r["total_amount"] or 0.0)
                paid = float(r["paid_amount"] or 0.0)
                out.append({"purchase_id": r["purchase_id"], "doc_no": r["purchase_id"], "date": r["date"], "total": total, "paid": paid})
            return out
        except Exception:
            return []
    def list_open_purchases(self) -> list[dict]:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self._open_purchases_for_vendor(vid)
    def _purchase_belongs_to_vendor(self, purchase_id: str, vendor_id: int) -> bool:
        row = self.repo.get_vendor_id_for_purchase(purchase_id)
        return bool(row) and int(row["vendor_id"]) == int(vendor_id)
    def _remaining_due_for_purchase(self, purchase_id: str) -> float:
        row = self.repo.get_purchase_remaining_due(purchase_id)
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
    def _current_vendor_id(self):
        try:
            vid = self._selected_id()
            return int(vid) if vid else None
        except Exception:
            return None
    def _current_selected_account(self):
        view = self.view.accounts_table
        model = view.model()
        sel = view.selectionModel()
        if not model or not sel or not sel.hasSelection():
            return None
        index = sel.currentIndex()
        row_dict = getattr(model, "row_at", lambda r: None)(index.row())
        return row_dict
    def _reload_accounts(self, vendor_id: int, keep_account_id: int | None = None):
        if not vendor_id:
            if self.view.accounts_table.model():
                self.view.accounts_table.model().set_rows([])
            return
        rows = self.vbank.list(int(vendor_id), active_only=False)
        model = self.view.accounts_table.model()
        if hasattr(model, "set_rows"):
            model.set_rows(rows)
        self.view.accounts_table.resizeColumnsToContents()
        if keep_account_id:
            m = self.view.accounts_table.model()
            if hasattr(m, "find_row_by_id"):
                r = m.find_row_by_id(int(keep_account_id))
                if r is not None:
                    idx = m.index(r, 0)
                    sm = self.view.accounts_table.selectionModel()
                    if sm is not None:
                        sm.select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                    self.view.accounts_table.setCurrentIndex(idx)
        elif self.view.accounts_table.model().rowCount() > 0:
            idx0 = self.view.accounts_table.model().index(0, 0)
            self.view.accounts_table.setCurrentIndex(idx0)
    def _acc_add(self):
        vendor_id = self._current_vendor_id()
        if not vendor_id:
            uih.info(self.view, "Select", "Please select a vendor first.")
            return
        dlg = AccountEditDialog(self.view, initial=None)
        if dlg.exec():
            data = dlg.payload()
            try:
                self.vbank.create(int(vendor_id), data)
                uih.info(self.view, "Added", "Bank account added.")
                self._reload_accounts(vendor_id)
            except Exception as e:
                uih.info(self.view, "Error", f"Unable to add account: {e}")
    def _acc_edit(self):
        vendor_id = self._current_vendor_id()
        row = self._current_selected_account()
        if not vendor_id or not row:
            uih.info(self.view, "Select", "Select a bank account to edit.")
            return
        account_id = int(row.get("vendor_bank_account_id"))
        dlg = AccountEditDialog(self.view, initial=row)
        if dlg.exec():
            data = dlg.payload()
            try:
                self.vbank.update(account_id, data)
                uih.info(self.view, "Updated", "Bank account updated.")
                self._reload_accounts(vendor_id, keep_account_id=account_id)
            except Exception as e:
                uih.info(self.view, "Error", f"Unable to update account: {e}")
    def _acc_deactivate(self):
        vendor_id = self._current_vendor_id()
        row = self._current_selected_account()
        if not vendor_id or not row:
            uih.info(self.view, "Select", "Select a bank account to deactivate.")
            return
        account_id = int(row.get("vendor_bank_account_id"))
        try:
            self.vbank.deactivate(account_id)
            uih.info(self.view, "Deactivated", "Bank account deactivated.")
            self._reload_accounts(vendor_id)
        except Exception as e:
            uih.info(self.view, "Error", f"Unable to deactivate account: {e}")
    def _acc_set_primary(self):
        vendor_id = self._current_vendor_id()
        row = self._current_selected_account()
        if not vendor_id or not row:
            uih.info(self.view, "Select", "Select a bank account to set as primary.")
            return
        account_id = int(row.get("vendor_bank_account_id"))
        try:
            self.vbank.force_set_primary(int(vendor_id), account_id)
            uih.info(self.view, "Updated", "Primary bank account updated.")
            self._reload_accounts(vendor_id, keep_account_id=account_id)
        except Exception as e:
            uih.info(self.view, "Error", f"Unable to set primary: {e}")
    def _accounts_table_widget(self):
        return getattr(self.view, "tblAccounts", None) or getattr(self.view, "accounts_table", None)
    def _has_account_selection(self):
        table = self._accounts_table_widget()
        if not table or not table.selectionModel():
            return False
        return table.selectionModel().hasSelection()
    def _set_acc_buttons_enabled(self, enabled: bool):
        for name in ("btn_acc_edit", "btn_acc_deactivate", "btn_acc_set_primary"):
            btn = getattr(self.view, name, None)
            if btn is not None:
                btn.setEnabled(bool(enabled))
    def _update_acc_buttons_enabled(self, *args):
        self._set_acc_buttons_enabled(self._has_account_selection())
    def _hook_acc_selection_enablement(self):
        if getattr(self, "_acc_enablement_hooked", False):
            self._update_acc_buttons_enabled()
            return
        table = self._accounts_table_widget()
        if not table or not table.selectionModel():
            try:
                from PySide6 import QtCore
                QtCore.QTimer.singleShot(0, self._hook_acc_selection_enablement)
            except Exception:
                pass
            self._set_acc_buttons_enabled(False)
            return
        table.selectionModel().selectionChanged.connect(self._update_acc_buttons_enabled)
        self._acc_enablement_hooked = True
        self._update_acc_buttons_enabled()
    def _format_bool(self, v):
        try:
            return "Yes" if bool(v) else "No"
        except Exception:
            return "No"
    def _clear_account_details(self):
        if not hasattr(self.view, "account_details_box"):
            return
        self.view.lblAccLabel.setText("-")
        self.view.lblAccBank.setText("-")
        self.view.lblAccNumber.setText("-")
        self.view.lblAccIBAN.setText("-")
        self.view.lblAccRouting.setText("-")
        self.view.lblAccPrimary.setText("-")
        self.view.lblAccActive.setText("-")
    def _set_account_details(self, row_dict: dict):
        if not row_dict or not hasattr(self.view, "account_details_box"):
            self._clear_account_details()
            return
        self.view.lblAccLabel.setText(str(row_dict.get("label", "") or "-"))
        self.view.lblAccBank.setText(str(row_dict.get("bank_name", "") or "-"))
        self.view.lblAccNumber.setText(str(row_dict.get("account_no", "") or "-"))
        self.view.lblAccIBAN.setText(str(row_dict.get("iban", "") or "-"))
        self.view.lblAccRouting.setText(str(row_dict.get("routing_no", "") or "-"))
        self.view.lblAccPrimary.setText(self._format_bool(row_dict.get("is_primary")))
        self.view.lblAccActive.setText(self._format_bool(row_dict.get("is_active")))
    def _update_account_details(self, *_):
        accounts_table = getattr(self.view, "tblAccounts", None) or getattr(self.view, "accounts_table", None)
        if not accounts_table or not accounts_table.model():
            self._clear_account_details()
            return
        sel = accounts_table.selectionModel()
        if not sel or not sel.hasSelection():
            self._clear_account_details()
            return
        idx = sel.currentIndex()
        model = accounts_table.model()
        row_dict = None
        if hasattr(model, "row_at"):
            row_dict = model.row_at(idx.row())
        else:
            key_map = ["vendor_bank_account_id", "label", "bank_name", "account_no", "iban", "routing_no", "is_primary", "is_active"]
            row_dict = {}
            for col, key in enumerate(key_map):
                mi = model.index(idx.row(), col)
                row_dict[key] = model.data(mi, Qt.DisplayRole)
            row_dict["is_primary"] = True if row_dict.get("is_primary") in ("Yes", True, "true", "1", 1) else False
            row_dict["is_active"] = True if row_dict.get("is_active") in ("Yes", True, "true", "1", 1) else False
        self._set_account_details(row_dict)
    def _after_accounts_model_bound(self):
        accounts_table = getattr(self.view, "tblAccounts", None) or getattr(self.view, "accounts_table", None)
        if not accounts_table:
            return
        sm = accounts_table.selectionModel()
        if sm and not getattr(self, "_acc_details_hooked", False):
            sm.selectionChanged.connect(self._update_account_details)
            self._acc_details_hooked = True
    def _reload_accounts(self, vendor_id: int, keep_account_id: int | None = None):
        if not vendor_id:
            if self.view.accounts_table.model():
                self.view.accounts_table.model().set_rows([])
            self._clear_account_details()
            self._hook_acc_selection_enablement()
            self._update_acc_buttons_enabled()
            return
        rows = self.vbank.list(int(vendor_id), active_only=False)
        model = self.view.accounts_table.model()
        if hasattr(model, "set_rows"):
            model.set_rows(rows)
        self.view.accounts_table.resizeColumnsToContents()
        self._after_accounts_model_bound()
        accounts_table = getattr(self.view, "tblAccounts", None) or getattr(self.view, "accounts_table", None)
        model = accounts_table.model() if accounts_table else None
        if keep_account_id:
            m = self.view.accounts_table.model()
            if hasattr(m, "find_row_by_id"):
                r = m.find_row_by_id(int(keep_account_id))
                if r is not None:
                    idx = m.index(r, 0)
                    sm = self.view.accounts_table.selectionModel()
                    if sm is not None:
                        sm.select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                    self.view.accounts_table.setCurrentIndex(idx)
                    self._update_account_details()
                    self._hook_acc_selection_enablement()
                    self._update_acc_buttons_enabled()
                    return
        elif self.view.accounts_table.model().rowCount() > 0:
            idx0 = self.view.accounts_table.model().index(0, 0)
            sm = self.view.accounts_table.selectionModel()
            if sm is not None:
                sm.select(idx0, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            self.view.accounts_table.setCurrentIndex(idx0)
            self._update_account_details()
        else:
            self._clear_account_details()
        self._hook_acc_selection_enablement()
        self._update_acc_buttons_enabled()
    def _on_record_payment(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        try:
            from .payment_dialog import open_vendor_money_form
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor payment dialog is not available:\n{e}")
            return
        defaults = {"list_company_bank_accounts": self._list_company_bank_accounts, "list_vendor_bank_accounts": self._list_vendor_bank_accounts, "list_open_purchases_for_vendor": self._list_open_purchases_for_vendor, "today": today_str, "vendor_display": str(vid)}
        payload = open_vendor_money_form(mode="payment", vendor_id=vid, purchase_id=None, defaults=defaults)
        if not payload:
            return
        purchase_id = payload.get("purchase_id")
        if not purchase_id:
            info(self.view, "Required", "Please select a purchase.")
            return
        if not self._purchase_belongs_to_vendor(purchase_id, vid):
            info(self.view, "Invalid", "Purchase does not belong to the selected vendor.")
            return
        amount = float(payload.get("amount", 0) or 0.0)
        method = str(payload.get("method") or "")
        remaining = self._remaining_due_for_purchase(str(purchase_id))
        if method.lower() != "cash" and amount - remaining > _EPS:
            info(self.view, "Too much", f"Amount exceeds remaining due ({remaining:.2f}).")
            return
        try:
            # Begin transaction to ensure both payment and header totals are updated atomically
            self.conn.execute("BEGIN")
            
            pid = self.ppay.record_payment(purchase_id=str(purchase_id), amount=amount, method=method, date=payload.get("date"), bank_account_id=payload.get("bank_account_id"), vendor_bank_account_id=payload.get("vendor_bank_account_id"), instrument_type=payload.get("instrument_type"), instrument_no=payload.get("instrument_no"), instrument_date=payload.get("instrument_date"), deposited_date=payload.get("deposited_date"), cleared_date=payload.get("cleared_date"), clearing_state=payload.get("clearing_state"), notes=payload.get("notes"), created_by=payload.get("created_by"))
            
            # Update the purchase header totals to reflect the new payment
            self.repo.update_header_totals(str(purchase_id))
            
            # Commit the transaction to persist both changes
            self.conn.execute("COMMIT")
            
            info(self.view, "Saved", f"Payment #{pid} recorded.")
            
        except Exception as e:
            # Rollback the transaction in case of any error
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass  # Ignore rollback errors
            if OverpayPurchaseError and isinstance(e, OverpayPurchaseError):
                info(self.view, "Not saved", str(e))
                return
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not saved", str(e))
                return
            info(self.view, "Not saved", f"Payment recording failed: {e}")
            return

        self._reload()
    def _on_record_advance_dialog(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        try:
            from .payment_dialog import open_vendor_money_form
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor money dialog is not available:\n{e}")
            return
        payload = open_vendor_money_form(mode="advance", vendor_id=vid, purchase_id=None, defaults={"vendor_display": str(vid), "today": today_str})
        if not payload:
            return
        try:
            tx_id = self.vadv.grant_credit(vendor_id=vid, amount=float(payload.get("amount", 0) or 0), date=payload.get("date"), notes=payload.get("notes"), created_by=payload.get("created_by"), source_id=None)
        except Exception as e:
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not saved", str(e))
                return
            info(self.view, "Not saved", str(e))
            return
        info(self.view, "Saved", f"Advance #{tx_id} recorded.")
        self._reload()
    def _on_apply_advance_dialog(self):
        info(self.view, "Feature Removed", "The Apply Advance feature has been removed as advances are now automatically applied to purchases when they are created or edited.")
    def _on_update_clearing(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
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
                self._payload = {"payment_id": pid, "clearing_state": state, "cleared_date": date_str, "notes": (self.notes.text().strip() or None)}
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
            updated = self.ppay.update_clearing_state(payment_id=int(data["payment_id"]), clearing_state=str(data["clearing_state"]), cleared_date=data.get("cleared_date"), notes=data.get("notes"))
        except (ValueError, sqlite3.IntegrityError) as e:
            info(self.view, "Not updated", str(e))
            return
        if updated <= 0:
            info(self.view, "Not updated", "No payment updated.")
            return
        info(self.view, "Updated", "Payment clearing updated.")
        self._reload()
    def _on_list_vendor_payments(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        rows = self.ppay.list_payments_for_vendor(vid, date_from=None, date_to=None)
        info(self.view, "Payments", f"Found {len(rows)} payment(s) for vendor.")
    def _on_list_purchase_payments(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
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
    def build_vendor_statement(self, vendor_id: int, *, date_from: Optional[str] = None, date_to: Optional[str] = None, include_opening: bool = True, show_return_origins: bool = False) -> dict:
        opening_credit = 0.0
        opening_payable = 0.0
        if include_opening and date_from:
            opening_credit = float(self.vadv.get_opening_balance(vendor_id, date_from))
            opening_payable -= opening_credit
        rows: list[dict] = []
        prep = PurchasesRepo(self.conn)
        for p in prep.list_purchases_by_vendor(vendor_id, date_from, date_to):
            rows.append({"date": p["date"], "type": "Purchase", "doc_id": p["purchase_id"], "reference": {}, "amount_effect": float(p["total_amount"])})
        for pay in self.ppay.list_payments_for_vendor(vendor_id, date_from, date_to):
            if str(pay["clearing_state"] or "").lower() != "cleared":
                continue
            amt = float(pay["amount"])
            row_type = "Cash Payment" if amt > 0 else "Refund"
            rows.append({"date": pay["date"], "type": row_type, "doc_id": pay["purchase_id"], "reference": {"payment_id": pay["payment_id"], "method": pay["method"], "instrument_no": pay["instrument_no"], "instrument_type": pay["instrument_type"], "bank_account_id": pay["bank_account_id"], "vendor_bank_account_id": pay["vendor_bank_account_id"], "ref_no": pay["ref_no"], "clearing_state": pay["clearing_state"]}, "amount_effect": (-abs(amt) if amt < 0 else -amt)})
        credit_note_rows_to_enrich: list[tuple[int, dict]] = []
        for a in self.vadv.list_ledger(vendor_id, date_from, date_to):
            amt = float(a["amount"])
            src_type = (a["source_type"] or "").lower()
            if src_type == "return_credit":
                row = {"date": a["tx_date"], "type": "Credit Note", "doc_id": a["source_id"], "reference": {"tx_id": a["tx_id"]}, "amount_effect": -amt}
                rows.append(row)
                if show_return_origins and a["source_id"]:
                    credit_note_rows_to_enrich.append((a["tx_id"], row))
            elif src_type == "applied_to_purchase":
                rows.append({"date": a["tx_date"], "type": "Credit Applied", "doc_id": a["source_id"], "reference": {"tx_id": a["tx_id"]}, "amount_effect": -abs(amt)})
            else:
                rows.append({"date": a["tx_date"], "type": "Credit Note", "doc_id": a["source_id"], "reference": {"tx_id": a["tx_id"]}, "amount_effect": -amt})
        if show_return_origins and credit_note_rows_to_enrich:
            for _tx_id, row in credit_note_rows_to_enrich:
                pid = row.get("doc_id")
                if pid:
                    try:
                        lines = prep.list_return_values_by_purchase(pid)
                        if lines:
                            row.setdefault("reference", {})["lines"] = list(lines)
                    except Exception:
                        pass
        type_order = {"Purchase": 1, "Cash Payment": 2, "Refund": 3, "Credit Note": 4, "Credit Applied": 5}
        def tie_value(r: dict):
            ref = r.get("reference", {}) or {}
            return r.get("doc_id") or ref.get("payment_id") or ref.get("tx_id") or ""
        rows.sort(key=lambda r: (r["date"], type_order.get(r["type"], 9), tie_value(r)))
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
        return {"vendor_id": vendor_id, "period": {"from": date_from, "to": date_to}, "opening_credit": opening_credit, "opening_payable": opening_payable, "rows": out_rows, "totals": totals, "closing_balance": closing_balance}
    def list_bank_accounts(self, active_only: bool = True) -> list[dict]:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self.vbank.list(vid, active_only=active_only)
    def create_bank_account(self, data: dict) -> Optional[int]:
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
        try:
            return self.vbank.update(account_id, data) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not update bank account:\n{e}")
            return False
    def deactivate_bank_account(self, account_id: int) -> bool:
        try:
            return self.vbank.deactivate(account_id) > 0
        except sqlite3.OperationalError as e:
            info(self.view, "Not saved", f"Could not deactivate bank account:\n{e}")
            return False
    def set_primary_bank_account(self, account_id: int) -> bool:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return False
        try:
            return self.vbank.set_primary(vid, account_id) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not set primary account:\n{e}")
            return False
    def get_primary_vendor_bank_account(self, vendor_id: Optional[int] = None) -> Optional[dict]:
        vid = vendor_id or self._selected_id()
        if not vid:
            return None
        accounts = self.vbank.list(vid, active_only=True)
        for acc in accounts:
            if int(acc.get("is_primary") or 0) == 1:
                return acc
        return None
    def get_primary_vendor_bank_account_id(self, vendor_id: Optional[int] = None) -> Optional[int]:
        acc = self.get_primary_vendor_bank_account(vendor_id)
        return int(acc["vendor_bank_account_id"]) if acc and acc.get("vendor_bank_account_id") is not None else None
    def _add(self):
        form = VendorForm(self.view)
        form.manageBankAccounts.connect(self._open_vendor_bank_accounts_dialog)
        form.grantVendorCredit.connect(self._open_grant_credit_dialog)
        form.ensureVendorExists.connect(lambda payload: self._ensure_vendor_exists_for_form(form, payload))
        if not form.exec():
            return
        payload = form.payload()
        if not payload:
            return
        existing_vid = getattr(form, "_vendor_id", None)
        if existing_vid:
            self.repo.update(existing_vid, **payload)
            info(self.view, "Saved", f"Vendor #{existing_vid} updated.")
        else:
            vid = self.repo.create(**payload)
            info(self.view, "Saved", f"Vendor #{vid} created.")
        self._reload()
    def _ensure_vendor_exists_for_form(self, form, payload: dict):
        try:
            vid = self.repo.create(**payload)
            form.set_vendor_id(vid)
            uih.info(self.view, "Info", "Vendor saved. Continuing…")
            self._reload()
        except Exception as e:
            uih.info(self.view, "Error", f"Unable to save vendor: {e}")
    def _edit(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor to edit.")
            return
        current = self.repo.get(vid)
        form = VendorForm(self.view, initial=current.__dict__)
        form.manageBankAccounts.connect(self._open_vendor_bank_accounts_dialog)
        form.grantVendorCredit.connect(self._open_grant_credit_dialog)
        form.ensureVendorExists.connect(lambda payload: self._ensure_vendor_exists_for_form(form, payload))
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
    def _open_vendor_bank_accounts_dialog(self, vendor_id: int):
        try:
            from .bank_accounts_dialog import VendorBankAccountsDialog
        except Exception as e:
            info(self.view, "Not available", f"Bank Accounts dialog is unavailable:\n{e}")
            return
        try:
            dlg = VendorBankAccountsDialog(self.view, conn=self.conn, vendor_id=int(vendor_id))
        except TypeError:
            try:
                dlg = VendorBankAccountsDialog(self.view, vendor_id=int(vendor_id))
            except Exception as e:
                info(self.view, "Error", f"Cannot open Bank Accounts dialog:\n{e}")
                return
        dlg.exec()
        self._reload()
    def _open_grant_credit_dialog(self, vendor_id: Optional[int] = None):
        if not vendor_id:
            try:
                vid = self._selected_id()
                vendor_id = int(vid) if vid else None
            except Exception:
                vendor_id = None
        if not vendor_id:
            uih.info(self.view, "Select", "Please select a vendor first.")
            return
        from PySide6 import QtWidgets, QtCore
        dlg = QtWidgets.QDialog(self.view)
        dlg.setWindowTitle("Grant Credit")
        dlg.setModal(True)
        form = QtWidgets.QFormLayout(dlg)
        amt_edit = QtWidgets.QLineEdit(dlg)
        amt_edit.setPlaceholderText("Amount (e.g., 1000.00)")
        amt_edit.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        memo_edit = QtWidgets.QLineEdit(dlg)
        memo_edit.setPlaceholderText("Optional note/memo")
        date_edit = QtWidgets.QDateEdit(dlg)
        date_edit.setCalendarPopup(True)
        date_edit.setDate(QtCore.QDate.currentDate())
        form.addRow("Amount", amt_edit)
        form.addRow("Memo", memo_edit)
        form.addRow("Date", date_edit)
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=dlg)
        form.addRow(btn_box)
        def _on_ok():
            raw = amt_edit.text().strip()
            try:
                amount = float(raw)
            except Exception:
                uih.info(self.view, "Invalid", "Enter a valid credit amount.")
                return
            if amount <= 0:
                uih.info(self.view, "Invalid", "Amount must be greater than 0.")
                return
            memo = memo_edit.text().strip() or None
            qd = date_edit.date()
            grant_date = None
            try:
                grant_date = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
            except Exception:
                grant_date = None
            try:
                self.vadv.grant_credit(vendor_id=vendor_id, amount=amount, date=(grant_date or (today_str() if callable(today_str) else today_str)), notes=memo, created_by=None, source_id=None)
                uih.info(self.view, "Success", "Credit granted.")
                if hasattr(self, "_update_details"):
                    self._update_details()
                dlg.accept()
            except Exception as e:
                uih.info(self.view, "Error", f"Unable to grant credit: {e}")
        btn_box.accepted.connect(_on_ok)
        btn_box.rejected.connect(dlg.reject)
        dlg.exec()
