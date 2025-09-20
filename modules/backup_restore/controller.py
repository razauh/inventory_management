"""
modules/backup_restore/controller.py

Purpose
-------
Glue between the app shell and the Backup/Restore workflows; owns the top-level widget.

This controller stays thin: it wires UI events (from views.py) to long-running
jobs (from service.py), coordinates DB connection lifecycle on restore, and
surfaces progress/results to the user.

Public Interface (called by app shell)
--------------------------------------
- get_widget() -> QWidget
- get_title() -> str
- register_menu_actions(menu_bar) -> None
- teardown() -> None
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import Qt, QObject, Signal, Slot, QCoreApplication, QTimer, QSettings
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QMessageBox,
)

# Lazy imports within methods keep startup light, but we import the Qt types above for typing/usage.


# ----------------------------
# Small typed callback adapter
# ----------------------------

@dataclass
class _Callbacks:
    phase: Callable[[str], None]
    progress: Callable[[int], None]
    log: Callable[[str], None]
    finished: Callable[[bool, str, Optional[str]], None]


# ----------------------------
# Controller
# ----------------------------

class BackupRestoreController(QObject):
    """
    Main controller for the Backup & Restore module.

    Dependencies can be injected for testing:
    - app_db_manager: object with close_all() and open() methods (used during restore).
    - settings_org/settings_app: used for QSettings key-space (remember last backup path).
    """

    # Signals for higher-level app (optional; not strictly required by shell)
    backup_completed = Signal(str)        # emits path to created backup
    restore_completed = Signal(str)       # emits path of backup used to restore

    TITLE = "Backup & Restore"
    SETTINGS_SCOPE = ("YourCompany", "YourApp")  # override via ctor args if needed
    SETTINGS_KEY_LAST_BACKUP = "backup_restore/last_backup_path"

    def __init__(
        self,
        app_db_manager: Optional[object] = None,
        settings_org: Optional[str] = None,
        settings_app: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        if settings_org and settings_app:
            self._settings_org, self._settings_app = settings_org, settings_app
        else:
            self._settings_org, self._settings_app = self.SETTINGS_SCOPE

        self._settings = QSettings(self._settings_org, self._settings_app)

        # App DB manager should provide: close_all(), open()
        self._app_db_manager = app_db_manager

        self._widget: Optional[QWidget] = None
        self._last_backup_path: Optional[Path] = self._load_last_backup_path()

        # Menu actions (created on demand)
        self._act_backup: Optional[QAction] = None
        self._act_restore: Optional[QAction] = None

    # -------- Public API expected by the shell --------

    def get_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = self._build_widget()
        return self._widget

    def get_title(self) -> str:
        return self.TITLE

    def register_menu_actions(self, menu_bar) -> None:
        """
        Register "File → Backup Database…" and "File → Restore Database…" actions.

        The menu_bar is expected to be a QMenuBar (or compatible) provided by the shell.
        """
        # Create or reuse actions
        if self._act_backup is None:
            self._act_backup = QAction("Backup Database…", self._widget or None)
            self._act_backup.triggered.connect(self._open_backup_dialog)

        if self._act_restore is None:
            self._act_restore = QAction("Restore Database…", self._widget or None)
            self._act_restore.triggered.connect(self._open_restore_dialog)

        # Put actions under File menu (create if missing)
        file_menu = None
        for menu in menu_bar.findChildren(type(menu_bar.addMenu("tmp"))):
            if menu.title().replace("&", "").lower() == "file":
                file_menu = menu
                break

        if file_menu is None:
            file_menu = menu_bar.addMenu("&File")

        file_menu.addSeparator()
        file_menu.addAction(self._act_backup)
        file_menu.addAction(self._act_restore)

    def teardown(self) -> None:
        # Nothing long-lived besides QSettings and signals
        self._widget = None

    # -------- UI construction --------

    def _build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel(self.TITLE)
        title.setProperty("class", "h2")  # let global QSS style it if present
        title.setTextInteractionFlags(Qt.NoTextInteraction)
        root.addWidget(title)

        subtitle = QLabel("Create a snapshot of your database, or restore from a previous snapshot.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: palette(mid);")
        root.addWidget(subtitle)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        root.addLayout(cards)

        backup_card = self._make_card(
            "Backup Database",
            "Create a consistent snapshot of the live SQLite database (*.imsdb).",
            primary=True,
            on_click=self._open_backup_dialog,
        )
        restore_card = self._make_card(
            "Restore Database",
            "Replace the current database with a previously created snapshot (*.imsdb).\n"
            "A safety copy of your current database will be created.",
            primary=False,
            on_click=self._open_restore_dialog,
        )

        cards.addWidget(backup_card)
        cards.addWidget(restore_card)

        # Last backup info (if any)
        self._last_label = QLabel(self._format_last_backup_label())
        self._last_label.setWordWrap(True)
        self._last_label.setStyleSheet("color: palette(dark);")
        root.addWidget(self._last_label)

        root.addStretch(1)
        return w

    def _make_card(self, title: str, text: str, primary: bool, on_click: Callable[[], None]) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setProperty("card", True)
        card.setStyleSheet("QFrame[card='true'] { border: 1px solid palette(midlight); border-radius: 12px; }")

        v = QVBoxLayout(card)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        lbl_t = QLabel(title)
        lbl_t.setProperty("class", "h3")
        v.addWidget(lbl_t)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        v.addWidget(lbl)

        v.addStretch(1)

        btn = QPushButton("Backup…" if primary else "Restore…")
        if primary:
            btn.setDefault(True)
        btn.clicked.connect(on_click)
        v.addWidget(btn, alignment=Qt.AlignRight)

        return card

    def _format_last_backup_label(self) -> str:
        if self._last_backup_path and self._last_backup_path.exists():
            return f"Last backup: {self._last_backup_path}"
        return "No backups created in this session."

    def _save_last_backup_path(self, path: Path) -> None:
        self._settings.setValue(self.SETTINGS_KEY_LAST_BACKUP, str(path))
        self._last_backup_path = path
        if hasattr(self, "_last_label"):
            self._last_label.setText(self._format_last_backup_label())

    def _load_last_backup_path(self) -> Optional[Path]:
        val = self._settings.value(self.SETTINGS_KEY_LAST_BACKUP, "", str)
        p = Path(val) if val else None
        return p if p and str(p).strip() else None

    # -------- Dialog launchers --------

    @Slot()
    def _open_backup_dialog(self) -> None:
        from .views import BackupDialog, ProgressDialog  # lazy import
        from . import __init__ as pkg_init  # for module title if needed

        dlg = BackupDialog(parent=self._widget or None)
        prog = ProgressDialog(parent=dlg)

        # Wire dialog → start job
        dlg.start_backup.connect(lambda dest: self._start_backup(dest, prog))
        dlg.show()

    @Slot()
    def _open_restore_dialog(self) -> None:
        from .views import RestoreDialog, ProgressDialog  # lazy import

        dlg = RestoreDialog(parent=self._widget or None)
        prog = ProgressDialog(parent=dlg)

        dlg.start_restore.connect(lambda src: self._start_restore(src, prog))
        dlg.show()

    # -------- Orchestration with service layer --------

    def _start_backup(self, dest_path: str, prog_dialog) -> None:
        """
        Kick off an async backup job to write a single *.imsdb file.
        """
        from .service import BackupJob  # lazy import

        # Basic destination sanity (existence/writability). Service will also validate.
        dest = Path(dest_path)
        try:
            if not dest.parent.exists():
                raise ValueError("Destination folder does not exist.")
            if dest.exists() and not dest.is_file():
                raise ValueError("Destination path is not a file.")
        except Exception as e:
            QMessageBox.critical(self._widget, "Backup Error", str(e))
            return

        # Progress callbacks
        cb = _Callbacks(
            phase=prog_dialog.on_phase,
            progress=prog_dialog.on_progress,
            log=prog_dialog.on_log,
            finished=lambda ok, msg, out_path: self._on_backup_finished(ok, msg, out_path, prog_dialog),
        )

        prog_dialog.on_phase("Starting backup…")
        prog_dialog.on_progress(0)
        prog_dialog.show()

        job = BackupJob(db_locator=None, sqlite_ops=None, fsops=None, logger=None)  # real deps are resolved inside service
        job.run_async(str(dest), callbacks=cb)

    def _on_backup_finished(self, ok: bool, message: str, out_path: Optional[str], prog_dialog) -> None:
        prog_dialog.on_log(message)
        prog_dialog.on_finished(ok, message, out_path)
        if ok and out_path:
            p = Path(out_path)
            self._save_last_backup_path(p)
            self.backup_completed.emit(str(p))

            # Offer to open the folder
            if self._widget:
                ret = QMessageBox.information(
                    self._widget,
                    "Backup Completed",
                    f"Backup created:\n{p}\n\nOpen containing folder?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if ret == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(p.parent.as_uri())

    def _start_restore(self, src_file: str, prog_dialog) -> None:
        """
        Kick off an async restore job from a *.imsdb file.
        """
        from .service import RestoreJob  # lazy import

        # Ensure we have a DB manager to coordinate connections.
        if self._app_db_manager is None:
            QMessageBox.critical(
                self._widget,
                "Restore Error",
                "No database manager available to coordinate connections during restore.",
            )
            return

        # Progress callbacks
        cb = _Callbacks(
            phase=prog_dialog.on_phase,
            progress=prog_dialog.on_progress,
            log=prog_dialog.on_log,
            finished=lambda ok, msg, used: self._on_restore_finished(ok, msg, used, prog_dialog),
        )

        prog_dialog.on_phase("Starting restore…")
        prog_dialog.on_progress(0)
        prog_dialog.show()

        job = RestoreJob(
            db_locator=None,
            sqlite_ops=None,
            fsops=None,
            app_db_manager=self._app_db_manager,
            logger=None,
        )
        job.run_async(str(src_file), callbacks=cb)

    def _on_restore_finished(self, ok: bool, message: str, used_path: Optional[str], prog_dialog) -> None:
        prog_dialog.on_log(message)
        prog_dialog.on_finished(ok, message, used_path)

        if ok:
            self.restore_completed.emit(used_path or "")
            # Inform the user the DB connection was restarted
            if self._widget:
                QMessageBox.information(
                    self._widget,
                    "Restore Completed",
                    "Database restore completed successfully.\n"
                    "The application database connection has been restarted.",
                )
        else:
            if self._widget:
                QMessageBox.critical(self._widget, "Restore Failed", message)
