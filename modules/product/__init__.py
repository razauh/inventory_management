# /home/pc/Desktop/inventory_management/modules/product/__init__.py

"""
Product module package exports.

- ProductController: orchestrates product CRUD and UoM role management.
- Optional UI parts (ProductView, ProductForm, UomPicker, UomManagerDialog)
  and models (ProductsTableModel, ProductFilterProxy) are imported defensively
  so tests/headless environments can import this package without a Qt runtime.
"""

# Core controller (safe to import without a GUI)
from .controller import ProductController

# Optional UI pieces & models (guard to avoid hard Qt dependency in headless runs)
try:
    from .view import ProductView  # type: ignore
    from .form import ProductForm, UomPicker  # type: ignore
    from .model import ProductsTableModel, ProductFilterProxy  # type: ignore
    from .uom_management import UomManagerDialog  # type: ignore
except Exception:  # pragma: no cover
    ProductView = None  # type: ignore
    ProductForm = None  # type: ignore
    UomPicker = None  # type: ignore
    ProductsTableModel = None  # type: ignore
    ProductFilterProxy = None  # type: ignore
    UomManagerDialog = None  # type: ignore

__all__ = [
    "ProductController",
    "ProductView",
    "ProductForm",
    "UomPicker",
    "UomManagerDialog",
    "ProductsTableModel",
    "ProductFilterProxy",
]
