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
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from constants import (
    APP_BACKUP_DIR_NAME,
    APP_BACKUP_FILE_PREFIX,
    APP_SETTINGS_NAME,
    APP_SETTINGS_ORG,
)
from PySide6.QtCore import Qt, QObject, Signal, Slot, QCoreApplication, QTimer, QSettings, QEventLoop
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QFrame,
    QMessageBox,
    QTabWidget,
)

# Lazy imports within methods keep startup light, but we import the Qt types above for typing/usage.
from ..notifications import notify_info, notify_success


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
    operation_controls_enabled_changed = Signal(bool)

    TITLE = "Backup & Restore"
    SETTINGS_SCOPE = (APP_SETTINGS_ORG, APP_SETTINGS_NAME)
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
        self._active_job: Optional[str] = None
        self._operation_buttons: list[QPushButton] = []

        # Menu actions (created on demand)
        self._act_backup: Optional[QAction] = None
        self._act_restore: Optional[QAction] = None
        self._file_menu: Optional[QMenu] = None

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
            self._act_backup.triggered.connect(self.open_backup_dialog)

        if self._act_restore is None:
            self._act_restore = QAction("Restore Database…", self._widget or None)
            self._act_restore.triggered.connect(self.open_restore_dialog)

        # Put actions under File menu (create if missing)
        file_menu = self._file_menu
        if file_menu is not None:
            try:
                file_menu.actions()
            except RuntimeError:
                file_menu = None

        if file_menu is None:
            for action in menu_bar.actions():
                try:
                    menu = action.menu()
                    if menu and menu.title().replace("&", "").lower() == "file":
                        file_menu = menu
                        break
                except RuntimeError:
                    continue

        if file_menu is None:
            file_menu = QMenu("&File", menu_bar)
            menu_bar.addMenu(file_menu)
        self._file_menu = file_menu

        actions = file_menu.actions()
        actions_to_add = [
            action
            for action in (self._act_backup, self._act_restore)
            if action not in actions
        ]
        if actions_to_add:
            if actions and not actions[-1].isSeparator():
                file_menu.addSeparator()
            for action in actions_to_add:
                file_menu.addAction(action)

    def teardown(self) -> None:
        # Nothing long-lived besides QSettings and signals
        self._widget = None

    def open_backup_dialog(self) -> Optional[QDialog]:
        return self._open_backup_dialog()

    def open_restore_dialog(self) -> None:
        self._open_restore_dialog()

    def create_backup_for_update(self, dest_dir: Optional[str] = None, parent: Optional[QWidget] = None) -> bool:
        if self._is_job_active():
            self._show_active_job_message()
            return False

        from .service import BackupJob
        from .views import ProgressDialog

        base_dir = Path(dest_dir) if dest_dir else Path.home() / APP_BACKUP_DIR_NAME
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(parent or self._widget, "Backup Error", str(exc))
            return False

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest = base_dir / f"{APP_BACKUP_FILE_PREFIX}_pre_update_{stamp}.imsdb"
        prog = ProgressDialog(parent=parent or self._widget or None)
        loop = QEventLoop()
        result = {"ok": False}

        def _finished(ok: bool, message: str, out_path: Optional[str]) -> None:
            result["ok"] = bool(ok and out_path)
            self._on_backup_finished(ok, message, out_path, prog)
            loop.quit()

        if not self._begin_job("backup"):
            return False

        cb = _Callbacks(
            phase=prog.on_phase,
            progress=prog.on_progress,
            log=prog.on_log,
            finished=_finished,
        )
        prog.on_phase("Starting backup...")
        prog.on_progress(0)
        prog.show()
        try:
            BackupJob(db_locator=None, sqlite_ops=None, fsops=None, logger=None).run_async(str(dest), callbacks=cb)
            loop.exec()
        except Exception as exc:
            self._finish_job("backup")
            QMessageBox.critical(self._widget, "Backup Error", str(exc))
            return False
        return bool(result["ok"])

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

        tabs = QTabWidget()
        root.addWidget(tabs)

        backup_restore_tab = QWidget()
        backup_restore_root = QVBoxLayout(backup_restore_tab)
        backup_restore_root.setContentsMargins(0, 12, 0, 0)
        backup_restore_root.setSpacing(16)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        backup_restore_root.addLayout(cards)

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
        backup_restore_root.addWidget(self._last_label)
        backup_restore_root.addStretch(1)

        purge_tab = self._build_purge_tab()
        tabs.addTab(backup_restore_tab, "Backup / Restore")
        tabs.addTab(purge_tab, "Purge Data")

        root.addStretch(1)
        return w

    def _build_purge_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        title = QLabel("Purge business activity rows while keeping master data.")
        title.setWordWrap(True)
        root.addWidget(title)

        detail = QLabel(
            "Deletes sales, purchases, payments, returns, inventory movement, valuation history, and expenses. "
            "Keeps products, UoMs, vendors, customers, company info, users, audit logs, and error logs."
        )
        detail.setWordWrap(True)
        root.addWidget(detail)

        btn = QPushButton("Purge Data…")
        btn.clicked.connect(self._open_purge_dialog)
        self._operation_buttons.append(btn)
        root.addWidget(btn, alignment=Qt.AlignLeft)
        root.addStretch(1)
        return tab

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
        self._operation_buttons.append(btn)
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
    def _open_backup_dialog(self) -> Optional[QDialog]:
        if self._is_job_active():
            self._show_active_job_message()
            return None

        from .views import BackupDialog, ProgressDialog  # lazy import
        from . import __init__ as pkg_init  # for module title if needed

        dlg = BackupDialog(parent=self._widget or None)
        prog = ProgressDialog(parent=dlg)

        # Wire dialog → start job
        dlg.start_backup.connect(lambda dest: self._start_backup(dest, prog))
        dlg.show()
        return dlg

    @Slot()
    def _open_restore_dialog(self) -> None:
        if self._is_job_active():
            self._show_active_job_message()
            return

        from .views import RestoreDialog, ProgressDialog  # lazy import

        dlg = RestoreDialog(parent=self._widget or None)
        prog = ProgressDialog(parent=dlg)

        dlg.start_restore.connect(lambda src: self._start_restore(src, prog))
        dlg.show()

    @Slot()
    def _open_purge_dialog(self) -> None:
        if self._is_job_active():
            self._show_active_job_message()
            return

        from .views import ProgressDialog, PurgeConfirmationDialog

        dlg = PurgeConfirmationDialog(parent=self._widget or None)
        prog = ProgressDialog(parent=dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._start_purge(dlg.backup_path if dlg.create_backup else None, prog)

    # -------- Orchestration with service layer --------

    def _is_job_active(self) -> bool:
        return self._active_job is not None

    def _show_active_job_message(self) -> None:
        notify_info(
            self._widget,
            "Backup & Restore Busy",
            "A backup or restore operation is already running.",
        )

    def _set_operation_controls_enabled(self, enabled: bool) -> None:
        for action in (self._act_backup, self._act_restore):
            if action is not None:
                action.setEnabled(enabled)
        for button in self._operation_buttons:
            try:
                button.setEnabled(enabled)
            except RuntimeError:
                continue
        self.operation_controls_enabled_changed.emit(enabled)

    def _begin_job(self, job_name: str) -> bool:
        if self._active_job is not None:
            self._show_active_job_message()
            return False
        self._active_job = job_name
        self._set_operation_controls_enabled(False)
        return True

    def _finish_job(self, job_name: str) -> None:
        if self._active_job == job_name:
            self._active_job = None
            self._set_operation_controls_enabled(True)

    def _start_backup(self, dest_path: str, prog_dialog) -> None:
        """
        Kick off an async backup job to write a single *.imsdb file.
        """
        from .service import BackupJob  # lazy import

        if self._is_job_active():
            self._show_active_job_message()
            return

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

        if not self._begin_job("backup"):
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
        try:
            job.run_async(str(dest), callbacks=cb)
        except Exception as exc:
            self._finish_job("backup")
            QMessageBox.critical(self._widget, "Backup Error", str(exc))

    def _on_backup_finished(self, ok: bool, message: str, out_path: Optional[str], prog_dialog) -> None:
        try:
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
        finally:
            self._finish_job("backup")

    def _start_restore(self, src_file: str, prog_dialog) -> None:
        """
        Kick off an async restore job from a *.imsdb file.
        """
        from . import sqlite_ops  # lazy import
        from .service import RestoreJob  # lazy import

        if self._is_job_active():
            self._show_active_job_message()
            return

        # Ensure we have a DB manager to coordinate connections.
        if self._app_db_manager is None:
            QMessageBox.critical(
                self._widget,
                "Restore Error",
                "No database manager available to coordinate connections during restore.",
            )
            return

        try:
            target_db_path = Path(sqlite_ops.get_db_path())
        except Exception as exc:
            QMessageBox.critical(
                self._widget,
                "Restore Error",
                f"Unable to resolve the live database path.\n\n{exc}",
            )
            return

        if not self._confirm_restore(src_file, str(target_db_path)):
            return

        if not self._begin_job("restore"):
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
        try:
            job.run_async(str(src_file), callbacks=cb)
        except Exception as exc:
            self._finish_job("restore")
            QMessageBox.critical(self._widget, "Restore Error", str(exc))

    def _start_purge(self, backup_path: Optional[str], prog_dialog) -> None:
        from .service import PurgeJob

        if self._is_job_active():
            self._show_active_job_message()
            return
        if backup_path is not None and not backup_path.strip():
            QMessageBox.critical(self._widget, "Purge Error", "Backup path is required.")
            return
        if not self._begin_job("purge"):
            return

        cb = _Callbacks(
            phase=prog_dialog.on_phase,
            progress=prog_dialog.on_progress,
            log=prog_dialog.on_log,
            finished=lambda ok, msg, out_path: self._on_purge_finished(ok, msg, out_path, prog_dialog),
        )
        prog_dialog.on_phase("Starting purge…")
        prog_dialog.on_progress(0)
        prog_dialog.show()

        try:
            PurgeJob(sqlite_ops=None, logger=None).run_async(backup_path, callbacks=cb)
        except Exception as exc:
            self._finish_job("purge")
            QMessageBox.critical(self._widget, "Purge Error", str(exc))

    def _on_purge_finished(self, ok: bool, message: str, backup_path: Optional[str], prog_dialog) -> None:
        try:
            prog_dialog.on_log(message)
            prog_dialog.on_finished(ok, message, backup_path)
            if ok:
                if backup_path:
                    self._save_last_backup_path(Path(backup_path))
                notify_success(
                    self._widget,
                    "Purge Completed",
                    f"Data purge completed successfully."
                    + (f"\n\nBackup created:\n{backup_path}" if backup_path else ""),
                )
            else:
                QMessageBox.critical(self._widget, "Purge Failed", message)
        finally:
            self._finish_job("purge")

    def _confirm_restore(self, src_file: str, target_db_path: str) -> bool:
        ret = QMessageBox.warning(
            self._widget,
            "Confirm Restore",
            "Restoring will replace the current database.\n\n"
            f"Backup file:\n{Path(src_file)}\n\n"
            f"Current database:\n{Path(target_db_path)}\n\n"
            "A safety copy of the current database will be created first.\n"
            "Continue with restore?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return ret == QMessageBox.StandardButton.Yes

    def _on_restore_finished(self, ok: bool, message: str, used_path: Optional[str], prog_dialog) -> None:
        from .service import RESTORE_RESTART_REQUIRED_MARKER

        try:
            restart_required = RESTORE_RESTART_REQUIRED_MARKER in message
            display_message = message.replace(RESTORE_RESTART_REQUIRED_MARKER, "").strip()

            prog_dialog.on_log(display_message)
            prog_dialog.on_finished(ok, display_message, used_path)

            if ok:
                self.restore_completed.emit(used_path or "")
                if self._widget:
                    QMessageBox.information(
                        self._widget,
                        "Restore Completed",
                        "Database restore completed successfully.\n"
                        "The application must now close. Please restart it before continuing.",
                    )
                QTimer.singleShot(0, QCoreApplication.quit)
            else:
                if self._widget:
                    QMessageBox.critical(self._widget, "Restore Failed", display_message)
                if restart_required:
                    QTimer.singleShot(0, QCoreApplication.quit)
        finally:
            self._finish_job("restore")
