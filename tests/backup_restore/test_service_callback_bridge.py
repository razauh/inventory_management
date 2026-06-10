from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from inventory_management.modules.backup_restore.service import _CallbackBridge


@dataclass
class _Callbacks:
    phase: object
    progress: object
    log: object
    finished: object


class _Worker(QObject):
    done = Signal()

    def __init__(self, bridge: _CallbackBridge) -> None:
        super().__init__()
        self._bridge = bridge

    @Slot()
    def run(self) -> None:
        self._bridge.phase_requested.emit("Snapshotting database")
        self._bridge.progress_requested.emit(42)
        self._bridge.log_requested.emit("snapshot created")
        self._bridge.finished_requested.emit(True, "done", "/tmp/backup.imsdb")
        self.done.emit()


def test_callback_bridge_dispatches_worker_events_on_qapp_thread(qtbot, qapp):
    events: list[tuple[str, object, object]] = []

    def record(name: str, value: object, extra: Optional[object] = None) -> None:
        events.append((name, value if extra is None else (value, extra), QThread.currentThread()))

    callbacks = _Callbacks(
        phase=lambda text: record("phase", text),
        progress=lambda pct: record("progress", pct),
        log=lambda line: record("log", line),
        finished=lambda ok, message, path: record("finished", ok, (message, path)),
    )
    bridge = _CallbackBridge(callbacks)
    worker = _Worker(bridge)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit)

    thread.start()
    qtbot.waitUntil(lambda: len(events) == 4)
    thread.quit()
    thread.wait(1000)

    assert [(name, value) for name, value, _ in events] == [
        ("phase", "Snapshotting database"),
        ("progress", 42),
        ("log", "snapshot created"),
        ("finished", (True, ("done", "/tmp/backup.imsdb"))),
    ]
    assert all(callback_thread == qapp.thread() for _, _, callback_thread in events)
