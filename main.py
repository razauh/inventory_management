from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QMessageBox,
    QHBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from pathlib import Path
import sys
import traceback
import os
from importlib import import_module

import sys
from pathlib import Path
# Add the project root to the Python path for imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from constants import APP_NAME, STYLE_FILE
from database import get_connection
from modules.base_module import BaseModule


def load_qss() -> str:
    qss = ""
    f = Path(__file__).resolve().parent / STYLE_FILE
    if f.exists():
        qss = f.read_text(encoding="utf-8")
    return qss


def _lazy_get(name: str, attr: str):
    """Import a module by name and fetch an attribute from it, with a clear error if missing."""
    # Prepend the project root and make sure the package can be imported
    import sys
    import warnings
    from pathlib import Path
    project_root = Path(__file__).resolve().parent
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    # Also make sure the parent of the project root is in the path for absolute imports
    parent_dir = str(project_root.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # Filter out the specific RuntimeWarning about signal disconnection
    warnings.filterwarnings("ignore",
                           message=r".*Failed to disconnect.*selectionChanged.*",
                           category=RuntimeWarning)

    try:
        mod = import_module(name)
    except Exception as e:
        raise ImportError(f"Failed to import module '{name}': {e}") from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise ImportError(f"'{attr}' not found in module '{name}'.") from e


class MainWindow(QMainWindow):
    # -----------------------------
    # Lightweight DB manager shim
    # -----------------------------
    class _AppDbManager:
        def __init__(self, main_window: "MainWindow"):
            self._mw = main_window

        def close_all(self):
            # Close the primary app connection
            try:
                if self._mw.conn:
                    try:
                        self._mw.conn.commit()
                    except Exception:
                        pass
                    self._mw.conn.close()
                    self._mw.conn = None
            except Exception:
                pass

            # Notify modules so they can drop cursors/prepare to rebind (optional)
            for _, mod in self._mw.modules:
                if hasattr(mod, "on_db_closed"):
                    try:
                        mod.on_db_closed()
                    except Exception:
                        pass

        def open(self):
            # Recreate the main connection
            from .database import get_connection as _gc  # local import avoids circularities
            self._mw.conn = _gc()

            # Give modules a chance to rebind their repos/cursors with the new connection
            for _, mod in self._mw.modules:
                if hasattr(mod, "on_db_reopened"):
                    try:
                        mod.on_db_reopened(self._mw.conn)
                    except Exception:
                        pass

    def __init__(self, conn, current_user: dict):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        # ensure normal window controls + sensible minimum
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setMinimumSize(820, 520)

        self.conn = conn
        self.user = current_user

        # ---- Central layout: left nav + stacked pages ----
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        # Left nav + content
        self.nav = QListWidget()
        # Cap the nav width so center content has room (reduced)
        self.nav.setFixedWidth(100)
        self.nav.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.stack = QStackedWidget()

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.addWidget(self.nav)
        row_lay.addWidget(self.stack, 1)
        layout.addWidget(row, 1)

        # Store module information for lazy loading
        self.module_info: list[dict] = []

        # Store loaded modules
        self.modules: list[tuple[str, BaseModule]] = []

        # nav wiring - connect to our lazy loading function
        self.nav.currentRowChanged.connect(self._on_nav_item_changed)

        # Dashboard
        self._add_module_deferred(
            "Dashboard",
            "inventory_management.modules.dashboard.controller",
            "DashboardController",
            self.conn,
            fallback_placeholder=True,
        )

        # Products
        self._add_module_deferred(
            "Products",
            "inventory_management.modules.product.controller",
            "ProductController",
            self.conn,
            fallback_placeholder=True,
        )

        # Inventory
        self._add_module_deferred(
            "Inventory",
            "inventory_management.modules.inventory.controller",
            "InventoryController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Purchases
        self._add_module_deferred(
            "Purchases",
            "inventory_management.modules.purchase.controller",
            "PurchaseController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Sales
        self._add_module_deferred(
            "Sales",
            "inventory_management.modules.sales.controller",
            "SalesController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Customers
        self._add_module_deferred(
            "Customers",
            "inventory_management.modules.customer.controller",
            "CustomerController",
            self.conn,
            fallback_placeholder=True,
        )

        # Vendors
        self._add_module_deferred(
            "Vendors",
            "inventory_management.modules.vendor.controller",
            "VendorController",
            self.conn,
            fallback_placeholder=True,
        )

        # Expenses
        self._add_module_deferred(
            "Expenses",
            "inventory_management.modules.expense.controller",
            "ExpenseController",
            self.conn,
            fallback_placeholder=True,
        )

        # Reporting (load actual module; if it fails we will print the exact error)
        self._add_module_deferred(
            "Reporting",
            "inventory_management.modules.reporting.controller",
            "ReportingController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # # Payments (load actual module; not admin-gated)
        # self._add_module_deferred(
        #     "Payments",
        #     "inventory_management.modules.payments.controller",
        #     "PaymentsController",
        #     self.conn,
        #     current_user=self.user,
        #     fallback_placeholder=True,
        # )

        # Admin-only: System Logs
        # if self.user and self.user.get("role") == "admin":
        #     self.add_placeholder("System Logs")

        # ---- Backup & Restore (replace previous placeholder) ----
        self._add_backup_restore_module_deferred()

        # Ensure first page is visible
        if self.nav.count():
            self.nav.setCurrentRow(0)
            # Load the first module (Dashboard) immediately
            self._load_module_at_index(0)
            self.stack.setCurrentIndex(0)

    # ---------- quick open to Inventory sub-tab ----------
    def open_inventory_sub(self, sub: str):
        """
        Ensure the Inventory module is visible and switch its internal tab.
        sub: 'adjustments' | 'transactions' | 'valuation'
        """
        idx = self._find_module_index("Inventory")
        if idx is None:
            QMessageBox.warning(self, "Missing", "Inventory module is not available.")
            return

        # Open Inventory page
        self.nav.setCurrentRow(idx)

        # Ask controller (if it exposes a selector)
        ctrl = self.modules[idx][1]
        if hasattr(ctrl, "select_tab"):
            try:
                ctrl.select_tab(sub)
                return
            except Exception:
                pass

        # Fallback: find a QTabWidget and select index
        try:
            w = ctrl.get_widget()
            from PySide6.QtWidgets import QTabWidget
            tab = w.findChild(QTabWidget)
            if tab:
                mapping = {"adjustments": 0, "transactions": 1, "valuation": 2}
                if sub in mapping and 0 <= mapping[sub] < tab.count():
                    tab.setCurrentIndex(mapping[sub])
        except Exception:
            pass

    # ---------- safe add helpers ----------
    def _add_module_safe(
        self,
        title: str,
        module_path: str,
        class_name: str,
        *args,
        fallback_placeholder: bool = True,
        **kwargs
    ):
        """Import and instantiate a controller safely. On any error, add a placeholder silently."""
        try:
            Controller = _lazy_get(module_path, class_name)
            controller = Controller(*args, **kwargs)
            self.add_module(title, controller)
        except Exception as e:
            # === DEBUG Reporting only ===
            if title in ["Sales", "Dashboard"]:
                import traceback as _tb, sys as _sys
                print(f"[{title}] failed to load:", e, file=_sys.stderr)
                _tb.print_exc()
            # ============================
            if fallback_placeholder:
                self.add_placeholder(title)

    def _add_backup_restore_module(self) -> None:
        """
        Create the Backup & Restore module using its factory and register
        File → Backup/Restore menu actions.
        """
        try:
            # Use the module factory (lazy import)
            backup_pkg = import_module("inventory_management.modules.backup_restore")
            create_module = getattr(backup_pkg, "create_module")
            module_title = getattr(backup_pkg, "MODULE_TITLE", "Backup & Restore")

            controller = create_module()

            # Attach the lightweight DB manager shim so restore can close/reopen the DB.
            setattr(controller, "_app_db_manager", MainWindow._AppDbManager(self))

            # Add to nav/stack
            self.add_module(module_title, controller)

            # Register File menu actions (controller wires actions to Backup/Restore dialogs)
            if hasattr(controller, "register_menu_actions"):
                controller.register_menu_actions(self.menuBar())

        except Exception as e:
            # If anything goes wrong, fall back to placeholder to keep app usable.
            print("[BackupRestore] failed to load:", e, file=sys.stderr)
            traceback.print_exc()
            self.add_placeholder("Backup & Restore")

    def add_module(self, title: str, module: BaseModule):
        page = module.get_widget()
        item = QListWidgetItem(title)
        self.nav.addItem(item)
        self.stack.addWidget(page)
        self.modules.append((title, module))

    def add_placeholder(self, title: str):
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"{title}\n\nComing soon..."))
        item = QListWidgetItem(title)
        self.nav.addItem(item)
        self.stack.addWidget(placeholder)

    def _add_module_deferred(
        self,
        title: str,
        module_path: str,
        class_name: str,
        *args,
        fallback_placeholder: bool = True,
        **kwargs
    ):
        """Add module info for deferred loading."""
        module_info = {
            'title': title,
            'module_path': module_path,
            'class_name': class_name,
            'args': args,
            'kwargs': kwargs,
            'fallback_placeholder': fallback_placeholder
        }

        # Add placeholder item to navigation
        item = QListWidgetItem(title)
        self.nav.addItem(item)

        # Add a placeholder widget to the stack - will be replaced when loaded
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"Loading {title}..."))
        self.stack.addWidget(placeholder)

        # Store module info for later loading
        self.module_info.append(module_info)

    def _add_backup_restore_module_deferred(self) -> None:
        """Add Backup & Restore module info for deferred loading."""
        module_info = {
            'title': 'Backup & Restore',
            'module_path': 'inventory_management.modules.backup_restore',
            'class_name': 'create_module',
            'args': (),
            'kwargs': {},
            'fallback_placeholder': True,
            'is_special': True  # Special handling for backup module
        }

        # Add placeholder item to navigation
        item = QListWidgetItem('Backup & Restore')
        self.nav.addItem(item)

        # Add a placeholder widget to the stack
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel("Loading Backup & Restore..."))
        self.stack.addWidget(placeholder)

        # Store module info for later loading
        self.module_info.append(module_info)

    def _on_nav_item_changed(self, index: int):
        """Load module when navigating to it."""
        if index < 0 or index >= len(self.module_info):
            return

        # Load the module if it hasn't been loaded yet
        self._load_module_at_index(index)

    def _load_module_at_index(self, index: int):
        """Load the module at the specified index if not already loaded."""
        if index < len(self.modules):
            # Module is already loaded, just show it
            self.stack.setCurrentIndex(index)
            return

        # Check if we've already loaded this module
        if index >= len(self.modules):
            # Load the module
            self._load_module(index)

        # Set the current index to show the module
        self.stack.setCurrentIndex(index)

    def _load_module(self, index: int):
        """Actually load the module at the specified index."""
        if index >= len(self.module_info):
            return

        # Set cursor to waiting
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            module_info = self.module_info[index]

            if module_info.get('is_special'):
                # Special handling for Backup & Restore
                self._load_backup_restore_module(index)
            else:
                # Normal module loading
                self._load_normal_module(index)
        except Exception as e:
            print(f"Error loading module at index {index}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

            # Add placeholder if loading failed
            if module_info.get('fallback_placeholder'):
                self._replace_placeholder_widget(index, f"{module_info['title']}\n\nLoading failed")
        finally:
            # Restore cursor
            QApplication.restoreOverrideCursor()

    def _load_normal_module(self, index: int):
        """Load a normal module (not special case)."""
        module_info = self.module_info[index]

        try:
            Controller = _lazy_get(module_info['module_path'], module_info['class_name'])
            controller = Controller(*module_info['args'], **module_info['kwargs'])

            # Replace the placeholder widget with the actual module widget
            widget = controller.get_widget()
            current_widget = self.stack.widget(index)

            # Remove the placeholder from the stack
            self.stack.removeWidget(current_widget)
            current_widget.deleteLater()

            # Add the actual module widget to the stack
            self.stack.insertWidget(index, widget)

            # Add to loaded modules list
            self.modules.append((module_info['title'], controller))

        except Exception as e:
            # === DEBUG Reporting only ===
            if module_info['title'] in ["Sales", "Dashboard"]:
                import traceback as _tb, sys as _sys
                print(f"[{module_info['title']}] failed to load:", e, file=_sys.stderr)
                _tb.print_exc()
            # ============================
            if module_info['fallback_placeholder']:
                self._replace_placeholder_widget(index, f"{module_info['title']}\n\nComing soon...")

    def _load_backup_restore_module(self, index: int):
        """Load the special Backup & Restore module."""
        module_info = self.module_info[index]

        try:
            # Use the module factory (lazy import)
            backup_pkg = import_module(module_info['module_path'])
            create_module = getattr(backup_pkg, 'create_module')
            module_title = getattr(backup_pkg, 'MODULE_TITLE', 'Backup & Restore')

            controller = create_module()

            # Attach the lightweight DB manager shim so restore can close/reopen the DB.
            setattr(controller, '_app_db_manager', MainWindow._AppDbManager(self))

            # Replace the placeholder widget with the actual module widget
            widget = controller.get_widget()
            current_widget = self.stack.widget(index)

            # Remove the placeholder from the stack
            self.stack.removeWidget(current_widget)
            current_widget.deleteLater()

            # Add the actual module widget to the stack
            self.stack.insertWidget(index, widget)

            # Add to loaded modules list
            self.modules.append((module_title, controller))

            # Register File menu actions (controller wires actions to Backup/Restore dialogs)
            if hasattr(controller, 'register_menu_actions'):
                controller.register_menu_actions(self.menuBar())

        except Exception as e:
            # If anything goes wrong, fall back to placeholder to keep app usable.
            print("[BackupRestore] failed to load:", e, file=sys.stderr)
            import traceback
            traceback.print_exc()
            self._replace_placeholder_widget(index, f"{module_info['title']}\n\nComing soon...")

    def _replace_placeholder_widget(self, index: int, message: str):
        """Replace a placeholder widget with a message."""
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        new_widget = wrap_center(QLabel(message))

        current_widget = self.stack.widget(index)

        # Remove the old placeholder from the stack
        self.stack.removeWidget(current_widget)
        current_widget.deleteLater()

        # Add the new widget to the stack
        self.stack.insertWidget(index, new_widget)

        # Add a placeholder module entry so the index doesn't get out of sync
        self.modules.append((self.module_info[index]['title'], None))

    def _find_module_index(self, title: str) -> int | None:
        for i, (t, _m) in enumerate(self.modules):
            if t == title:
                return i
        return None

    # ---------- global Sales shortcuts ----------
    def _find_module_info_index(self, title: str) -> int | None:
        for i, info in enumerate(self.module_info):
            if info.get("title") == title:
                return i
        return None

    def _get_sales_controller(self):
        """
        Ensure Sales module is loaded and return its controller, or None on failure.
        """
        info_idx = self._find_module_info_index("Sales")
        if info_idx is None:
            QMessageBox.warning(self, "Missing", "Sales module is not available.")
            return None

        # Ensure the Sales module is loaded (by index in module_info),
        # then resolve the actual controller by title from self.modules.
        self._load_module_at_index(info_idx)

        mod_idx = self._find_module_index("Sales")
        if mod_idx is None or mod_idx >= len(self.modules):
            QMessageBox.warning(self, "Missing", "Sales module could not be loaded.")
            return None

        return self.modules[mod_idx][1]

    def _invoke_sales_action(self, action_name: str, error_message: str) -> None:
        """
        Helper to invoke a method on the Sales controller with basic error handling.
        """
        ctrl = self._get_sales_controller()
        if ctrl and hasattr(ctrl, action_name):
            try:
                getattr(ctrl, action_name)()
            except Exception:
                QMessageBox.warning(self, "Error", error_message)

    def _open_new_sale(self):
        self._invoke_sales_action("new_sale", "Could not open New Sale form.")

    def _open_new_quotation(self):
        self._invoke_sales_action("new_quotation", "Could not open New Quotation form.")


def main():
    # Filter out warnings about signal disconnection
    import warnings
    warnings.filterwarnings("ignore",
                           message=r".*Failed to disconnect.*selectionChanged.*",
                           category=RuntimeWarning)

    # Make sure no test-time env disables decorations when running the app
    import os
    os.environ.pop("QT_QPA_DISABLE_WINDOWDECORATION", None)

    # Check if QApplication already exists (for dev_launcher.py compatibility)
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # DB connection (ensure schema, etc.)
    conn = get_connection()

    # ---- Login (lazy import to avoid circulars) ----
    # Commented out for development: bypass login during development
    # LoginController = _lazy_get("inventory_management.modules.login.controller", "LoginController")
    # login = LoginController(conn)

    # # Retry loop: specific messages for each failure case
    # while True:
    #     user = login.prompt()
    #     if user:
    #         break

    #     code = getattr(login, "last_error_code", None)
    #     uname = getattr(login, "last_username", "") or "this user"

    #     if code == "user_not_found":
    #         msg = f"No account exists for username “{uname}”.\n\nTry again?"
    #         title = "Unknown username"
    #         buttons = QMessageBox.Retry | QMessageBox.Close
    #         default = QMessageBox.Retry
    #     elif code == "wrong_password":
    #         msg = f"Incorrect password for “{uname}”.\n\nTry again?"
    #         title = "Incorrect password"
    #         buttons = QMessageBox.Retry | QMessageBox.Close
    #         default = QMessageBox.Retry
    #     elif code == "user_inactive":
    #         msg = f"Account “{uname}” is inactive. Contact an administrator."
    #         title = "Account inactive"
    #         buttons = QMessageBox.Close | QMessageBox.Retry
    #         default = QMessageBox.Retry
    #     elif code == "empty_fields":
    #         msg = "Please enter both username and password.\n\nTry again?"
    #         title = "Missing credentials"
    #         buttons = QMessageBox.Retry | QMessageBox.Close
    #         default = QMessageBox.Retry
    #     elif code == "cancelled":
    #         msg = "Login was cancelled.\n\nDo you want to quit the application?"
    #         title = "Login cancelled"
    #         buttons = QMessageBox.Yes | QMessageBox.No
    #         default = QMessageBox.Yes
    #     else:
    #         msg = "Login failed.\n\nDo you want to try again?"
    #         title = "Login failed"
    #         buttons = QMessageBox.Retry | QMessageBox.Close
    #         default = QMessageBox.Retry

    #     choice = QMessageBox.question(None, title, msg, buttons, default)
    #     if choice in (QMessageBox.Close, QMessageBox.No):
    #         return  # exit app
    
    # For development, create a mock user
    user = {
        "username": "dev_user", 
        "role": "admin", 
        "id": 1, 
        "user_id": 1,
        "user_name": "dev_user"  # Add other potential user fields as needed
    }  # Mock user for development

    # Optional style
    qss = load_qss()
    if qss:
        app.setStyleSheet(qss)

    # Window
    win = MainWindow(conn, current_user=user)

    # Show UI (smaller default)
    win.resize(900, 560)
    win.show()
    
    # Only call exec_ if we're running standalone (not under dev_launcher.py)
    # When running under dev_launcher.py, just return and let it handle the event loop
    if os.environ.get('__DEV_LAUNCHER__') != '1':
        sys.exit(app.exec())
    # If we're under dev_launcher.py, just return control


if __name__ == "__main__":
    main()
