from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QMessageBox
)
from pathlib import Path
import sys
import traceback
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
    def __init__(self, conn, current_user: dict):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.conn = conn
        self.user = current_user

        # ---- Central layout: left nav + stacked pages ----
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.nav = QListWidget()
        self.nav.setMaximumWidth(220)
        self.stack = QStackedWidget()

        from PySide6.QtWidgets import QHBoxLayout
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.addWidget(self.nav)
        row_lay.addWidget(self.stack, 1)
        layout.addWidget(row, 1)

        self.modules: list[tuple[str, BaseModule]] = []

        # nav wiring
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        # Try real Dashboard first; fallback to placeholder
        self._add_module_safe(
            "Dashboard",
            "inventory_management.modules.dashboard.controller",
            "DashboardController",
            self.conn,
            current_user=self.user,
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
        self.add_placeholder("Reporting")
        if self.user and self.user.get("role") == "admin":
            self.add_placeholder("Users")
            self.add_placeholder("System Logs")
        self.add_placeholder("Printing")

        # Ensure first page is visible
        if self.nav.count():
            self.nav.setCurrentRow(0)
            self.stack.setCurrentIndex(0)

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
        """Import and instantiate a controller safely. On any error, log and add a placeholder."""
        try:
            Controller = _lazy_get(module_path, class_name)
            controller = Controller(*args, **kwargs)
            self.add_module(title, controller)
        except Exception as e:
            print(f"[{title}] failed to load: {e}", file=sys.stderr)
            traceback.print_exc()
            if fallback_placeholder:
                self.add_placeholder(title)

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


def main():
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
        # Normalize button choices to exit/continue
        if choice in (QMessageBox.Close, QMessageBox.No):
            return  # exit app
        # otherwise loop to re-prompt

    # Optional style
    qss = load_qss()
    if qss:
        app.setStyleSheet(qss)

    # Window
    win = MainWindow(conn, current_user=user)

    # Show UI
    win.resize(1200, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
