# inventory_management/modules/login/view.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QDialogButtonBox, QLabel, QCheckBox, QPushButton, QWidget
)


class LoginDialog(QDialog):
    """
    Enhanced login dialog (UI-only).

    API kept compatible with the basic form:
      - exec() -> int (Accepted / Rejected)
      - get_values() -> tuple[str, str]

    Extra helpers the controller MAY use (optional):
      - set_error(msg: str | None)
      - set_info(msg: str | None)
      - show_busy(is_busy: bool)

    No database or business logic here.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Info / error banners
        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setVisible(False)
        self.lbl_info.setStyleSheet("color:#2b6;")
        root.addWidget(self.lbl_info)

        self.lbl_error = QLabel()
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        # Accessible, high-contrast error style
        self.lbl_error.setStyleSheet(
            "QLabel {background:#fcebea; color:#b10000; border:1px solid #f5c6cb; border-radius:6px; padding:6px;}"
        )
        root.addWidget(self.lbl_error)

        # Form
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setContentsMargins(0, 0, 0, 0)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Your username")
        self.username.setClearButtonEnabled(True)
        form.addRow("Username", self.username)

        pw_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Your password")
        self.password.setClearButtonEnabled(True)
        pw_row.addWidget(self.password, 1)

        self.chk_show = QCheckBox("Show")
        self.chk_show.toggled.connect(self._toggle_password_visibility)
        pw_row.addWidget(self.chk_show, 0, Qt.AlignRight)

        pw_container = QWidget()
        pw_container.setLayout(pw_row)
        form.addRow("Password", pw_container)

        root.addLayout(form)

        # Extras (purely UI; controller may ignore)
        extras = QHBoxLayout()
        self.chk_remember = QCheckBox("Remember me")
        # (Your controller can read this later via isChecked() if you decide to use it.)
        extras.addWidget(self.chk_remember)
        extras.addStretch(1)

        self.btn_forgot = QPushButton("Forgot password…")
        self.btn_forgot.setFlat(True)
        self.btn_forgot.setCursor(Qt.PointingHandCursor)
        # NOTE: leave unconnected; hook it up later if you add a reset flow.
        extras.addWidget(self.btn_forgot)
        root.addLayout(extras)

        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        # Focus UX
        self.username.setFocus()

    # ---------- Public API ----------

    def get_values(self) -> tuple[str, str]:
        """
        Returns (username, password) without trimming password.
        Username is stripped by the controller if desired.
        """
        return self.username.text(), self.password.text()

    def set_error(self, msg: str | None) -> None:
        """Show or clear an error banner."""
        if msg:
            self.lbl_error.setText(msg)
            self.lbl_error.setVisible(True)
        else:
            self.lbl_error.clear()
            self.lbl_error.setVisible(False)

    def set_info(self, msg: str | None) -> None:
        """Show or clear an informational banner."""
        if msg:
            self.lbl_info.setText(msg)
            self.lbl_info.setVisible(True)
        else:
            self.lbl_info.clear()
            self.lbl_info.setVisible(False)

    def show_busy(self, is_busy: bool) -> None:
        """
        Simple busy state: disable inputs and buttons.
        (No spinner to keep dependencies minimal.)
        """
        for w in (self.username, self.password, self.chk_show, self.chk_remember, self.btn_forgot, self.buttons):
            w.setEnabled(not is_busy)

    # ---------- Internals ----------

    def _toggle_password_visibility(self, checked: bool) -> None:
        self.password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
