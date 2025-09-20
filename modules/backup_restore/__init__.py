"""
Backup & Restore module package.

- Keeps imports light by deferring controller import until create_module() is called.
- Exposes MODULE_TITLE and create_module() for the app shell.
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

MODULE_TITLE: str = "Backup & Restore"
__all__ = ["MODULE_TITLE", "create_module"]


class _BaseModuleLike(Protocol):
    """Minimal contract expected by the app shell."""
    def get_widget(self): ...
    def get_title(self) -> str: ...
    def teardown(self) -> None: ...


if TYPE_CHECKING:
    # Only for type-checkers; avoids runtime import cost.
    from .controller import BackupRestoreController  # pragma: no cover


def create_module() -> _BaseModuleLike:
    """
    Factory: returns the module controller instance.

    Importing the controller here (instead of at module import time) keeps
    startup overhead low.
    """
    from .controller import BackupRestoreController
    return BackupRestoreController()
