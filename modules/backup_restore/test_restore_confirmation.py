from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QMessageBox, QWidget

from modules.backup_restore import service, sqlite_ops
from modules.backup_restore.controller import BackupRestoreController


class _AppDbManager:
    def close_all(self) -> None:
        raise AssertionError("restore job should not run in this controller test")

    def open(self) -> None:
        raise AssertionError("restore job should not run in this controller test")


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


def _controller(qtbot) -> BackupRestoreController:
    controller = BackupRestoreController(
        app_db_manager=_AppDbManager(),
        settings_org="TestOrg",
        settings_app="RestoreConfirmation",
    )
    controller._widget = QWidget()
    qtbot.addWidget(controller._widget)
    return controller


def test_restore_confirmation_cancel_prevents_restore_job(qtbot, monkeypatch, tmp_path):
    controller = _controller(qtbot)
    progress = _ProgressDialog()
    source = tmp_path / "backup.imsdb"
    target = tmp_path / "live.db"
    source.write_bytes(b"backup")

    monkeypatch.setattr(sqlite_ops, "get_db_path", lambda: str(target))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    class RestoreJob:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("RestoreJob should not be created when restore is cancelled")

    monkeypatch.setattr(service, "RestoreJob", RestoreJob)

    controller._start_restore(str(source), progress)

    assert progress.shown is False
    assert progress.phases == []
    assert progress.progress == []


def test_restore_confirmation_shows_source_and_target_before_starting_job(qtbot, monkeypatch, tmp_path):
    controller = _controller(qtbot)
    progress = _ProgressDialog()
    source = tmp_path / "backup.imsdb"
    target = tmp_path / "live.db"
    source.write_bytes(b"backup")
    calls: list[tuple[str, object]] = []
    messages: list[str] = []

    monkeypatch.setattr(sqlite_ops, "get_db_path", lambda: str(target))

    def confirm(parent, title, text, buttons, default_button):
        messages.append(text)
        assert title == "Confirm Restore"
        assert buttons == QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        assert default_button == QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", confirm)

    class RestoreJob:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run_async(self, src_file: str, callbacks) -> None:
            calls.append((src_file, callbacks))

    monkeypatch.setattr(service, "RestoreJob", RestoreJob)

    controller._start_restore(str(source), progress)

    assert len(calls) == 1
    assert calls[0][0] == str(source)
    assert progress.phases == ["Starting restore…"]
    assert progress.progress == [0]
    assert progress.shown is True
    assert messages
    assert str(Path(source)) in messages[0]
    assert str(Path(target)) in messages[0]
