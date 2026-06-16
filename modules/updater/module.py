from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ..base_module import BaseModule
from .views import UpdateCenterView


class UpdatesModule(BaseModule):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._updater = main_window._get_updater_controller()
        self.view = UpdateCenterView()
        self._wire()
        self._updater.emit_state()

    def _wire(self) -> None:
        self.view.refresh_requested.connect(lambda: self._updater.check_now(manual=True))
        self.view.update_now_requested.connect(lambda: self._updater.download_update(True))
        self.view.download_requested.connect(lambda: self._updater.download_update(False))
        self.view.remind_later_requested.connect(self._updater.defer_current_update)
        self.view.install_requested.connect(self._updater.install_downloaded_update)
        self.view.backup_requested.connect(self._updater.open_backup_tool)
        self.view.clear_download_requested.connect(self._updater.clear_download)
        self._updater.state_changed.connect(self.view.render_state)

    def get_widget(self) -> QWidget:
        return self.view

    def refresh(self) -> None:
        self._updater.emit_state()


def create_module(main_window) -> UpdatesModule:
    return UpdatesModule(main_window)
