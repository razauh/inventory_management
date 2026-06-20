from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import QMessageBox, QWidget

from ..base_module import BaseModule
from ...database.repositories.company_info_repo import CompanyInfoRepo
from ...utils import ui_helpers as uih
from .form import BankAccountForm, CompanyInfoForm
from .model import CompanyBankAccountsTableModel
from .view import CompanyInfoView


class CompanyInfoController(BaseModule):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.repo = CompanyInfoRepo(conn)
        self.view = CompanyInfoView()
        self.model = CompanyBankAccountsTableModel([])
        self.view.bank_table.setModel(self.model)
        self._wire()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_edit_company.clicked.connect(self._edit_company)
        self.view.btn_delete_company.clicked.connect(self._delete_company)
        self.view.btn_add_bank.clicked.connect(self._add_bank)
        self.view.btn_edit_bank.clicked.connect(self._edit_bank)
        self.view.btn_delete_bank.clicked.connect(self._delete_bank)
        self.view.btn_primary_bank.clicked.connect(self._set_primary_bank)

    def _reload(self):
        company = self.repo.get()
        self._show_company(company)
        rows = self.repo.list_bank_accounts(active_only=False)
        self.model.replace(rows)
        self.view.bank_status.setText(f"{len(rows)} account(s)" if company else "Add company info before bank accounts.")
        self.view.bank_table.resizeColumnsToContents()
        has_company = bool(company)
        self.view.btn_delete_company.setEnabled(has_company)
        self.view.btn_add_bank.setEnabled(has_company)
        has_bank = bool(rows)
        self.view.btn_edit_bank.setEnabled(has_bank)
        self.view.btn_delete_bank.setEnabled(has_bank)
        self.view.btn_primary_bank.setEnabled(has_bank)

    def _show_company(self, company: dict | None):
        if not company:
            self.view.company_details.setPlainText("No company info configured.")
            return
        lines = [
            company.get("company_name") or "",
            company.get("address_line1") or company.get("address") or "",
            company.get("address_line2") or "",
            " ".join(
                part
                for part in [
                    company.get("city"),
                    company.get("state_region"),
                    company.get("postal_code"),
                ]
                if part
            ),
            company.get("country") or "",
            company.get("phone") and f"Phone: {company.get('phone')}",
            company.get("email") and f"Email: {company.get('email')}",
            company.get("website") and f"Website: {company.get('website')}",
            company.get("tax_number") and f"Tax/NTN/Reg No: {company.get('tax_number')}",
            company.get("logo_path") and f"Logo: {company.get('logo_path')}",
            company.get("invoice_footer_note") and f"Footer: {company.get('invoice_footer_note')}",
            company.get("terms_text") and f"Terms: {company.get('terms_text')}",
            "Active" if company.get("is_active") else "Inactive",
        ]
        self.view.company_details.setPlainText("\n".join(str(line) for line in lines if line))

    def _selected_bank_id(self) -> int | None:
        selection = self.view.bank_table.selectionModel()
        if not selection:
            return None
        rows = selection.selectedRows()
        if not rows:
            return None
        row = self.model.row_at(rows[0].row())
        return int(row["account_id"]) if row else None

    def _edit_company(self):
        dlg = CompanyInfoForm(self.view, self.repo.get())
        if dlg.exec():
            try:
                self.repo.save(dlg.payload())
            except Exception as exc:
                QMessageBox.warning(self.view, "Save Failed", str(exc))
                return
            self._reload()
            uih.info(self.view, "Saved", "Company info saved.")

    def _delete_company(self):
        if QMessageBox.question(
            self.view,
            "Delete Company Info",
            "Delete company info? Invoices will use the fallback name.",
        ) != QMessageBox.Yes:
            return
        try:
            self.repo.delete()
        except Exception as exc:
            QMessageBox.warning(self.view, "Delete Blocked", str(exc))
            return
        self._reload()

    def _add_bank(self):
        dlg = BankAccountForm(self.view)
        if dlg.exec():
            self._save_bank(dlg.payload())

    def _edit_bank(self):
        account_id = self._selected_bank_id()
        if account_id is None:
            uih.info(self.view, "Select", "Select a bank account.")
            return
        dlg = BankAccountForm(self.view, self.repo.get_bank_account(account_id))
        if dlg.exec():
            self._save_bank(dlg.payload(), account_id)

    def _save_bank(self, payload: dict, account_id: int | None = None):
        try:
            self.repo.save_bank_account(payload, account_id)
        except Exception as exc:
            QMessageBox.warning(self.view, "Save Failed", str(exc))
            return
        self._reload()
        uih.info(self.view, "Saved", "Bank account saved.")

    def _delete_bank(self):
        account_id = self._selected_bank_id()
        if account_id is None:
            uih.info(self.view, "Select", "Select a bank account.")
            return
        if QMessageBox.question(
            self.view,
            "Delete Bank Account",
            "Delete this bank account? Used accounts will be deactivated.",
        ) != QMessageBox.Yes:
            return
        try:
            self.repo.delete_bank_account(account_id)
        except Exception as exc:
            QMessageBox.warning(self.view, "Delete Failed", str(exc))
            return
        self._reload()

    def _set_primary_bank(self):
        account_id = self._selected_bank_id()
        if account_id is None:
            uih.info(self.view, "Select", "Select a bank account.")
            return
        try:
            self.repo.set_primary_bank_account(account_id)
        except Exception as exc:
            QMessageBox.warning(self.view, "Primary Failed", str(exc))
            return
        self._reload()
