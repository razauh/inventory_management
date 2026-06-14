from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QItemSelectionModel
import sqlite3
import logging
from typing import Optional, Any, Dict, List

_log = logging.getLogger(__name__)
from ..base_module import BaseModule
from .view import VendorView
from .form import VendorForm
from .model import VendorsTableModel, _mask_value
from .bank_accounts_dialog import AccountEditDialog
from ...database.repositories.vendors_repo import DomainError as VendorsDomainError, VendorsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.purchases_repo import PurchasesRepo
from ...utils import ui_helpers as uih
from ...utils.helpers import today_str
try:
    from ...database.repositories.purchase_payments_repo import OverpayPurchaseError
except Exception:
    OverpayPurchaseError = None
_EPS = 1e-9
def info(parent, title: str, text: str):
    return uih.info(parent, title, text)
class VendorController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
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
        self.view.btn_import.clicked.connect(self._import_vendors)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.search.textChanged.connect(self._apply_filter)

        if hasattr(self.view, "btn_apply_advance"):
            self.view.btn_apply_advance.clicked.connect(self._on_apply_advance_dialog)
        if hasattr(self.view, "btn_history"):
            self.view.btn_history.clicked.connect(self._on_history)
        self.view.btn_acc_add.clicked.connect(self._acc_add)
        self.view.btn_acc_edit.clicked.connect(self._acc_edit)
        self.view.btn_acc_deactivate.clicked.connect(self._acc_deactivate)
        self.view.btn_acc_set_primary.clicked.connect(self._acc_set_primary)
        self.view.btn_acc_activate.clicked.connect(self._acc_activate)
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
        except (TypeError, RuntimeError, RuntimeWarning):
            pass
        sel.selectionChanged.connect(self._update_details)
    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.table.selectRow(0)
        else:
            self.view.details.clear()
            self._reload_accounts(None)
    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(QRegularExpression.escape(text)))
        if self.proxy.rowCount() > 0:
            if not self.view.table.selectionModel().selectedRows():
                self.view.table.selectRow(0)
        else:
            self.view.details.clear()
            self._reload_accounts(None)
    def _selected_id(self) -> int | None:
        idxs = self.view.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base_model.at(src.row()).vendor_id
    def _current_vendor_row(self) -> dict | None:
        vid = self._selected_id()
        if not vid:
            return None
        row = self.repo.get(vid)
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if hasattr(row, "__dict__"):
            return dict(row.__dict__)
        if hasattr(row, "keys"):
            try:
                return {key: row[key] for key in row.keys()}
            except Exception:
                pass
        return {"vendor_id": vid}
    def _current_vendor_display_text(self, vendor_id: int | None = None) -> str:
        row = None
        if vendor_id is not None:
            try:
                row = self.repo.get(int(vendor_id))
            except Exception:
                row = None
        else:
            try:
                vid = self._selected_id()
                row = self.repo.get(vid) if vid else None
            except Exception:
                row = None
        if not row:
            return f"Vendor #{vendor_id}" if vendor_id else "Selected vendor"
        payload = row.__dict__ if hasattr(row, "__dict__") else {}
        name = getattr(row, "name", None) or payload.get("name")
        vendor_id_val = getattr(row, "vendor_id", None) or payload.get("vendor_id")
        if not name and hasattr(row, "keys"):
            try:
                name = row["name"]
            except Exception:
                name = None
        if vendor_id_val is None and hasattr(row, "keys"):
            try:
                vendor_id_val = row["vendor_id"]
            except Exception:
                vendor_id_val = None
        if name and vendor_id_val is not None:
            return f"{name} (ID {vendor_id_val})"
        if name:
            return str(name)
        if vendor_id_val is not None:
            return f"Vendor #{vendor_id_val}"
        return "Selected vendor"
    def _update_details(self, *args, **kwargs):
        vid = self._selected_id()
        self.view.details.set_data(self._current_vendor_row())
        credit = 0.0
        credit_error = None
        try:
            if vid:
                raw = self.vadv.get_balance(int(vid))
                credit = float(raw) if raw is not None else 0.0
        except Exception as e:
            _log.exception("Failed to load vendor credit balance for vendor_id=%s", vid)
            credit_error = f"Available advance could not be loaded: {e}"
            credit = 0.0
        if hasattr(self.view, "details") and hasattr(self.view.details, "set_credit"):
            if credit_error and hasattr(self.view.details, "set_credit_error"):
                self.view.details.set_credit_error(credit_error)
            else:
                self.view.details.set_credit(credit)
        self._reload_accounts(vid)
        self._hook_acc_selection_enablement()
        self._update_acc_buttons_enabled()
    def _list_company_bank_accounts(self) -> List[Dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT account_id, label, bank_name, account_no
                FROM company_bank_accounts
                WHERE is_active = 1
                ORDER BY label ASC, account_id ASC
                """
            ).fetchall()
            return [
                {
                    "id": int(r["account_id"]),
                    "name": self._format_bank_account_choice(
                        label=r["label"],
                        bank_name=r["bank_name"],
                        account_no=r["account_no"],
                    ),
                }
                for r in rows
            ]
        except Exception as e:
            _log.exception("Failed to load company bank accounts for vendor payment flow")
            info(self.view, "Data unavailable", f"Company bank accounts could not be loaded:\n{e}")
            return []
    def _list_vendor_bank_accounts(self, vendor_id: int) -> List[Dict[str, Any]]:
        try:
            rows = self.vbank.list(vendor_id, active_only=True)
            out: List[Dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "id": int(r["vendor_bank_account_id"]),
                        "name": self._format_bank_account_choice(
                            label=r.get("label"),
                            bank_name=r.get("bank_name"),
                            account_no=r.get("account_no"),
                            is_primary=bool(r.get("is_primary")),
                        ),
                    }
                )
            return out
        except Exception as e:
            _log.exception("Failed to load vendor bank accounts for vendor_id=%s", vendor_id)
            info(self.view, "Data unavailable", f"Vendor bank accounts could not be loaded:\n{e}")
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
        except Exception as e:
            _log.exception("Failed to load open purchases for vendor_id=%s", vendor_id)
            info(self.view, "Data unavailable", f"Open purchases could not be loaded:\n{e}")
            return []
    def list_open_purchases(self) -> list[dict]:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return []
        return self._open_purchases_for_vendor(vid)
    def _purchase_belongs_to_vendor(self, purchase_id: str, vendor_id: int) -> bool:
        from ...database.repositories.purchases_repo import PurchasesRepo
        prep = PurchasesRepo(self.conn)
        row = prep.get_vendor_id_for_purchase(purchase_id)
        return bool(row) and int(row["vendor_id"]) == int(vendor_id)
    def _remaining_due_for_purchase(self, purchase_id: str) -> float:
        from ...database.repositories.purchases_repo import PurchasesRepo
        prep = PurchasesRepo(self.conn)
        row = prep.get_purchase_remaining_due(purchase_id)
        if not row:
            return 0.0
        try:
            return max(0.0, float(row["remaining_due"] or 0.0))
        except Exception:
            total = float(row.get("calculated_total_amount") or row.get("total_amount") or 0.0)
            paid = float(row.get("paid_amount") or 0.0)
            applied = float(row.get("advance_payment_applied") or 0.0)
            return max(0.0, total - paid - applied)
    def _vendor_credit_balance(self, vendor_id: int) -> float:
        try:
            return float(self.vadv.get_balance(vendor_id))
        except Exception as e:
            _log.exception("Failed to load vendor credit balance for vendor_id=%s", vendor_id)
            info(self.view, "Data unavailable", f"Vendor credit balance could not be loaded:\n{e}")
            return 0.0
    def _format_bank_account_choice(
        self,
        *,
        label: Any = None,
        bank_name: Any = None,
        account_no: Any = None,
        is_primary: bool = False,
    ) -> str:
        parts: list[str] = []
        label_text = str(label).strip() if label else ""
        bank_text = str(bank_name).strip() if bank_name else ""
        account_text = _mask_value(account_no)
        if label_text:
            parts.append(label_text)
        if bank_text:
            parts.append(bank_text)
        if account_text:
            parts.append(account_text)
        text = " - ".join(parts) if parts else "Bank account"
        if is_primary:
            text = f"{text} (Primary)"
        return text
    def _build_grant_credit_allocation_preview(self, vendor_id: int, amount: float) -> dict:
        remaining_credit = max(0.0, float(amount or 0.0))
        open_purchases = sorted(
            self.repo.get_open_purchases_for_vendor(vendor_id),
            key=lambda purchase: (
                str(purchase["date"] or ""),
                str(purchase["purchase_id"] or ""),
            ),
        )
        rows = []
        for purchase in open_purchases:
            if remaining_credit <= _EPS:
                break
            purchase_id = purchase["purchase_id"]
            remaining_due = self._remaining_due_for_purchase(purchase_id)
            if remaining_due <= _EPS:
                continue
            amount_to_apply = min(remaining_due, remaining_credit)
            if amount_to_apply <= _EPS:
                continue
            rows.append(
                {
                    "purchase_id": purchase_id,
                    "date": purchase["date"],
                    "remaining_due": remaining_due,
                    "amount_to_apply": amount_to_apply,
                    "remaining_due_after": max(0.0, remaining_due - amount_to_apply),
                }
            )
            remaining_credit -= amount_to_apply
        return {
            "total_credit": max(0.0, float(amount or 0.0)),
            "rows": rows,
            "remaining_credit": max(0.0, remaining_credit),
        }
    def _grant_credit_and_auto_apply(
        self,
        vendor_id: int,
        amount: float,
        grant_date: str,
        memo: Optional[str],
    ) -> dict:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            preview = self._build_grant_credit_allocation_preview(vendor_id, amount)
            tx_id = self.vadv.grant_credit(
                vendor_id=vendor_id,
                amount=amount,
                date=grant_date,
                notes=memo,
                created_by=None,
                source_id=None,
            )

            for row in preview["rows"]:
                self.vadv.apply_credit_to_purchase(
                    vendor_id=vendor_id,
                    purchase_id=row["purchase_id"],
                    amount=row["amount_to_apply"],
                    date=grant_date,
                    notes=f"Auto-applied from vendor advance (Tx #{tx_id})",
                    created_by=None,
                )
                _log.info(
                    f"Auto-applied {row['amount_to_apply']:.2f} of vendor advance "
                    f"to purchase {row['purchase_id']}"
                )

            self.conn.execute("COMMIT")
            return {
                "tx_id": tx_id,
                "applied_amount": amount - preview["remaining_credit"],
                "remaining_credit": preview["remaining_credit"],
                "rows": preview["rows"],
            }
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
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

    def _with_bank_account_savepoint(self, operation):
        self.conn.execute("SAVEPOINT vendor_bank_account_mutation")
        try:
            result = operation()
        except Exception:
            try:
                self.conn.execute("ROLLBACK TO vendor_bank_account_mutation")
            finally:
                self.conn.execute("RELEASE vendor_bank_account_mutation")
            raise
        self.conn.execute("RELEASE vendor_bank_account_mutation")
        return result

    def _acc_add(self):
        vendor_id = self._current_vendor_id()
        if not vendor_id:
            uih.info(self.view, "Select", "Please select a vendor first.")
            return
        dlg = AccountEditDialog(self.view, initial=None)
        if dlg.exec():
            data = dlg.payload()
            try:
                self._with_bank_account_savepoint(
                    lambda: self.vbank.create(int(vendor_id), data)
                )
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
                self._with_bank_account_savepoint(
                    lambda: self.vbank.update(account_id, data)
                )
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
            self._with_bank_account_savepoint(lambda: self.vbank.deactivate(account_id))
            uih.info(self.view, "Deactivated", "Bank account deactivated.")
            self._reload_accounts(vendor_id)
        except Exception as e:
            uih.info(self.view, "Error", f"Unable to deactivate account: {e}")
    
    def _acc_activate(self):
        vendor_id = self._current_vendor_id()
        row = self._current_selected_account()
        if not vendor_id or not row:
            uih.info(self.view, "Select", "Select a bank account to activate.")
            return
        account_id = int(row.get("vendor_bank_account_id"))
        try:
            self._with_bank_account_savepoint(lambda: self.vbank.activate(account_id))
            uih.info(self.view, "Activated", "Bank account activated.")
            self._reload_accounts(vendor_id)
        except Exception as e:
            uih.info(self.view, "Error", f"Unable to activate account: {e}")

    def _acc_set_primary(self):
        vendor_id = self._current_vendor_id()
        row = self._current_selected_account()
        if not vendor_id or not row:
            uih.info(self.view, "Select", "Select a bank account to set as primary.")
            return
            
        # Check if the selected account is active before allowing to set it as primary
        if not row.get("is_active", 1):
            uih.info(self.view, "Inactive", "Cannot set an inactive account as primary. Please activate the account first.")
            return
            
        account_id = int(row.get("vendor_bank_account_id"))
        try:
            self._with_bank_account_savepoint(
                lambda: self.vbank.force_set_primary(int(vendor_id), account_id)
            )
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
        # First set all buttons to the base enabled state
        for name in ("btn_acc_edit", "btn_acc_deactivate", "btn_acc_set_primary", "btn_acc_activate"):
            btn = getattr(self.view, name, None)
            if btn is not None:
                btn.setEnabled(bool(enabled))
        
        # If not enabled or no selection, done
        if not enabled:
            return
            
        # Based on the selected account, enable/disable based on account status
        row = self._current_selected_account()
        if not row:
            return
            
        is_active = bool(row.get("is_active", 1))  # Default to active if not specified
        btn_deactivate = getattr(self.view, "btn_acc_deactivate", None)
        btn_activate = getattr(self.view, "btn_acc_activate", None)
        
        # Only enable deactivate if the account is active, activate if inactive
        if btn_deactivate:
            btn_deactivate.setEnabled(is_active)
        if btn_activate:
            btn_activate.setEnabled(not is_active)
            
        # For "Set Primary", only enable if the account is active
        btn_set_primary = getattr(self.view, "btn_acc_set_primary", None)
        if btn_set_primary:
            btn_set_primary.setEnabled(is_active and bool(enabled))
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
        self.view.lblAccLabel.setText("No account selected")
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
        self.view.lblAccNumber.setText(_mask_value(row_dict.get("account_no")) or "-")
        self.view.lblAccIBAN.setText(_mask_value(row_dict.get("iban"), keep_last=6) or "-")
        self.view.lblAccRouting.setText(_mask_value(row_dict.get("routing_no")) or "-")
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
    def _reload_accounts(self, vendor_id: int | None, keep_account_id: int | None = None):
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



    def _on_apply_advance_dialog(self):
        # This function records a new vendor advance/payment (creates vendor credit)
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return

        try:
            from .payment_dialog import open_vendor_money_form
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor payment dialog is not available:\n{e}")
            return

        defaults = {
            "list_company_bank_accounts": self._list_company_bank_accounts,
            "list_vendor_bank_accounts": self._list_vendor_bank_accounts,
            "today": today_str,
            "vendor_display": self._current_vendor_display_text(vid),
            # Don't set default amount to allow null values in the amount field
        }

        # Use the payment form to record a new vendor advance (not tied to a specific purchase)
        payload = open_vendor_money_form(
            vendor_id=vid,
            vendors=self.repo,
            defaults=defaults
        )

        if not payload:
            return

        amount = float(payload.get("amount", 0) or 0.0)
        if amount <= 0:
            info(self.view, "Invalid", "Amount must be greater than zero.")
            return

        try:
            self.conn.execute("SAVEPOINT apply_advance")
            tx_id = self.vadv.grant_credit(
                vendor_id=payload["vendor_id"],
                amount=payload["amount"],
                date=payload["date"],
                notes=payload.get("notes"),
                created_by=payload.get("created_by"),
                source_id=None,
                source_type="deposit",
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
                temp_vendor_bank_name=payload.get("temp_vendor_bank_name"),
                temp_vendor_bank_number=payload.get("temp_vendor_bank_number"),
            )
            self.conn.execute("RELEASE apply_advance")

            info(self.view, "Recorded", f"Advance payment of {amount:,.2f} recorded successfully (Tx #{tx_id}).")

        except Exception as e:
            # Rollback to the savepoint in case of any error
            try:
                self.conn.execute("ROLLBACK TO apply_advance")
                self.conn.execute("RELEASE apply_advance")
            except Exception:
                pass
            if isinstance(e, (ValueError, sqlite3.IntegrityError)):
                info(self.view, "Not recorded", str(e))
                return
            info(self.view, "Not recorded", f"Advance recording failed: {e}")
            return

        self._reload()
    def build_vendor_statement(self, vendor_id: int, *, date_from: Optional[str] = None, date_to: Optional[str] = None, include_opening: bool = True, show_return_origins: bool = False) -> dict:
        opening_credit = 0.0
        opening_payable = 0.0
        if include_opening and date_from:
            row = self.conn.execute(
                """
                WITH pre_period_purchases AS (
                    SELECT COALESCE(
                        SUM(CAST(COALESCE(pdt.calculated_total_amount, p.total_amount) AS REAL)),
                        0.0
                    ) AS amount
                    FROM purchases p
                    LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
                    WHERE p.vendor_id = ?
                      AND DATE(p.date) < DATE(?)
                ),
                pre_period_payments AS (
                    SELECT COALESCE(SUM(CAST(pp.amount AS REAL)), 0.0) AS amount
                    FROM purchase_payments pp
                    JOIN purchases p ON p.purchase_id = pp.purchase_id
                    WHERE p.vendor_id = ?
                      AND LOWER(COALESCE(pp.clearing_state, '')) = 'cleared'
                      AND DATE(pp.date) < DATE(?)
                ),
                pre_period_refunds AS (
                    SELECT COALESCE(SUM(CAST(pr.amount AS REAL)), 0.0) AS amount
                    FROM purchase_refunds pr
                    WHERE pr.vendor_id = ?
                      AND pr.clearing_state = 'cleared'
                      AND DATE(pr.date) < DATE(?)
                ),
                pre_period_deposits AS (
                    SELECT COALESCE(SUM(CAST(va.amount AS REAL)), 0.0) AS amount
                    FROM vendor_advances va
                    WHERE va.vendor_id = ?
                      AND va.source_type = 'deposit'
                      AND DATE(va.tx_date) < DATE(?)
                )
                SELECT
                    pre_period_deposits.amount AS opening_credit,
                    pre_period_purchases.amount
                      - pre_period_payments.amount
                      - pre_period_deposits.amount
                      + pre_period_refunds.amount AS opening_payable
                FROM pre_period_purchases, pre_period_payments,
                     pre_period_refunds, pre_period_deposits
                """,
                (
                    vendor_id, date_from,
                    vendor_id, date_from,
                    vendor_id, date_from,
                    vendor_id, date_from,
                ),
            ).fetchone()
            if row:
                if isinstance(row, sqlite3.Row):
                    opening_credit = float(row["opening_credit"])
                    opening_payable = float(row["opening_payable"])
                else:
                    opening_credit = float(row[0])
                    opening_payable = float(row[1])
        rows: list[dict] = []
        prep = PurchasesRepo(self.conn)
        for p in prep.list_purchases_by_vendor(vendor_id, date_from, date_to):
            amount = float(p["net_total_amount"])
            rows.append({"date": p["date"], "type": "Purchase", "doc_id": p["purchase_id"], "reference": {}, "amount": amount, "amount_effect": amount})
        for pay in self.ppay.list_payments_for_vendor(vendor_id, date_from, date_to):
            if str(pay["clearing_state"] or "").lower() != "cleared":
                continue
            amt = float(pay["amount"])
            row_type = "Cash Payment" if amt >= 0 else "Refund"
            rows.append({"date": pay["date"], "type": row_type, "doc_id": pay["purchase_id"], "reference": {"payment_id": pay["payment_id"], "method": pay["method"], "instrument_no": pay["instrument_no"], "instrument_type": pay["instrument_type"], "bank_account_id": pay["bank_account_id"], "vendor_bank_account_id": pay["vendor_bank_account_id"], "ref_no": pay["ref_no"], "clearing_state": pay["clearing_state"]}, "amount": abs(amt), "amount_effect": -amt})
        refund_sql = [
            """
            SELECT refund_id, purchase_id, date, CAST(amount AS REAL) AS amount,
                   method, instrument_no, instrument_type, bank_account_id,
                   vendor_bank_account_id, ref_no, clearing_state
            FROM purchase_refunds
            WHERE vendor_id = ? AND clearing_state = 'cleared'
            """
        ]
        refund_params: list[object] = [vendor_id]
        if date_from:
            refund_sql.append("AND DATE(date) >= DATE(?)")
            refund_params.append(date_from)
        if date_to:
            refund_sql.append("AND DATE(date) <= DATE(?)")
            refund_params.append(date_to)
        try:
            refund_rows = self.conn.execute(
                "\n".join(refund_sql), refund_params
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: purchase_refunds" not in str(exc):
                raise
            refund_rows = []
        for refund in refund_rows:
            amount = float(refund["amount"])
            rows.append({
                "date": refund["date"],
                "type": "Refund",
                "doc_id": refund["purchase_id"],
                "reference": {
                    "refund_id": refund["refund_id"],
                    "method": refund["method"],
                    "instrument_no": refund["instrument_no"],
                    "instrument_type": refund["instrument_type"],
                    "bank_account_id": refund["bank_account_id"],
                    "vendor_bank_account_id": refund["vendor_bank_account_id"],
                    "ref_no": refund["ref_no"],
                    "clearing_state": refund["clearing_state"],
                },
                "amount": amount,
                "amount_effect": amount,
            })
        credit_note_rows_to_enrich: list[tuple[int, dict]] = []
        def advance_reference(a) -> dict:
            ref = {"tx_id": a["tx_id"]}
            keys = set(a.keys()) if hasattr(a, "keys") else set()
            for key in (
                "method",
                "bank_account_id",
                "vendor_bank_account_id",
                "instrument_type",
                "instrument_no",
                "instrument_date",
                "deposited_date",
                "cleared_date",
                "clearing_state",
                "ref_no",
                "temp_vendor_bank_name",
                "temp_vendor_bank_number",
            ):
                if key in keys:
                    ref[key] = a[key]
            return ref
        for a in self.vadv.list_ledger(vendor_id, date_from, date_to):
            amt = float(a["amount"])
            src_type = (a["source_type"] or "").lower()
            if src_type == "return_credit":
                row = {"date": a["tx_date"], "type": "Credit Note", "doc_id": a["source_id"], "reference": advance_reference(a), "amount": abs(amt), "amount_effect": 0.0}
                rows.append(row)
                if show_return_origins and a["source_id"]:
                    credit_note_rows_to_enrich.append((a["tx_id"], row))
            elif src_type == "applied_to_purchase":
                rows.append({"date": a["tx_date"], "type": "Credit Applied", "doc_id": a["source_id"], "reference": advance_reference(a), "amount": abs(amt), "amount_effect": 0.0})
            else:
                rows.append({"date": a["tx_date"], "type": "Credit Note", "doc_id": a["source_id"], "reference": advance_reference(a), "amount": abs(amt), "amount_effect": -amt})
        if show_return_origins and credit_note_rows_to_enrich:
            for _tx_id, row in credit_note_rows_to_enrich:
                pid = row.get("doc_id")
                if pid:
                    try:
                        lines = prep.list_return_values_by_purchase(pid)
                        if lines:
                            row.setdefault("reference", {})["lines"] = list(lines)
                    except Exception:
                        _log.exception("Failed to load return-origin lines for purchase_id=%s", pid)
                        pass
        type_order = {"Purchase": 1, "Cash Payment": 2, "Refund": 3, "Credit Note": 4, "Credit Applied": 5}
        def tie_value(r: dict):
            ref = r.get("reference", {}) or {}
            return r.get("doc_id") or ref.get("payment_id") or ref.get("refund_id") or ref.get("tx_id") or ""
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
                totals["purchases"] += abs(float(r["amount"]))
            elif r["type"] == "Cash Payment":
                totals["cash_paid"] += abs(float(r["amount"]))
            elif r["type"] == "Refund":
                totals["refunds"] += abs(float(r["amount"]))
            elif r["type"] == "Credit Note":
                totals["credit_notes"] += abs(float(r["amount"]))
            elif r["type"] == "Credit Applied":
                totals["credit_applied"] += abs(float(r["amount"]))
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

    def _on_history(self):
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return
        try:
            from .payment_history_view import open_vendor_history
        except Exception as e:
            info(self.view, "Unavailable", f"Vendor history view is not available: {e}")
            return

        try:
            payload = self.build_vendor_statement(int(vid))
            open_vendor_history(
                vendor_id=int(vid),
                history=payload,
                vendor_display=self._current_vendor_display_text(vid),
            )
        except Exception as e:
            info(self.view, "Error", f"Could not open vendor history:\n{e}")
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
            return self._with_bank_account_savepoint(lambda: self.vbank.create(vid, data))
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not create bank account:\n{e}")
            return None
    def update_bank_account(self, account_id: int, data: dict) -> bool:
        try:
            return self._with_bank_account_savepoint(
                lambda: self.vbank.update(account_id, data)
            ) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not update bank account:\n{e}")
            return False
    def deactivate_bank_account(self, account_id: int) -> bool:
        try:
            return self._with_bank_account_savepoint(
                lambda: self.vbank.deactivate(account_id)
            ) > 0
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Not saved", f"Could not deactivate bank account:\n{e}")
            return False
    def set_primary_bank_account(self, account_id: int) -> bool:
        vid = self._selected_id()
        if not vid:
            info(self.view, "Select", "Please select a vendor first.")
            return False
        try:
            self._with_bank_account_savepoint(
                lambda: self.vbank.force_set_primary(vid, account_id)
            )
            return True
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
        try:
            existing_vid = getattr(form, "_vendor_id", None)
            if existing_vid:
                self.repo.update(existing_vid, **payload)
                info(self.view, "Saved", f"Vendor #{existing_vid} updated.")
            else:
                vid = self.repo.create(**payload)
                info(self.view, "Saved", f"Vendor #{vid} created.")
        except (VendorsDomainError, sqlite3.IntegrityError) as e:
            info(self.view, "Not saved", f"Could not save vendor:\n{e}")
            return
        self._reload()
    def _import_vendors(self):
        path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Import Vendors",
            "",
            "Excel Workbooks (*.xlsx)",
        )
        if not path:
            return
        try:
            try:
                from inventory_management.scripts.bulk_import_vendors import (
                    ImportValidationError,
                    import_vendors_from_xlsx,
                )
            except ModuleNotFoundError:
                from scripts.bulk_import_vendors import (  # type: ignore
                    ImportValidationError,
                    import_vendors_from_xlsx,
                )

            result = import_vendors_from_xlsx(self.conn, Path(path))
        except ImportError as exc:
            info(self.view, "Import failed", f"Import helper could not load.\n\n{exc}")
            return
        except ImportValidationError as exc:
            failed_count = getattr(exc, "failed_count", 0)
            info(
                self.view,
                "Import failed",
                f"Imported vendors: 0\nSkipped/failed rows: {failed_count}\n\n{exc}",
            )
            return
        except (sqlite3.Error, OSError, ValueError) as exc:
            info(
                self.view,
                "Import failed",
                f"Imported vendors: 0\nSkipped/failed rows: unknown\n\n{exc}",
            )
            return

        info(
            self.view,
            "Import complete",
            (
                f"Imported vendors: {result.imported_count}\n"
                f"Skipped/failed rows: {result.failed_count}"
            ),
        )
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
        try:
            self.repo.update(vid, **payload)
        except (VendorsDomainError, sqlite3.IntegrityError) as e:
            info(self.view, "Not saved", f"Could not save vendor:\n{e}")
            return
        info(self.view, "Saved", f"Vendor #{vid} updated.")
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
        from PySide6 import QtWidgets, QtCore, QtGui
        dlg = QtWidgets.QDialog(self.view)
        dlg.setWindowTitle("Grant Credit and Auto-Apply")
        dlg.setModal(True)
        layout = QtWidgets.QVBoxLayout(dlg)
        vendor_label = QtWidgets.QLabel(f"Selected vendor: {self._current_vendor_display_text(vendor_id)}")
        vendor_label.setWordWrap(True)
        layout.addWidget(vendor_label)
        description = QtWidgets.QLabel(
            "This will create vendor credit, then apply it to the oldest open purchases first."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        policy = QtWidgets.QLabel(
            "FIFO means oldest purchase date first, then purchase ID ascending."
        )
        policy.setWordWrap(True)
        layout.addWidget(policy)
        form = QtWidgets.QFormLayout()
        amt_edit = QtWidgets.QLineEdit(dlg)
        amt_edit.setPlaceholderText("Amount (e.g., 1000.00)")
        amt_edit.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        amount_validator = QtGui.QDoubleValidator(0.0, 999999999999.99, 2, dlg)
        amount_validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        amt_edit.setValidator(amount_validator)
        memo_edit = QtWidgets.QLineEdit(dlg)
        memo_edit.setPlaceholderText("Optional note/memo")
        date_edit = QtWidgets.QDateEdit(dlg)
        date_edit.setCalendarPopup(True)
        date_edit.setDate(QtCore.QDate.currentDate())
        form.addRow("Amount", amt_edit)
        form.addRow("Memo", memo_edit)
        form.addRow("Date", date_edit)
        layout.addLayout(form)
        summary_label = QtWidgets.QLabel("Total credit: 0.00")
        layout.addWidget(summary_label)
        preview_empty_label = QtWidgets.QLabel("")
        preview_empty_label.setWordWrap(True)
        layout.addWidget(preview_empty_label)
        preview_table = QtWidgets.QTableWidget(0, 5, dlg)
        preview_table.setHorizontalHeaderLabels(
            ["Purchase", "Date", "Current due", "Apply credit", "Due after"]
        )
        preview_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        preview_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        preview_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        preview_table.verticalHeader().setVisible(False)
        preview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(preview_table)
        remaining_label = QtWidgets.QLabel("Remaining available credit after allocation: 0.00")
        layout.addWidget(remaining_label)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        btn_box.button(QtWidgets.QDialogButtonBox.Ok).setText("Grant Credit")
        layout.addWidget(btn_box)
        def _fmt_money(value: float | int | None) -> str:
            try:
                return f"{float(value or 0.0):,.2f}"
            except Exception:
                return "0.00"
        def _set_preview_item(row: int, col: int, value: str, align_right: bool = False):
            item = QtWidgets.QTableWidgetItem(value)
            if align_right:
                item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            preview_table.setItem(row, col, item)
        def _refresh_preview():
            raw = amt_edit.text().strip()
            try:
                amount = float(raw)
            except Exception:
                amount = 0.0
            if amount <= 0:
                preview = {
                    "total_credit": max(0.0, amount),
                    "rows": [],
                    "remaining_credit": max(0.0, amount),
                }
            else:
                preview = self._build_grant_credit_allocation_preview(vendor_id, amount)
            summary_label.setText(f"Total credit being granted: {_fmt_money(preview['total_credit'])}")
            if amount <= 0:
                preview_empty_label.setText("Enter an amount to preview allocation.")
                preview_table.setRowCount(0)
            else:
                preview_table.setRowCount(max(1, len(preview["rows"])))
                if preview["rows"]:
                    preview_empty_label.setText("")
                    for row_idx, row in enumerate(preview["rows"]):
                        _set_preview_item(row_idx, 0, str(row["purchase_id"]))
                        _set_preview_item(row_idx, 1, str(row["date"] or ""))
                        _set_preview_item(row_idx, 2, _fmt_money(row["remaining_due"]), True)
                        _set_preview_item(row_idx, 3, _fmt_money(row["amount_to_apply"]), True)
                        _set_preview_item(row_idx, 4, _fmt_money(row["remaining_due_after"]), True)
                else:
                    preview_empty_label.setText("No open purchases will receive credit.")
                    _set_preview_item(0, 0, "No open purchases")
                    _set_preview_item(0, 1, "-")
                    _set_preview_item(0, 2, "-")
                    _set_preview_item(0, 3, "-")
                    _set_preview_item(0, 4, "-")
            preview_table.resizeColumnsToContents()
            if amount > 0 and preview["rows"]:
                remaining_label.setText(
                    f"Remaining available vendor credit after allocation: {_fmt_money(preview['remaining_credit'])}"
                )
            elif amount > 0:
                remaining_label.setText(
                    f"Remaining available vendor credit: {_fmt_money(preview['remaining_credit'])}"
                )
            else:
                remaining_label.setText("Remaining available vendor credit: 0.00")
        amt_edit.textChanged.connect(_refresh_preview)
        _refresh_preview()
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
                result = self._grant_credit_and_auto_apply(
                    vendor_id=vendor_id,
                    amount=amount,
                    grant_date=(grant_date or (today_str() if callable(today_str) else today_str)),
                    memo=memo,
                )
                if float(result.get("applied_amount", 0.0)) > 0:
                    message = (
                        f"Credit granted. {result['applied_amount']:,.2f} applied to open purchase orders. "
                        f"{float(result.get('remaining_credit', 0.0)):,.2f} remains available."
                    )
                else:
                    message = (
                        f"Credit granted. No open purchases received credit yet. "
                        f"{float(result.get('remaining_credit', 0.0)):,.2f} remains available."
                    )
                uih.info(
                    self.view,
                    "Success",
                    message,
                )
                try:
                    if hasattr(self, "_update_details"):
                        self._update_details()
                except Exception as ui_error:
                    _log.error(f"Error updating UI after vendor advance grant: {ui_error}")
                    # Continue with accepting the dialog even if UI update fails
                dlg.accept()
            except Exception as e:
                uih.info(self.view, "Error", f"Unable to grant credit: {e}")
        btn_box.accepted.connect(_on_ok)
        btn_box.rejected.connect(dlg.reject)
        dlg.exec()
