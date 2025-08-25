from __future__ import annotations
import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QMessageBox, QDialogButtonBox, QFormLayout, QLineEdit, QCheckBox
)

from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo


class AccountEditDialog(QDialog):
    """Add/Edit a single vendor bank account (no 'primary' toggle here)."""
    def __init__(self, parent=None, *, initial: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Bank Account")
        self._payload = None

        self.txt_label = QLineEdit()
        self.txt_bank = QLineEdit()
        self.txt_acc  = QLineEdit()
        self.txt_iban = QLineEdit()
        self.txt_rout = QLineEdit()
        self.chk_active = QCheckBox("Active")
        self.chk_active.setChecked(True)

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
        self.setWindowTitle("Vendor Bank Accounts")
        self.conn = conn
        self.vendor_id = int(vendor_id)
        self.repo = VendorBankAccountsRepo(conn)

        # Table
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(self.tbl.SelectRows)
        self.tbl.setEditTriggers(self.tbl.NoEditTriggers)
        self.tbl.setColumnWidth(0, 40)
        self.tbl.setColumnWidth(1, 220)
        self.tbl.setColumnWidth(2, 140)
        self.tbl.setColumnWidth(3, 220)
        self.tbl.setColumnWidth(4, 80)
        self.tbl.setColumnWidth(5, 80)

        # Buttons
        btns = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        self.btn_toggle = QPushButton("Deactivate")
        self.btn_primary = QPushButton("Make Primary")
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

            acc_line = (r["account_no"] or "").strip()
            if r["iban"]:
                acc_line = (acc_line + " | " if acc_line else "") + r["iban"]
            self.tbl.setItem(row, 3, QTableWidgetItem(acc_line or ""))

            self.tbl.setItem(row, 4, QTableWidgetItem("Yes" if r["is_primary"] else "No"))
            act = bool(r["is_active"])
            self.tbl.setItem(row, 5, QTableWidgetItem("Active" if act else "Inactive"))

        self._update_toggle_label()

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

    # ---- Actions ----
    def _add(self):
        dlg = AccountEditDialog(self)
        if not dlg.exec():
            return
        data = dlg.payload()
        if not data:
            return
        try:
            self.repo.create(self.vendor_id, data)
        except sqlite3.IntegrityError as e:
            # likely duplicate (vendor_id, label) unique hit or 'one primary' check
            QMessageBox.warning(self, "Not saved", f"Could not add account:\n{e}")
            return
        self._reload()

    def _edit(self):
        acc_id = self._selected_id()
        if not acc_id:
            QMessageBox.information(self, "Select", "Select an account to edit.")
            return
        row = self.conn.execute("""
            SELECT * FROM vendor_bank_accounts WHERE vendor_bank_account_id=? AND vendor_id=?
        """, (acc_id, self.vendor_id)).fetchone()
        if not row:
            QMessageBox.warning(self, "Not found", "Account not found.")
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
            # Prefer repo.update if available; else direct SQL
            if hasattr(self.repo, "update"):
                self.repo.update(acc_id, data)
            else:
                with self.conn:
                    self.conn.execute("""
                        UPDATE vendor_bank_accounts
                           SET label=?, bank_name=?, account_no=?, iban=?, routing_no=?, is_active=?
                         WHERE vendor_bank_account_id=? AND vendor_id=?
                    """, (data["label"], data["bank_name"], data["account_no"], data["iban"], data["routing_no"],
                          int(data["is_active"]), acc_id, self.vendor_id))
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not saved", f"Could not update account:\n{e}")
            return

        self._reload()

    def _toggle_active(self):
        acc_id = self._selected_id()
        if not acc_id:
            QMessageBox.information(self, "Select", "Select an account to activate/deactivate.")
            return
        row = self.conn.execute("""
            SELECT is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id=? AND vendor_id=?
        """, (acc_id, self.vendor_id)).fetchone()
        if not row:
            return
        new_flag = 0 if int(row["is_active"]) else 1
        with self.conn:
            self.conn.execute("""
                UPDATE vendor_bank_accounts SET is_active=? WHERE vendor_bank_account_id=? AND vendor_id=?
            """, (new_flag, acc_id, self.vendor_id))
        self._reload()

    def _make_primary(self):
        acc_id = self._selected_id()
        if not acc_id:
            QMessageBox.information(self, "Select", "Select an account to make primary.")
            return
        # Force-flip primary in one transaction to satisfy the partial-unique constraint
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE vendor_bank_accounts SET is_primary=0 WHERE vendor_id=?", (self.vendor_id,)
                )
                self.conn.execute(
                    "UPDATE vendor_bank_accounts SET is_primary=1 WHERE vendor_bank_account_id=? AND vendor_id=?",
                    (acc_id, self.vendor_id)
                )
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(self, "Not updated", f"Could not make primary:\n{e}")
            return
        self._reload()

    # keep the toggle button label in sync with selection
    def showEvent(self, e):
        super().showEvent(e)
        self.tbl.selectionModel().selectionChanged.connect(lambda *_: self._update_toggle_label())
