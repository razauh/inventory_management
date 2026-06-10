from PySide6.QtWidgets import QMessageBox, QWidget

from inventory_management.modules.backup_restore import controller as controller_module
from inventory_management.modules.backup_restore.controller import BackupRestoreController


class _ProgressDialog:
    def __init__(self):
        self.logs = []
        self.finished = None

    def on_log(self, message):
        self.logs.append(message)

    def on_finished(self, ok, message, used_path):
        self.finished = (ok, message, used_path)


def test_successful_restore_completion_requires_application_restart(qtbot, monkeypatch):
    controller = BackupRestoreController()
    controller._widget = QWidget()
    qtbot.addWidget(controller._widget)
    progress = _ProgressDialog()
    messages = []
    scheduled = []
    emitted = []

    def quit_app():
        pass

    class Timer:
        @staticmethod
        def singleShot(delay_ms, callback):
            scheduled.append((delay_ms, callback))

    class CoreApplication:
        quit = staticmethod(quit_app)

    controller.restore_completed.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text: messages.append((parent, title, text)),
    )
    monkeypatch.setattr(controller_module, "QTimer", Timer)
    monkeypatch.setattr(controller_module, "QCoreApplication", CoreApplication)

    controller._on_restore_finished(
        True,
        "Restore completed successfully.",
        "/tmp/backup.imsdb",
        progress,
    )

    assert progress.finished == (
        True,
        "Restore completed successfully.",
        "/tmp/backup.imsdb",
    )
    assert emitted == ["/tmp/backup.imsdb"]
    assert messages
    assert "must now close" in messages[0][2]
    assert scheduled == [(0, quit_app)]


def test_failed_restore_completion_does_not_request_restart(qtbot, monkeypatch):
    controller = BackupRestoreController()
    controller._widget = QWidget()
    qtbot.addWidget(controller._widget)
    progress = _ProgressDialog()
    scheduled = []

    class Timer:
        @staticmethod
        def singleShot(delay_ms, callback):
            scheduled.append((delay_ms, callback))

    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(controller_module, "QTimer", Timer)

    controller._on_restore_finished(False, "Restore failed.", None, progress)

    assert progress.finished == (False, "Restore failed.", None)
    assert scheduled == []
