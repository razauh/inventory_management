from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QVBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QCheckBox,
    QMessageBox,
)

from ...utils.validators import non_empty


class CustomerForm(QDialog):
    """
    Customer create/edit form.

    Enhancements:
      - Active toggle (schema: customers.is_active) — defaults to ON.
      - Required fields: name, contact info.
      - Whitespace normalization: trims and tidies multi-line inputs.
      - Optional dedup hint: pass a `dup_check` callable to warn if an active
        customer with the same name exists (non-blocking, consistent with vendor side).

    Args:
        parent: Qt parent
        initial: optional dict with keys like
                 {customer_id, name, contact_info, address, is_active}
        dup_check: optional callable (name: str, current_id: Optional[int]) -> bool
                   Return True if another ACTIVE customer with the same name exists.
                   The form will warn but will not block submission.
    """

    def __init__(
        self,
        parent=None,
        initial: dict | None = None,
        dup_check: Optional[Callable[[str, Optional[int]], bool]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Customer")
        self.setModal(True)

        self._dup_check = dup_check
        self._initial = initial or {}

        # --- Fields ---
        self.name = QLineEdit()
        self.contact = QPlainTextEdit()
        self.contact.setPlaceholderText("Phone, email, etc.")
        self.addr = QPlainTextEdit()
        self.addr.setPlaceholderText("Address (optional)")

        self.is_active = QCheckBox("Active")
        self.is_active.setChecked(True)  # default ON

        # --- Layout ---
        form = QFormLayout()
        form.addRow("Name*", self.name)
        form.addRow("Contact Info*", self.contact)
        form.addRow("Address", self.addr)
        form.addRow("", self.is_active)

        root = QVBoxLayout(self)
        root.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        # --- Initial values ---
        if initial:
            self.name.setText(initial.get("name", "") or "")
            self.contact.setPlainText(initial.get("contact_info", "") or "")
            self.addr.setPlainText(initial.get("address", "") or "")
            ia = initial.get("is_active")
            if ia is not None:
                # Accept 1/0, True/False
                self.is_active.setChecked(bool(ia))

        self._payload = None

    # ---------------- helpers ----------------

    @staticmethod
    def _collapse_spaces(line: str) -> str:
        # Collapse runs of whitespace inside a line to a single space
        return re.sub(r"\s+", " ", line).strip()

    def _norm_multiline(self, text: str) -> str:
        """
        Normalize multi-line text:
          - strip each line
          - collapse runs of spaces on each line
          - remove leading/trailing blank lines
        """
        if text is None:
            return ""
        lines = [self._collapse_spaces(l) for l in text.splitlines()]
        # Trim leading/trailing empty lines
        while lines and lines[0] == "":
            lines.pop(0)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines).strip()

    # ---------------- API ----------------

    def get_payload(self) -> dict | None:
        # Validate required
        if not non_empty(self.name.text()):
            self.name.setFocus()
            return None
        if not non_empty(self.contact.toPlainText()):
            self.contact.setFocus()
            return None

        # Normalize
        name = self._collapse_spaces(self.name.text())
        contact_info = self._norm_multiline(self.contact.toPlainText())
        address_norm = self._norm_multiline(self.addr.toPlainText())
        address = address_norm if address_norm else None
        is_active = 1 if self.is_active.isChecked() else 0

        # Optional dedup *warning* (non-blocking)
        if self._dup_check:
            current_id = self._initial.get("customer_id")
            try:
                if self._dup_check(name, current_id):
                    QMessageBox.warning(
                        self,
                        "Possible Duplicate",
                        (
                            "An active customer with the same name already exists.\n\n"
                            "You can still proceed — this is just a heads-up."
                        ),
                    )
            except Exception:
                # If the callback fails, we do not block the user.
                pass

        return {
            "name": name,
            "contact_info": contact_info,
            "address": address,          # optional
            "is_active": is_active,      # schema toggle
        }

    def accept(self):
        p = self.get_payload()
        if p is None:
            return
        self._payload = p
        super().accept()

    def payload(self):
        return self._payload
