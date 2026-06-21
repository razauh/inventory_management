# ⚠️ VENDOR MODULE ONLY: Do not modify other modules or shared components. Selection-behavior crash fix only.
from __future__ import annotations
import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QMessageBox, QDialogButtonBox, QFormLayout, QLineEdit, QCheckBox, QAbstractItemView, QLabel
)

from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from ...modules.notifications import notify_warning
from ...utils import ui_helpers as uih
from .model import _mask_value


class AccountEditDialog(QDialog):
    """Add/Edit a single vendor bank account (no 'primary' toggle here)."""
    def __init__(self, parent=None, *, initial: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Bank Account" if initial else "Add Bank Account")
        self._payload = None

        self.txt_label = QLineEdit()
        self.txt_bank = QLineEdit()
        self.txt_acc  = QLineEdit()
        self.txt_iban = QLineEdit()
        self.txt_rout = QLineEdit()
        self.chk_active = QCheckBox("Active")
        self.chk_active.setChecked(True)
        self.txt_label.setPlaceholderText("Account label, like Payroll or AP")
        self.txt_bank.setPlaceholderText("Bank name")
        self.txt_acc.setPlaceholderText("Account number")
        self.txt_iban.setPlaceholderText("IBAN, if used")
        self.txt_rout.setPlaceholderText("Routing number, if used")

        form = QFormLayout()
        form.addRow("Label*", self.txt_label)
        form.addRow("Bank", self.txt_bank)
        form.addRow("Account No", self.txt_acc)
        form.addRow("IBAN", self.txt_iban)
        form.addRow("Routing No", self.txt_rout)
        form.addRow("", self.chk_active)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

        if initial:
            self.txt_label.setText(initial.get("label", "") or "")
            self.txt_bank.setText(initial.get("bank_name", "") or "")
            self.txt_acc.setText(initial.get("account_no", "") or "")
            self.txt_iban.setText(initial.get("iban", "") or "")
            self.txt_rout.setText(initial.get("routing_no", "") or "")
            self.chk_active.setChecked(bool(initial.get("is_active", 1)))

    def accept(self):
        label = (self.txt_label.text() or "").strip()
        if not label:
            QMessageBox.warning(self, "Required", "Label is required.")
            return
        self._payload = {
            "label": label,
            "bank_name": (self.txt_bank.text() or "").strip() or None,
            "account_no": (self.txt_acc.text() or "").strip() or None,
            "iban": (self.txt_iban.text() or "").strip() or None,
            "routing_no": (self.txt_rout.text() or "").strip() or None,
            "is_active": 1 if self.chk_active.isChecked() else 0,
        }
        super().accept()

    def payload(self) -> Optional[dict]:
        return self._payload


class VendorBankAccountsDialog(QDialog):
    """
    Manage a vendor's bank accounts:
      - List: Label, Bank, Account/IBAN, Primary, Active
      - Add/Edit
      - Activate/Deactivate
      - Make Primary (force flip: clear others, set one)
    """
    COLS = ["#", "Label", "Bank", "Account / IBAN", "Primary", "Active"]

    def __init__(self, parent=None, *, conn: sqlite3.Connection, vendor_id: int):
        super().__init__(parent)
        self.setWindowTitle(f"Vendor Bank Accounts — Vendor #{vendor_id}")
        self.conn = conn
        self.vendor_id = int(vendor_id)
        self.repo = VendorBankAccountsRepo(conn)

        # Table
        self.empty_label = QLabel("No bank accounts yet.")
        self.empty_label.setStyleSheet("color: #666;")
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setColumnWidth(0, 40)
        self.tbl.setColumnWidth(1, 220)
        self.tbl.setColumnWidth(2, 140)
        self.tbl.setColumnWidth(3, 220)
        self.tbl.setColumnWidth(4, 80)
        self.tbl.setColumnWidth(5, 80)

        # Buttons
        btns = QHBoxLayout()
        self.btn_add = QPushButton("Add Account")
        self.btn_edit = QPushButton("Edit Account")
        self.btn_toggle = QPushButton("Deactivate")
        self.btn_primary = QPushButton("Set Primary")
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_edit)
        btns.addWidget(self.btn_toggle)
        btns.addWidget(self.btn_primary)
        btns.addStretch(1)

        # Close
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)  # in case you ever flip to OK|Close

        lay = QVBoxLayout(self)
        lay.addWidget(self.empty_label)
        lay.addWidget(self.tbl, 1)
        lay.addLayout(btns)
        lay.addWidget(bb)

        # Wire
        self.btn_add.clicked.connect(self._add)
        self.btn_edit.clicked.connect(self._edit)
        self.btn_toggle.clicked.connect(self._toggle_active)
        self.btn_primary.clicked.connect(self._make_primary)

        self._reload()

    def _reload(self):
        rows = self.conn.execute("""
            SELECT vendor_bank_account_id, label, bank_name, account_no, iban, routing_no,
                   is_primary, is_active
            FROM vendor_bank_accounts
            WHERE vendor_id=?
            ORDER BY is_active DESC, is_primary DESC, label
        """, (self.vendor_id,)).fetchall()

        self.tbl.setRowCount(0)
        for i, r in enumerate(rows, start=1):
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            id_item = QTableWidgetItem(str(i))
            id_item.setData(Qt.UserRole, int(r["vendor_bank_account_id"]))
            self.tbl.setItem(row, 0, id_item)

            self.tbl.setItem(row, 1, QTableWidgetItem(r["label"] or ""))
            self.tbl.setItem(row, 2, QTableWidgetItem(r["bank_name"] or ""))

            acc_line = _mask_value(r["account_no"])
            iban = _mask_value(r["iban"], keep_last=6)
            if iban:
                acc_line = (acc_line + " | " if acc_line else "") + iban
            self.tbl.setItem(row, 3, QTableWidgetItem(acc_line or ""))

            self.tbl.setItem(row, 4, QTableWidgetItem("Yes" if r["is_primary"] else "No"))
            act = bool(r["is_active"])
            self.tbl.setItem(row, 5, QTableWidgetItem("Active" if act else "Inactive"))

        self.empty_label.setVisible(not bool(rows))
        self.tbl.setVisible(bool(rows))
        if rows and not self.tbl.selectionModel().selectedRows():
            self.tbl.selectRow(0)
        self._update_toggle_label()
        self._update_action_states()

    def _selected_id(self) -> Optional[int]:
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return None
        it = self.tbl.item(idxs[0].row(), 0)
        return int(it.data(Qt.UserRole)) if it else None

    def _update_toggle_label(self):
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            self.btn_toggle.setText("Deactivate")
            return
        row = idxs[0].row()
        active_text = self.tbl.item(row, 5).text()
        self.btn_toggle.setText("Deactivate" if active_text == "Active" else "Activate")

    def _update_action_states(self):
        selected = self.tbl.selectionModel().selectedRows()
        has_selection = bool(selected)
        is_active = False
        if has_selection:
            row = selected[0].row()
            active_item = self.tbl.item(row, 5)
            is_active = bool(active_item and active_item.text() == "Active")
        self.btn_edit.setEnabled(has_selection)
        self.btn_toggle.setEnabled(has_selection)
        self.btn_primary.setEnabled(has_selection and is_active)

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

    # ---- Actions ----
    def _add(self):
        dlg = AccountEditDialog(self)
        if not dlg.exec():
            return
        data = dlg.payload()
        if not data:
            return
        try:
            self._with_bank_account_savepoint(
                lambda: self.repo.create(self.vendor_id, data)
            )
        except sqlite3.IntegrityError as e:
            # likely duplicate (vendor_id, label) unique hit or 'one primary' check
            QMessageBox.warning(self, "Not saved", f"Could not add account:\n{e}")
            return
        self._reload()

    def _edit(self):
        acc_id = self._selected_id()
        if not acc_id:
            notify_warning(self, "Select", "Select an account to edit.")
            return
        row = self.conn.execute("""
            SELECT * FROM vendor_bank_accounts WHERE vendor_bank_account_id=? AND vendor_id=?
        """, (acc_id, self.vendor_id)).fetchone()
        if not row:
            uih.info(self, "Not found", "Account not found.")
            return

        init = {
            "label": row["label"], "bank_name": row["bank_name"], "account_no": row["account_no"],
            "iban": row["iban"], "routing_no": row["routing_no"], "is_active": row["is_active"]
        }
        dlg = AccountEditDialog(self, initial=init)
        if not dlg.exec():
            return
        data = dlg.payload()
        if not data:
            return

        try:
            self._with_bank_account_savepoint(lambda: self.repo.update(acc_id, data))
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not saved", f"Could not update account:\n{e}")
            return

        self._reload()

    def _toggle_active(self):
        acc_id = self._selected_id()
        if not acc_id:
            notify_warning(self, "Select", "Select an account to activate/deactivate.")
            return
        row = self.conn.execute("""
            SELECT is_active, is_primary FROM vendor_bank_accounts WHERE vendor_bank_account_id=? AND vendor_id=?
        """, (acc_id, self.vendor_id)).fetchone()
        if not row:
            return
        new_flag = 0 if int(row["is_active"]) else 1
        if new_flag == 0 and int(row["is_primary"]):
            QMessageBox.warning(
                self,
                "Not updated",
                "Choose another active primary account before deactivating this account.",
            )
            return
        if new_flag == 0:
            answer = QMessageBox.question(
                self,
                "Deactivate account?",
                "Deactivate this bank account?\n\nIt will stop appearing as active for vendor workflows.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            self._with_bank_account_savepoint(
                lambda: self.repo.deactivate(acc_id) if new_flag == 0 else self.repo.activate(acc_id)
            )
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not updated", f"Could not update account:\n{e}")
            return
        self._reload()

    def _make_primary(self):
        acc_id = self._selected_id()
        if not acc_id:
            notify_warning(self, "Select", "Select an account to make primary.")
            return
        row = self.conn.execute("""
            SELECT is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id=? AND vendor_id=?
        """, (acc_id, self.vendor_id)).fetchone()
        if not row:
            uih.info(self, "Not found", "Account not found.")
            return
        if not int(row["is_active"]):
            QMessageBox.warning(self, "Inactive", "Activate this account before making it primary.")
            return
        try:
            self._with_bank_account_savepoint(
                lambda: self.repo.force_set_primary(self.vendor_id, acc_id)
            )
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not updated", f"Could not make primary:\n{e}")
            return
        self._reload()

    # keep the toggle button label in sync with selection
    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_toggle_label_hooked", False):
            self.tbl.selectionModel().selectionChanged.connect(lambda *_: (self._update_toggle_label(), self._update_action_states()))
            self._toggle_label_hooked = True
        self._update_toggle_label()
        self._update_action_states()
