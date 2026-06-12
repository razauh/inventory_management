from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .downloader import download_asset, download_text
from .logging_utils import get_logger, log_event
from .models import UpdateInfo
from .service import UpdaterService
from .verifier import parse_expected_sha256, verify_sha256
from .views import UpdateAvailableDialog, UpdateProgressDialog


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished_successfully = Signal(str)
    failed = Signal(str)

    def __init__(self, update: UpdateInfo, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.update = update

    def run(self) -> None:
        try:
            download_dir = Path(tempfile.mkdtemp(prefix="alhusnain-update-"))
            self.status.emit("Downloading update installer...")

            def progress_callback(bytes_written: int, total_bytes: int | None) -> None:
                if total_bytes:
                    pct = int(bytes_written * 100 / total_bytes)
                    self.progress.emit(max(0, min(100, pct)))
                else:
                    self.progress.emit(0)

            installer = download_asset(
                self.update.installer_asset,
                dest_dir=download_dir,
                progress_callback=progress_callback,
            )

            if self.update.checksum_asset is None:
                raise RuntimeError("Release checksum asset is missing.")

            self.status.emit("Downloading checksum...")
            checksum_text = download_text(self.update.checksum_asset)

            self.status.emit("Verifying checksum...")
            expected = parse_expected_sha256(checksum_text, self.update.installer_asset.name)
            if expected is None:
                raise RuntimeError("Release checksum did not include the installer asset.")

            verify_sha256(installer, expected)
            self.finished_successfully.emit(str(installer))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class UpdaterController(QObject):
    _check_finished = Signal(object, bool, str)

    SETTINGS_SCOPE = ("Al Husnain", "Al Husnain")
    SETTINGS_KEY_AUTO_CHECK = "updater/auto_check"
    SETTINGS_KEY_INCLUDE_PRERELEASE = "updater/include_prerelease"

    def __init__(self, main_window, service: UpdaterService | None = None, parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._service = service or UpdaterService()
        self._settings = QSettings(*self.SETTINGS_SCOPE)
        self._log = get_logger()
        self._active = False
        self._check_finished.connect(self._on_check_finished)

    def check_on_startup(self) -> None:
        enabled = self._settings.value(self.SETTINGS_KEY_AUTO_CHECK, True, bool)
        if not enabled:
            return
        QTimer.singleShot(1500, lambda: self.check_now(manual=False))

    def check_now(self, *, manual: bool = True) -> None:
        if self._active:
            return
        self._active = True
        include_prerelease = self._settings.value(self.SETTINGS_KEY_INCLUDE_PRERELEASE, False, bool)
        worker = threading.Thread(
            target=self._run_check,
            args=(bool(manual), bool(include_prerelease)),
            daemon=True,
        )
        worker.start()

    def _run_check(self, manual: bool, include_prerelease: bool) -> None:
        try:
            update = self._service.check_for_update(include_prerelease=include_prerelease)
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"
            log_event(self._log, "check_failed", "Update check failed.", error=error)
            self._check_finished.emit(None, manual, str(exc))
            return
        self._check_finished.emit(update, manual, "")

    @Slot(object, bool, str)
    def _on_check_finished(self, update: UpdateInfo | None, manual: bool, error: str) -> None:
        self._active = False
        if error:
            if manual:
                QMessageBox.warning(self._main_window, "Update Check Failed", error)
            return
        if update is None:
            if manual:
                QMessageBox.information(self._main_window, "No Update Available", "You are using the latest version.")
            return
        self.open_update_dialog(update)

    def open_update_dialog(self, update: UpdateInfo) -> None:
        while True:
            dialog = UpdateAvailableDialog(update, self._main_window)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                log_event(self._log, "postponed", "User postponed update.", tag=update.release.tag_name)
                return
            if dialog.choice == "backup":
                self._open_backup_screen()
                continue
            if dialog.choice == "install":
                self._confirm_and_install(update)
                return

    def _open_backup_screen(self) -> None:
        if hasattr(self._main_window, "_get_backup_restore_controller"):
            controller = self._main_window._get_backup_restore_controller()
            if controller is not None and hasattr(controller, "open_backup_dialog"):
                controller.open_backup_dialog()
                return
        QMessageBox.warning(
            self._main_window,
            "Backup Required",
            "Open Backup & Restore and create a backup before installing the update.",
        )

    def _confirm_and_install(self, update: UpdateInfo) -> None:
        backup_ok = self._offer_programmatic_backup()
        if not backup_ok:
            if not self._confirm_skip_backup():
                return

        progress_dialog = UpdateProgressDialog(self._main_window)
        self._download_worker = UpdateDownloadWorker(update, self)

        self._download_worker.status.connect(progress_dialog.set_status)
        self._download_worker.progress.connect(progress_dialog.set_progress)

        installer_path: Path | None = None
        error_message: str | None = None

        def on_success(path_str: str) -> None:
            nonlocal installer_path
            installer_path = Path(path_str)
            progress_dialog.allow_close()
            progress_dialog.accept()

        def on_failure(msg: str) -> None:
            nonlocal error_message
            error_message = msg
            progress_dialog.allow_close()
            progress_dialog.reject()

        self._download_worker.finished_successfully.connect(on_success)
        self._download_worker.failed.connect(on_failure)

        self._download_worker.start()
        progress_dialog.exec()

        self._download_worker = None

        if error_message:
            log_event(self._log, "download_failed", "Update download failed.", error=error_message)
            QMessageBox.critical(self._main_window, "Update Failed", error_message)
            return

        if installer_path is None:
            return

        log_event(self._log, "verified", "Installer checksum verified.", path=str(installer_path))

        if QMessageBox.question(
            self._main_window,
            "Install Update",
            "The installer is ready. The application will close before the installer starts.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._launch_installer(installer_path)

    def _offer_programmatic_backup(self) -> bool:
        controller = None
        if hasattr(self._main_window, "_get_backup_restore_controller"):
            controller = self._main_window._get_backup_restore_controller()
        if controller is None or not hasattr(controller, "create_backup_for_update"):
            QMessageBox.information(
                self._main_window,
                "Create Backup",
                "Automatic update backup is not available yet. Please create a backup from Backup & Restore.",
            )
            self._open_backup_screen()
            return False
        reply = QMessageBox.question(
            self._main_window,
            "Create Backup",
            "Create a backup before installing this update?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return bool(controller.create_backup_for_update())

    def _confirm_skip_backup(self) -> bool:
        return QMessageBox.warning(
            self._main_window,
            "Continue Without Backup?",
            "If the update fails, your current data may be harder to recover. Continue without a new backup?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes



    def _launch_installer(self, installer: Path) -> None:
        self._close_database_before_install()
        try:
            subprocess.Popen([str(installer)], close_fds=True)
        except OSError as exc:
            QMessageBox.critical(self._main_window, "Update Failed", f"Could not start installer.\n\n{exc}")
            return
        QApplication.quit()

    def _close_database_before_install(self) -> None:
        conn = getattr(self._main_window, "conn", None)
        if conn is None:
            return
        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
            self._main_window.conn = None
        except Exception:
            pass
