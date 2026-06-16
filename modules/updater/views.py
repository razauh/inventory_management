from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import UpdateState


class UpdateCenterView(QWidget):
    refresh_requested = Signal()
    update_now_requested = Signal()
    download_requested = Signal()
    remind_later_requested = Signal()
    install_requested = Signal()
    backup_requested = Signal()
    clear_download_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("App Updates")
        title.setProperty("class", "h2")
        root.addWidget(title)

        subtitle = QLabel("Check GitHub releases, download in the background, and install when ready.")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.status_card = QFrame()
        self.status_card.setObjectName("updateStatusCard")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(16, 16, 16, 16)
        status_layout.setSpacing(8)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        self.status_badge = QLabel("Idle")
        self.status_badge.setObjectName("updateStatusBadge")
        badge_row.addWidget(self.status_badge, 0, Qt.AlignLeft)
        badge_row.addStretch(1)
        self.btn_refresh = QPushButton("Check Now")
        badge_row.addWidget(self.btn_refresh)
        status_layout.addLayout(badge_row)

        versions_row = QHBoxLayout()
        versions_row.setContentsMargins(0, 0, 0, 0)
        versions_row.setSpacing(16)
        self.current_version = QLabel("Current version: -")
        self.target_version = QLabel("Available release: -")
        versions_row.addWidget(self.current_version)
        versions_row.addWidget(self.target_version)
        versions_row.addStretch(1)
        status_layout.addLayout(versions_row)

        self.status_detail = QLabel("Use this page to manage app updates.")
        self.status_detail.setWordWrap(True)
        status_layout.addWidget(self.status_detail)

        self.error_label = QLabel("")
        self.error_label.setObjectName("updateErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        status_layout.addWidget(self.error_label)

        root.addWidget(self.status_card)

        self.release_card = QFrame()
        self.release_card.setObjectName("updateReleaseCard")
        release_layout = QVBoxLayout(self.release_card)
        release_layout.setContentsMargins(16, 16, 16, 16)
        release_layout.setSpacing(10)

        release_header = QHBoxLayout()
        release_header.setContentsMargins(0, 0, 0, 0)
        self.release_title = QLabel("No release loaded")
        self.release_title.setProperty("class", "h3")
        release_header.addWidget(self.release_title)
        release_header.addStretch(1)
        self.release_asset = QLabel("")
        release_header.addWidget(self.release_asset)
        release_layout.addLayout(release_header)

        self.release_notes = QPlainTextEdit()
        self.release_notes.setReadOnly(True)
        self.release_notes.setMinimumHeight(180)
        release_layout.addWidget(self.release_notes)

        release_actions = QHBoxLayout()
        release_actions.setContentsMargins(0, 0, 0, 0)
        release_actions.setSpacing(8)
        self.btn_update_now = QPushButton("Update Now")
        self.btn_download_only = QPushButton("Download Only")
        self.btn_remind_later = QPushButton("Remind Me Later")
        release_actions.addWidget(self.btn_update_now)
        release_actions.addWidget(self.btn_download_only)
        release_actions.addWidget(self.btn_remind_later)
        release_actions.addStretch(1)
        release_layout.addLayout(release_actions)

        root.addWidget(self.release_card)

        self.progress_card = QFrame()
        self.progress_card.setObjectName("updateProgressCard")
        progress_layout = QVBoxLayout(self.progress_card)
        progress_layout.setContentsMargins(16, 16, 16, 16)
        progress_layout.setSpacing(8)

        self.progress_title = QLabel("Background Download")
        self.progress_title.setProperty("class", "h3")
        progress_layout.addWidget(self.progress_title)

        self.progress_detail = QLabel("Download has not started.")
        self.progress_detail.setWordWrap(True)
        progress_layout.addWidget(self.progress_detail)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(self.progress_card)

        self.install_card = QFrame()
        self.install_card.setObjectName("updateInstallCard")
        install_layout = QVBoxLayout(self.install_card)
        install_layout.setContentsMargins(16, 16, 16, 16)
        install_layout.setSpacing(8)

        install_title = QLabel("Ready to Install")
        install_title.setProperty("class", "h3")
        install_layout.addWidget(install_title)

        self.install_detail = QLabel(
            "Create a fresh backup before installing. The app will close when the installer starts."
        )
        self.install_detail.setWordWrap(True)
        install_layout.addWidget(self.install_detail)

        install_actions = QHBoxLayout()
        install_actions.setContentsMargins(0, 0, 0, 0)
        install_actions.setSpacing(8)
        self.btn_backup = QPushButton("Create Backup Now")
        self.btn_install = QPushButton("Install and Restart")
        self.btn_clear_download = QPushButton("Remove Download")
        install_actions.addWidget(self.btn_backup)
        install_actions.addWidget(self.btn_install)
        install_actions.addWidget(self.btn_clear_download)
        install_actions.addStretch(1)
        install_layout.addLayout(install_actions)

        root.addWidget(self.install_card)
        root.addStretch(1)

        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_update_now.clicked.connect(self.update_now_requested.emit)
        self.btn_download_only.clicked.connect(self.download_requested.emit)
        self.btn_remind_later.clicked.connect(self.remind_later_requested.emit)
        self.btn_install.clicked.connect(self.install_requested.emit)
        self.btn_backup.clicked.connect(self.backup_requested.emit)
        self.btn_clear_download.clicked.connect(self.clear_download_requested.emit)

        self.release_card.hide()
        self.progress_card.hide()
        self.install_card.hide()

    def render_state(self, state: UpdateState) -> None:
        self.status_badge.setText(state.status_label)
        self.current_version.setText(f"Current version: {state.local_version}")
        self.status_detail.setText(state.detail)
        self.progress_bar.setValue(max(0, min(100, state.progress)))
        self.progress_detail.setText(state.detail)

        has_error = bool(state.error_text)
        self.error_label.setVisible(has_error)
        self.error_label.setText(state.error_text)

        update = state.update
        has_update = update is not None
        self.release_card.setVisible(has_update)
        self.target_version.setText(
            f"Available release: {update.release.tag_name}" if update is not None else "Available release: -"
        )
        if update is not None:
            release_title = update.release.title.strip() or f"Version {update.release.tag_name}"
            if release_title == update.release.tag_name:
                self.release_title.setText(release_title)
            else:
                self.release_title.setText(f"{release_title} ({update.release.tag_name})")
            if update.installer_asset is not None:
                self.release_asset.setText(update.installer_asset.name)
            else:
                self.release_asset.setText("Installer not available")
            self.release_notes.setPlainText(update.release.body or "No release notes were provided.")
        else:
            self.release_title.setText("No release loaded")
            self.release_asset.setText("")
            self.release_notes.setPlainText("")

        is_busy = state.status in {"checking", "downloading"}
        self.btn_refresh.setEnabled(not is_busy)

        release_actions_enabled = (
            has_update
            and update is not None
            and update.can_download
            and state.status not in {"checking", "downloading", "install_ready"}
        )
        self.btn_update_now.setEnabled(release_actions_enabled)
        self.btn_download_only.setEnabled(release_actions_enabled)
        self.btn_remind_later.setEnabled(has_update and state.status not in {"checking", "downloading"})

        show_progress = state.status == "downloading"
        self.progress_card.setVisible(show_progress)

        show_install = state.status == "install_ready"
        self.install_card.setVisible(show_install)


class UpdateToast(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("updateToast")
        self._primary_callback: Callable[[], None] | None = None
        self._secondary_callback: Callable[[], None] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self.title_label = QLabel("Update")
        self.title_label.setObjectName("updateToastTitle")
        root.addWidget(self.title_label)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        root.addWidget(self.message_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.primary_button = QPushButton("Open")
        self.secondary_button = QPushButton("Later")
        actions.addWidget(self.secondary_button)
        actions.addWidget(self.primary_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.primary_button.clicked.connect(self._handle_primary)
        self.secondary_button.clicked.connect(self._handle_secondary)

    def configure(
        self,
        *,
        title: str,
        message: str,
        primary_text: str,
        primary_callback: Callable[[], None] | None,
        secondary_text: str,
        secondary_callback: Callable[[], None] | None,
    ) -> None:
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.primary_button.setText(primary_text)
        self.secondary_button.setText(secondary_text)
        self._primary_callback = primary_callback
        self._secondary_callback = secondary_callback
        self.adjustSize()

    def _handle_primary(self) -> None:
        self.hide()
        if self._primary_callback is not None:
            self._primary_callback()

    def _handle_secondary(self) -> None:
        self.hide()
        if self._secondary_callback is not None:
            self._secondary_callback()
