# /home/pc/Desktop/inventory_management/modules/dashboard/__init__.py

"""
Dashboard module package exports.
"""

from .controller import DashboardController

# UI pieces are optional to avoid a hard Qt dependency during headless tests
try:
    from .view import DashboardView  # type: ignore
except Exception:  # pragma: no cover
    DashboardView = None  # type: ignore

__all__ = [
    "DashboardController",
    "DashboardView",
]