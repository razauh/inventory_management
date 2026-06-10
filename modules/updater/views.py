from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .models import UpdateInfo


class UpdateAvailableDialog(QDialog):
    def __init__(self, update: UpdateInfo, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.choice = "later"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(f"Version {update.release.version} is available.")
        title.setProperty("class", "h3")
        root.addWidget(title)

        root.addWidget(QLabel(f"Current version: {update.local_version}"))
        root.addWidget(QLabel(f"Installer: {update.installer_asset.name}"))

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setMaximumHeight(160)
        notes.setPlainText(update.release.body or "No release notes were provided.")
        root.addWidget(notes)

        warning = QLabel(
            "Before installing this update, create a database backup. "
            "The update will not start until you acknowledge this warning."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #9b4d00;")
        root.addWidget(warning)

        self.backup_checkbox = QCheckBox("I understand that I should create a backup before installing.")
        root.addWidget(self.backup_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.backup_btn = QPushButton("Create Backup Now")
        self.install_btn = QPushButton("Download and Install")
        self.later_btn = QPushButton("Later")
        self.install_btn.setEnabled(False)
        buttons.addWidget(self.backup_btn)
        buttons.addWidget(self.install_btn)
        buttons.addWidget(self.later_btn)
        root.addLayout(buttons)

        self.backup_checkbox.toggled.connect(self.install_btn.setEnabled)
        self.backup_btn.clicked.connect(self._backup)
        self.install_btn.clicked.connect(self._install)
        self.later_btn.clicked.connect(self.reject)

    def _backup(self) -> None:
        self.choice = "backup"
        self.accept()

    def _install(self) -> None:
        self.choice = "install"
        self.accept()
