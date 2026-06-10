from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QMessageBox, QMainWindow, QPushButton

from modules.backup_restore import service, sqlite_ops
from modules.backup_restore.controller import BackupRestoreController


class _AppDbManager:
    def close_all(self) -> None:
        raise AssertionError("restore service should not run in this controller test")

    def open(self) -> None:
        raise AssertionError("restore service should not run in this controller test")


class _ProgressDialog:
    def __init__(self) -> None:
        self.phases: list[str] = []
        self.progress: list[int] = []
        self.shown = False

    def on_phase(self, text: str) -> None:
        self.phases.append(text)

    def on_progress(self, value: int) -> None:
        self.progress.append(value)

    def on_log(self, message: str) -> None:
        pass

    def on_finished(self, ok: bool, message: str, path: str | None) -> None:
        pass

    def show(self) -> None:
        self.shown = True


def _controller_with_actions(qtbot) -> tuple[BackupRestoreController, QMainWindow]:
    window = QMainWindow()
    qtbot.addWidget(window)
    controller = BackupRestoreController(
        app_db_manager=_AppDbManager(),
        settings_org="TestOrg",
        settings_app="ActiveJobGuard",
    )
    qtbot.addWidget(controller.get_widget())
    controller.register_menu_actions(window.menuBar())
    return controller, window


def _operation_buttons(controller: BackupRestoreController) -> list[QPushButton]:
    return [
        button
        for button in controller.get_widget().findChildren(QPushButton)
        if button.text() in {"Backup…", "Restore…"}
    ]


def test_active_backup_blocks_duplicate_backup_jobs_and_reenables_controls(qtbot, monkeypatch, tmp_path):
    controller, _window = _controller_with_actions(qtbot)
    progress_one = _ProgressDialog()
    progress_two = _ProgressDialog()
    dest_one = tmp_path / "one.imsdb"
    dest_two = tmp_path / "two.imsdb"
    calls: list[tuple[str, object]] = []
    messages: list[str] = []
    enabled_changes: list[bool] = []

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: messages.append(args[2]))
    controller.operation_controls_enabled_changed.connect(enabled_changes.append)

    class BackupJob:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run_async(self, dest_file: str, callbacks) -> None:
            calls.append((dest_file, callbacks))

    monkeypatch.setattr(service, "BackupJob", BackupJob)

    controller._start_backup(str(dest_one), progress_one)
    controller._start_backup(str(dest_two), progress_two)

    assert [call[0] for call in calls] == [str(dest_one)]
    assert progress_one.shown is True
    assert progress_two.shown is False
    assert controller._act_backup is not None
    assert controller._act_restore is not None
    assert controller._act_backup.isEnabled() is False
    assert controller._act_restore.isEnabled() is False
    assert all(not button.isEnabled() for button in _operation_buttons(controller))
    assert messages == ["A backup or restore operation is already running."]
    assert enabled_changes == [False]

    calls[0][1].finished(False, "done", None)

    assert controller._act_backup.isEnabled() is True
    assert controller._act_restore.isEnabled() is True
    assert all(button.isEnabled() for button in _operation_buttons(controller))
    assert enabled_changes == [False, True]


def test_active_restore_blocks_duplicate_restore_jobs(qtbot, monkeypatch, tmp_path):
    controller, _window = _controller_with_actions(qtbot)
    progress_one = _ProgressDialog()
    progress_two = _ProgressDialog()
    source_one = tmp_path / "one.imsdb"
    source_two = tmp_path / "two.imsdb"
    target = tmp_path / "live.db"
    source_one.write_bytes(b"backup one")
    source_two.write_bytes(b"backup two")
    target.write_bytes(b"live")
    calls: list[tuple[str, object]] = []
    messages: list[str] = []
    confirmations: list[str] = []

    monkeypatch.setattr(sqlite_ops, "get_db_path", lambda: str(target))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: confirmations.append(args[2]) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: messages.append(args[2]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    class RestoreJob:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run_async(self, src_file: str, callbacks) -> None:
            calls.append((src_file, callbacks))

    monkeypatch.setattr(service, "RestoreJob", RestoreJob)

    controller._start_restore(str(source_one), progress_one)
    controller._start_restore(str(source_two), progress_two)

    assert [call[0] for call in calls] == [str(source_one)]
    assert progress_one.shown is True
    assert progress_two.shown is False
    assert len(confirmations) == 1
    assert messages == ["A backup or restore operation is already running."]

    calls[0][1].finished(False, "done", None)

    assert controller._act_backup is not None
    assert controller._act_restore is not None
    assert controller._act_backup.isEnabled() is True
    assert controller._act_restore.isEnabled() is True
