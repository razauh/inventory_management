from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QMessageBox,
    QHBoxLayout, QMenu, QSizePolicy
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
from pathlib import Path
import sys
import traceback
import os
from importlib import import_module

from .constants import APP_NAME, STYLE_FILE
from .database import get_connection
from .modules.base_module import BaseModule


def load_qss() -> str:
    qss = ""
    f = Path(__file__).resolve().parent / STYLE_FILE
    if f.exists():
        qss = f.read_text(encoding="utf-8")
    return qss


def _lazy_get(name: str, attr: str):
    """Import a module by name and fetch an attribute from it, with a clear error if missing."""
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
        # Cap the nav width so center content has room
        self.nav.setFixedWidth(200)
        self.nav.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.stack = QStackedWidget()

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.addWidget(self.nav)
        row_lay.addWidget(self.stack, 1)
        layout.addWidget(row, 1)

        self.modules: list[tuple[str, BaseModule]] = []

        # nav wiring
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        # Dashboard
        self._add_module_safe(
            "Dashboard",
            "inventory_management.modules.dashboard.controller",
            "DashboardController",
            self.conn,
            fallback_placeholder=True,
        )

        # Products
        self._add_module_safe(
            "Products",
            "inventory_management.modules.product.controller",
            "ProductController",
            self.conn,
            fallback_placeholder=True,
        )

        # Inventory
        self._add_module_safe(
            "Inventory",
            "inventory_management.modules.inventory.controller",
            "InventoryController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Purchases
        self._add_module_safe(
            "Purchases",
            "inventory_management.modules.purchase.controller",
            "PurchaseController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Sales
        self._add_module_safe(
            "Sales",
            "inventory_management.modules.sales.controller",
            "SalesController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # Customers
        self._add_module_safe(
            "Customers",
            "inventory_management.modules.customer.controller",
            "CustomerController",
            self.conn,
            fallback_placeholder=True,
        )

        # Vendors
        self._add_module_safe(
            "Vendors",
            "inventory_management.modules.vendor.controller",
            "VendorController",
            self.conn,
            fallback_placeholder=True,
        )

        # Expenses
        self._add_module_safe(
            "Expenses",
            "inventory_management.modules.expense.controller",
            "ExpenseController",
            self.conn,
            fallback_placeholder=True,
        )

        # Reporting (load actual module; if it fails we will print the exact error)
        self._add_module_safe(
            "Reporting",
            "inventory_management.modules.reporting.controller",
            "ReportingController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # # Payments (load actual module; not admin-gated)
        # self._add_module_safe(
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
        self._add_backup_restore_module()

        # Ensure first page is visible
        if self.nav.count():
            self.nav.setCurrentRow(0)
            self.stack.setCurrentIndex(0)

        # -------- Inventory menu anchored to left nav item (click to open) --------
        self.inventory_menu = QMenu(self)
        act_adj = QAction("Adjustments & Recent", self.inventory_menu)
        act_txn = QAction("Transactions", self.inventory_menu)
        act_val = QAction("Stock Valuation", self.inventory_menu)
        self.inventory_menu.addAction(act_adj)
        self.inventory_menu.addAction(act_txn)
        self.inventory_menu.addSeparator()
        self.inventory_menu.addAction(act_val)

        # Wire actions to open sub-tabs
        act_adj.triggered.connect(lambda: self.open_inventory_sub("adjustments"))
        act_txn.triggered.connect(lambda: self.open_inventory_sub("transactions"))
        act_val.triggered.connect(lambda: self.open_inventory_sub("valuation"))

        # Open the Inventory menu when user clicks the Inventory row
        self.nav.setMouseTracking(False)  # no hover popups

        def _show_inventory_menu_at_row():
            idx = self._find_module_index("Inventory")
            if idx is None:
                return
            item = self.nav.item(idx)
            if not item:
                return
            rect = self.nav.visualItemRect(item)
            global_pt = self.nav.viewport().mapToGlobal(rect.topRight())
            global_pt.setX(global_pt.x() + 6)  # slight offset from list edge
            self.inventory_menu.popup(global_pt)

        def _nav_mouse_press(event):
            # Qt6: event.position() returns QPointF
            pos = event.position().toPoint()
            clicked_item = self.nav.itemAt(pos)
            # open menu only if user clicked exactly "Inventory"
            if clicked_item and clicked_item.text() == "Inventory":
                _show_inventory_menu_at_row()
                event.accept()
            else:
                QListWidget.mousePressEvent(self.nav, event)  # default behavior

        # install the light handler
        self.nav.viewport().mousePressEvent = _nav_mouse_press

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
        from .utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"{title}\n\nComing soon..."))
        item = QListWidgetItem(title)
        self.nav.addItem(item)
        self.stack.addWidget(placeholder)

    def _find_module_index(self, title: str) -> int | None:
        for i, (t, _m) in enumerate(self.modules):
            if t == title:
                return i
        return None


def main():
    # Make sure no test-time env disables decorations when running the app
    os.environ.pop("QT_QPA_DISABLE_WINDOWDECORATION", None)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # DB connection (ensure schema, etc.)
    conn = get_connection()

    # ---- Login (lazy import to avoid circulars) ----
    LoginController = _lazy_get("inventory_management.modules.login.controller", "LoginController")
    login = LoginController(conn)

    # Retry loop: specific messages for each failure case
    while True:
        user = login.prompt()
        if user:
            break

        code = getattr(login, "last_error_code", None)
        uname = getattr(login, "last_username", "") or "this user"

        if code == "user_not_found":
            msg = f"No account exists for username “{uname}”.\n\nTry again?"
            title = "Unknown username"
            buttons = QMessageBox.Retry | QMessageBox.Close
            default = QMessageBox.Retry
        elif code == "wrong_password":
            msg = f"Incorrect password for “{uname}”.\n\nTry again?"
            title = "Incorrect password"
            buttons = QMessageBox.Retry | QMessageBox.Close
            default = QMessageBox.Retry
        elif code == "user_inactive":
            msg = f"Account “{uname}” is inactive. Contact an administrator."
            title = "Account inactive"
            buttons = QMessageBox.Close | QMessageBox.Retry
            default = QMessageBox.Retry
        elif code == "empty_fields":
            msg = "Please enter both username and password.\n\nTry again?"
            title = "Missing credentials"
            buttons = QMessageBox.Retry | QMessageBox.Close
            default = QMessageBox.Retry
        elif code == "cancelled":
            msg = "Login was cancelled.\n\nDo you want to quit the application?"
            title = "Login cancelled"
            buttons = QMessageBox.Yes | QMessageBox.No
            default = QMessageBox.Yes
        else:
            msg = "Login failed.\n\nDo you want to try again?"
            title = "Login failed"
            buttons = QMessageBox.Retry | QMessageBox.Close
            default = QMessageBox.Retry

        choice = QMessageBox.question(None, title, msg, buttons, default)
        if choice in (QMessageBox.Close, QMessageBox.No):
            return  # exit app

    # Optional style
    qss = load_qss()
    if qss:
        app.setStyleSheet(qss)

    # Window
    win = MainWindow(conn, current_user=user)

    # Show UI (smaller default)
    win.resize(900, 560)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
