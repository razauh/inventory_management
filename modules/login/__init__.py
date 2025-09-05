# /home/pc/Desktop/inventory_management/modules/login/__init__.py

"""
Login module package exports.

- LoginController: orchestrates the login flow (reads users from DB, verifies password).
- LoginForm: simple username/password dialog (Qt). Imported lazily to stay usable
  in headless/test environments where Qt might not be available.
"""

from .controller import LoginController

# Import the form defensively so headless environments can still import the package.
try:
    from .form import LoginForm  # type: ignore
except Exception:  # pragma: no cover - optional UI dependency
    LoginForm = None  # type: ignore

__all__ = [
    "LoginController",
    "LoginForm",
]
