from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter


def configure_contains_completer(combo: QComboBox) -> QCompleter:
    completer = combo.completer()
    if completer is None:
        completer = QCompleter(combo.model(), combo)
        combo.setCompleter(completer)
    else:
        completer.setModel(combo.model())
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    return completer
