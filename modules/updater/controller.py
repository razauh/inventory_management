from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import sys
from pathlib import Path

from constants import APP_SETTINGS_NAME, APP_SETTINGS_ORG, APP_UPDATE_TEMP_PREFIX
from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication
from version import APP_VERSION

from .downloader import download_asset, download_text
from .logging_utils import get_logger, log_event
from .models import UpdateInfo, UpdateState
from .service import UpdaterService
from .verifier import parse_expected_sha256, verify_sha256


def _cleanup_dir(dir_path: Path) -> None:
    try:
        if dir_path.exists():
            for item in dir_path.iterdir():
                if item.is_file():
                    item.unlink()
            dir_path.rmdir()
    except Exception:
        pass


def _installer_cache_key(update: UpdateInfo) -> str:
    installer_name = update.installer_asset.name if update.installer_asset is not None else ""
    return f"{update.release.tag_name}|{installer_name}"


def _current_application_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def build_updater_bootstrap_command(
    executable: Path,
    installer: Path,
    install_dir: Path,
    parent_pid: int,
) -> list[str]:
    return [
        str(executable),
        "--updater-bootstrap",
        "--updater-installer",
        str(installer),
        "--updater-install-dir",
        str(install_dir),
        "--updater-parent-pid",
        str(parent_pid),
    ]


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished_successfully = Signal(str)
    failed = Signal(str)

    def __init__(self, update: UpdateInfo, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.update = update

    def run(self) -> None:
        download_dir = None
        succeeded = False
        try:
            if self.update.installer_asset is None:
                raise RuntimeError("Release installer asset is missing.")
            download_dir = Path(tempfile.mkdtemp(prefix=APP_UPDATE_TEMP_PREFIX))
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
            succeeded = True
            self.finished_successfully.emit(str(installer))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
        finally:
            if not succeeded and download_dir is not None:
                _cleanup_dir(download_dir)


class UpdaterController(QObject):
    state_changed = Signal(object)
    _check_finished = Signal(object, bool, str)

    SETTINGS_SCOPE = (APP_SETTINGS_ORG, APP_SETTINGS_NAME)
    SETTINGS_KEY_AUTO_CHECK = "updater/auto_check"
    SETTINGS_KEY_INCLUDE_PRERELEASE = "updater/include_prerelease"
    SETTINGS_KEY_DEFERRED_TAG = "updater/deferred_tag"
    SETTINGS_KEY_PENDING_EXPECTED_VERSION = "updater/pending_expected_version"

    STATUS_LABELS = {
        "idle": "Idle",
        "checking": "Checking for Updates",
        "up_to_date": "Up to Date",
        "update_available": "Update Available",
        "downloading": "Downloading",
        "install_ready": "Ready to Install",
        "deferred": "Reminder Snoozed",
        "error": "Update Error",
    }

    def __init__(self, main_window, service: UpdaterService | None = None, parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._service = service or UpdaterService()
        self._settings = QSettings(*self.SETTINGS_SCOPE)
        self._log = get_logger()
        self._active = False
        self._download_worker: UpdateDownloadWorker | None = None
        self._current_update: UpdateInfo | None = None
        self._download_status = ""
        self._progress = 0
        self._downloaded_installer: Path | None = None
        self._download_cache_key: str | None = None
        self._install_after_download = False
        self._check_finished.connect(self._on_check_finished)
        self._state = UpdateState(
            status="idle",
            status_label=self.STATUS_LABELS["idle"],
            detail="Use the Updates page to check for newer releases.",
            local_version=self._service.local_version,
        )

    def state(self) -> UpdateState:
        return self._state

    def emit_state(self) -> None:
        self.state_changed.emit(self._state)

    def check_on_startup(self) -> None:
        enabled = self._settings.value(self.SETTINGS_KEY_AUTO_CHECK, True, bool)
        if not enabled:
            return
        QTimer.singleShot(1500, lambda: self.check_now(manual=False))

    def open_updates_center(self) -> None:
        if hasattr(self._main_window, "open_module"):
            self._main_window.open_module("Updates")

    def check_now(self, *, manual: bool = True) -> None:
        if self._active:
            if manual:
                self.open_updates_center()
                self.emit_state()
            return
        self._active = True
        if manual:
            self.open_updates_center()
        self._set_state(
            "checking",
            "Checking GitHub for a newer release...",
            update=self._current_update,
        )
        include_prerelease = self._settings.value(self.SETTINGS_KEY_INCLUDE_PRERELEASE, False, bool)
        worker = threading.Thread(
            target=self._run_check,
            args=(bool(manual), bool(include_prerelease)),
            daemon=True,
        )
        worker.start()

    def download_update(self, install_after_download: bool) -> None:
        update = self._current_update
        if update is None:
            self.check_now(manual=True)
            return
        if not update.can_download:
            self._set_state(
                "update_available",
                update.availability_message or f"Release {update.release.tag_name} is visible but cannot be downloaded here.",
                update=update,
                error_text=update.availability_message,
            )
            return
        if self._download_worker is not None:
            self.emit_state()
            return
        cache_key = _installer_cache_key(update)
        if self._downloaded_installer is not None and self._download_cache_key != cache_key:
            self._discard_download_cache()
        if self._downloaded_installer is not None and self._downloaded_installer.exists():
            self._install_after_download = install_after_download
            self._set_state(
                "install_ready",
                "Update package is ready to install.",
                progress=100,
                update=update,
                download_path=str(self._downloaded_installer),
                install_after_download=install_after_download,
            )
            if install_after_download:
                self._show_ready_toast()
            return

        self._install_after_download = install_after_download
        self._download_status = "Preparing download..."
        self._progress = 0
        self._set_state(
            "downloading",
            self._download_status,
            progress=0,
            update=update,
            install_after_download=install_after_download,
        )

        worker = UpdateDownloadWorker(update, self)
        worker.status.connect(self._on_download_status)
        worker.progress.connect(self._on_download_progress)
        worker.finished_successfully.connect(self._on_download_success)
        worker.failed.connect(self._on_download_failure)
        worker.finished.connect(self._on_download_finished)
        self._download_worker = worker
        worker.start()

    def defer_current_update(self) -> None:
        if self._current_update is None:
            return
        self._settings.setValue(self.SETTINGS_KEY_DEFERRED_TAG, self._current_update.release.tag_name)
        log_event(self._log, "deferred", "User deferred update reminder.", tag=self._current_update.release.tag_name)
        self._set_state(
            "deferred",
            f"{self._current_update.release.tag_name} will stay available in this page.",
            update=self._current_update,
        )

    def install_downloaded_update(self) -> None:
        installer = self._downloaded_installer
        if installer is None or not installer.exists():
            self.clear_download()
            self._set_state(
                "error",
                "Downloaded installer is no longer available.",
                update=self._current_update,
                error_text="The downloaded installer could not be found. Download the update again.",
            )
            return

        update = self._current_update
        if update is None:
            self._set_state(
                "error",
                "No update is selected.",
                error_text="The selected update is no longer available.",
            )
            return

        self._close_database_before_install()
        self._settings.setValue(self.SETTINGS_KEY_PENDING_EXPECTED_VERSION, update.release.version)
        self._settings.sync()
        executable = _current_application_executable()
        install_dir = executable.parent
        try:
            bootstrap_command = build_updater_bootstrap_command(
                executable,
                installer,
                install_dir,
                os.getpid(),
            )
            subprocess.Popen(bootstrap_command, close_fds=True)
        except OSError as exc:
            self._settings.remove(self.SETTINGS_KEY_PENDING_EXPECTED_VERSION)
            self._settings.sync()
            error = f"Could not start installer: {exc}"
            log_event(self._log, "launch_failed", "Update installer could not be started.", error=error)
            self._set_state(
                "error",
                "Could not start the installer.",
                update=self._current_update,
                error_text=error,
                download_path=str(installer),
            )
            return
        log_event(
            self._log,
            "installer_started",
            "Installer bootstrap launched.",
            path=str(installer),
            install_dir=str(install_dir),
            parent_pid=os.getpid(),
        )
        QApplication.quit()

    def clear_download(self) -> None:
        self._discard_download_cache()
        self._progress = 0
        self._download_status = ""
        if self._current_update is not None:
            self._set_state(
                "update_available",
                f"Release {self._current_update.release.tag_name} is ready when you want it.",
                update=self._current_update,
            )
        else:
            self._set_state("idle", "Use the Updates page to check for newer releases.")

    def open_backup_tool(self) -> None:
        if hasattr(self._main_window, "_get_backup_restore_controller"):
            controller = self._main_window._get_backup_restore_controller()
            if controller is not None and hasattr(controller, "open_backup_dialog"):
                controller.open_backup_dialog()

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
            self._set_state(
                "error",
                "Could not check for updates.",
                update=self._current_update,
                error_text=error,
            )
            return

        if update is None:
            self._current_update = None
            self._discard_download_cache()
            self._set_state(
                "up_to_date",
                f"Version {self._service.local_version} is the latest available release.",
            )
            return

        if self._download_cache_key != _installer_cache_key(update):
            self._discard_download_cache()
        self._current_update = update
        detail = update.availability_message or f"Release {update.release.tag_name} is available to download."
        self._set_state(
            "update_available",
            detail,
            update=update,
            error_text=update.availability_message,
        )
        if not manual and self._settings.value(self.SETTINGS_KEY_DEFERRED_TAG, "", str) != update.release.tag_name:
            self._show_available_toast(update)

    @Slot(str)
    def _on_download_status(self, text: str) -> None:
        self._download_status = text
        self._set_state(
            "downloading",
            text,
            progress=self._progress,
            update=self._current_update,
            install_after_download=self._install_after_download,
        )

    @Slot(int)
    def _on_download_progress(self, progress: int) -> None:
        self._progress = progress
        self._set_state(
            "downloading",
            self._download_status or "Downloading update installer...",
            progress=progress,
            update=self._current_update,
            install_after_download=self._install_after_download,
        )

    @Slot(str)
    def _on_download_success(self, path_str: str) -> None:
        installer = Path(path_str)
        self._downloaded_installer = installer
        if self._current_update is not None:
            self._download_cache_key = _installer_cache_key(self._current_update)
        self._progress = 100
        log_event(self._log, "verified", "Installer checksum verified.", path=str(installer))
        self._set_state(
            "install_ready",
            "Download finished. The installer is ready.",
            progress=100,
            update=self._current_update,
            download_path=str(installer),
            install_after_download=self._install_after_download,
        )
        self._show_ready_toast()

    @Slot(str)
    def _on_download_failure(self, error_message: str) -> None:
        self._discard_download_cache()
        log_event(self._log, "download_failed", "Update download failed.", error=error_message)
        self._set_state(
            "error",
            "Download failed.",
            progress=self._progress,
            update=self._current_update,
            error_text=error_message,
            install_after_download=self._install_after_download,
        )

    @Slot()
    def _on_download_finished(self) -> None:
        self._download_worker = None

    def _set_state(
        self,
        status: str,
        detail: str,
        *,
        progress: int | None = None,
        update: UpdateInfo | None = None,
        error_text: str = "",
        download_path: str = "",
        install_after_download: bool | None = None,
    ) -> None:
        if progress is None:
            progress = self._progress
        if install_after_download is None:
            install_after_download = self._install_after_download
        self._state = UpdateState(
            status=status,
            status_label=self.STATUS_LABELS.get(status, status.replace("_", " ").title()),
            detail=detail,
            local_version=self._service.local_version,
            progress=progress,
            update=update,
            error_text=error_text,
            download_path=download_path,
            install_after_download=install_after_download,
        )
        self.emit_state()

    def _show_available_toast(self, update: UpdateInfo) -> None:
        if hasattr(self._main_window, "show_update_toast"):
            self._main_window.show_update_toast(
                title="Update Available",
                message=f"Release {update.release.tag_name} is ready.",
                primary_text="Update Now",
                primary_callback=lambda: self.download_update(True),
                secondary_text="View Details",
                secondary_callback=self.open_updates_center,
            )

    def _show_ready_toast(self) -> None:
        update = self._current_update
        if update is None:
            return
        if hasattr(self._main_window, "show_update_toast"):
            self._main_window.show_update_toast(
                title="Update Ready",
                message=f"Release {update.release.tag_name} finished downloading.",
                primary_text="Install Now",
                primary_callback=self.install_downloaded_update,
                secondary_text="View Details",
                secondary_callback=self.open_updates_center,
            )

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

    def _discard_download_cache(self) -> None:
        installer = self._downloaded_installer
        if installer is not None:
            _cleanup_dir(installer.parent)
        self._downloaded_installer = None
        self._download_cache_key = None

    def verify_pending_installation(self) -> bool:
        expected_version = self._settings.value(self.SETTINGS_KEY_PENDING_EXPECTED_VERSION, "", str)
        if not expected_version:
            return True
        if expected_version == APP_VERSION:
            self._settings.remove(self.SETTINGS_KEY_PENDING_EXPECTED_VERSION)
            self._settings.sync()
            log_event(
                self._log,
                "install_verified",
                "Pending update matched the running version.",
                expected_version=expected_version,
                actual_version=APP_VERSION,
            )
            return True
        log_event(
            self._log,
            "install_mismatch",
            "Pending update did not match the running version.",
            expected_version=expected_version,
            actual_version=APP_VERSION,
        )
        return False
