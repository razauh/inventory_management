import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QMainWindow, QMenu

from modules.backup_restore.controller import BackupRestoreController


def _menu_titles(menu_bar):
    return [
        action.menu().title()
        for action in menu_bar.actions()
        if action.menu() is not None
    ]


def _non_separator_texts(menu):
    return [
        action.text()
        for action in menu.actions()
        if not action.isSeparator()
    ]


def test_register_menu_actions_reuses_file_menu_without_tmp_menu(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    menu_bar = window.menuBar()
    file_menu = QMenu("&File", menu_bar)
    menu_bar.addMenu(file_menu)

    controller = BackupRestoreController(settings_org="TestOrg", settings_app="TestApp")
    controller.register_menu_actions(menu_bar)

    assert _menu_titles(menu_bar) == ["&File"]
    assert "tmp" not in _menu_titles(menu_bar)
    assert _non_separator_texts(file_menu) == [
        "Backup Database…",
        "Restore Database…",
    ]


def test_register_menu_actions_is_idempotent(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    menu_bar = window.menuBar()

    controller = BackupRestoreController(settings_org="TestOrg", settings_app="TestApp")
    controller.register_menu_actions(menu_bar)
    controller.register_menu_actions(menu_bar)

    assert _menu_titles(menu_bar) == ["&File"]
    file_menu = menu_bar.actions()[0].menu()
    assert _non_separator_texts(file_menu) == [
        "Backup Database…",
        "Restore Database…",
    ]
    assert sum(1 for action in file_menu.actions() if action.isSeparator()) == 0
