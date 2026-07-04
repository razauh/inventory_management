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
    QMenu,
    QLabel,
    QFrame,
)
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from pathlib import Path
import subprocess
import sys
import traceback
import os
import time
from importlib import import_module
from types import ModuleType
# Add the project root to the Python path for imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from constants import APP_MUTEX_NAME, APP_NAME, STYLE_FILE
from database import get_connection, get_unresolved_purchase_return_count
from modules.base_module import BaseModule
from version import APP_VERSION


def load_qss() -> str:
    qss = ""
    f = Path(__file__).resolve().parent / STYLE_FILE
    if f.exists():
        qss = f.read_text(encoding="utf-8")
    return qss


def _bootstrap_inventory_management_namespace() -> None:
    project_root = Path(__file__).resolve().parent
    root_str = str(project_root)
    parent_dir = str(project_root.parent)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    package_name = "inventory_management"
    package = sys.modules.get(package_name)
    if package is None:
        package = ModuleType(package_name)
        package.__file__ = str(project_root / "__init__.py")
        package.__package__ = package_name
        package.__path__ = [root_str]
        sys.modules[package_name] = package
    else:
        package_paths = list(getattr(package, "__path__", []))
        if root_str not in package_paths:
            package_paths.append(root_str)
            package.__path__ = package_paths


def _log_module_load_failure(title: str, module_path: str, class_name: str, exc: Exception) -> None:
    print(
        f"[{title}] failed to load {module_path}.{class_name}: {exc}",
        file=sys.stderr,
    )
    traceback.print_exc()


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

    _bootstrap_inventory_management_namespace()

    try:
        mod = import_module(name)
    except Exception as e:
        raise ImportError(f"Failed to import module '{name}': {e}") from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise ImportError(f"'{attr}' not found in module '{name}'.") from e


def _updater_bootstrap_arg(argv: list[str], flag: str) -> str | None:
    try:
        idx = argv.index(flag)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def _wait_for_process_exit(parent_pid: int) -> None:
    if parent_pid <= 0:
        return
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, parent_pid)
        if handle:
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel32.CloseHandle(handle)
        return

    while True:
        try:
            os.kill(parent_pid, 0)
        except OSError:
            return
        time.sleep(0.25)


def _run_updater_bootstrap(argv: list[str]) -> bool:
    if "--updater-bootstrap" not in argv:
        return False

    installer_text = _updater_bootstrap_arg(argv, "--updater-installer")
    install_dir_text = _updater_bootstrap_arg(argv, "--updater-install-dir")
    parent_pid_text = _updater_bootstrap_arg(argv, "--updater-parent-pid")
    if not installer_text or not install_dir_text or not parent_pid_text:
        print("Updater bootstrap mode missing required arguments.", file=sys.stderr)
        return True

    try:
        parent_pid = int(parent_pid_text)
    except ValueError:
        print("Updater bootstrap mode had an invalid parent PID.", file=sys.stderr)
        return True

    _wait_for_process_exit(parent_pid)

    installer = Path(installer_text)
    install_dir = Path(install_dir_text)
    try:
        subprocess.Popen([str(installer), f"/DIR={install_dir}"], close_fds=True)
    except OSError as exc:
        print(f"Could not start installer: {exc}", file=sys.stderr)
    return True


class MainWindow(QMainWindow):
    class _SidebarNavItem(QWidget):
        def __init__(self, title: str, *, section: str, show_separator: bool, parent=None):
            super().__init__(parent)
            self._selected = False
            self._hovered = False
            self.setAttribute(Qt.WA_StyledBackground, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            self.separator = QFrame()
            self.separator.setObjectName("sidebarSectionSeparator")
            self.separator.setFixedHeight(1)
            self.separator.setVisible(show_separator)
            root.addWidget(self.separator)

            self.surface = QFrame()
            self.surface.setObjectName("sidebarItemSurface")
            self.surface.setProperty("section", section)
            surface_layout = QHBoxLayout(self.surface)
            surface_layout.setContentsMargins(0, 0, 0, 0)
            surface_layout.setSpacing(0)

            self.accent = QFrame()
            self.accent.setObjectName("sidebarItemAccent")
            self.accent.setFixedWidth(3)
            surface_layout.addWidget(self.accent)

            label_wrap = QWidget()
            label_wrap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label_layout = QHBoxLayout(label_wrap)
            label_layout.setContentsMargins(10, 0, 10, 0)
            label_layout.setSpacing(0)
            self.label = QLabel(title)
            self.label.setObjectName("sidebarItemLabel")
            self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.label.setWordWrap(False)
            label_layout.addWidget(self.label, 1)
            surface_layout.addWidget(label_wrap, 1)

            root.addWidget(self.surface)
            self._apply_state()

        def sizeHint(self) -> QSize:
            extra = 1 if self.separator.isVisible() else 0
            return QSize(120, 30 + extra)

        def set_selected(self, selected: bool) -> None:
            self._selected = selected
            self._apply_state()

        def set_hovered(self, hovered: bool) -> None:
            self._hovered = hovered
            self._apply_state()

        def _apply_state(self) -> None:
            self.surface.setProperty("selected", self._selected)
            self.surface.setProperty("hovered", self._hovered and not self._selected)
            self.label.setProperty("selected", self._selected)
            self.accent.setProperty("selected", self._selected)
            for widget in (self.surface, self.label, self.accent):
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()

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
            from database import get_connection as _gc  # local import avoids circularities
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
        _bootstrap_inventory_management_namespace()
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
        self.nav.setObjectName("sidebarNav")
        self.nav.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.nav.setMouseTracking(True)
        self.nav.setSpacing(0)
        self.nav.viewport().installEventFilter(self)
        self.nav.itemEntered.connect(self._on_nav_item_hovered)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebarRail")
        self.sidebar.setFixedWidth(132)
        self.sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self.nav, 1)
        self.sidebar_version = QLabel(f"v{APP_VERSION}")
        self.sidebar_version.setObjectName("sidebarVersionLabel")
        self.sidebar_version.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.sidebar_version, 0)

        self.stack = QStackedWidget()

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(0)
        row_lay.addWidget(self.sidebar)
        row_lay.addWidget(self.stack, 1)
        layout.addWidget(row, 1)

        # Store module information for lazy loading
        self.module_info: list[dict] = []

        # Store modules aligned with module_info/nav/stack indexes.
        self.modules: list[tuple[str, BaseModule | None]] = []

        # nav wiring - connect to our lazy loading function
        self.nav.currentRowChanged.connect(self._on_nav_item_changed)
        self.nav.currentRowChanged.connect(self._refresh_nav_item_states)

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

        # Payments (read-only shortcut to Reporting > Payments)
        self._add_module_deferred(
            "Payments",
            "inventory_management.modules.payments.controller",
            "PaymentsController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        self._add_module_deferred(
            "Updates",
            "inventory_management.modules.updater",
            "create_module",
            self,
            fallback_placeholder=True,
        )

        # Admin-only: System Logs
        # if self.user and self.user.get("role") == "admin":
        #     self.add_placeholder("System Logs")

        self._add_module_deferred(
            "Accounting",
            "inventory_management.modules.accounting_review.controller",
            "AccountingReviewController",
            self.conn,
            current_user=self.user,
            fallback_placeholder=True,
        )

        # ---- Backup & Restore (replace previous placeholder) ----
        self._add_backup_restore_module_deferred()

        self._add_module_deferred(
            "Company Info",
            "inventory_management.modules.company_info.controller",
            "CompanyInfoController",
            self.conn,
            fallback_placeholder=True,
        )

        self._register_backup_restore_file_actions()
        self._register_global_shortcuts()
        self._register_updater_actions()

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
        sub: 'valuation' | 'low_inventory' | 'transactions' | 'adjustments'
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
                mapping = {"valuation": 0, "low_inventory": 1, "transactions": 2, "adjustments": 3}
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
            _log_module_load_failure(title, module_path, class_name, e)
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
            if not getattr(self, "_backup_restore_file_actions_registered", False) and hasattr(controller, "register_menu_actions"):
                controller.register_menu_actions(self.menuBar())

        except Exception as e:
            # If anything goes wrong, fall back to placeholder to keep app usable.
            print("[BackupRestore] failed to load:", e, file=sys.stderr)
            traceback.print_exc()
            self.add_placeholder("Backup & Restore")

    def add_module(self, title: str, module: BaseModule):
        page = module.get_widget()
        item = self._create_nav_item(title)
        self.nav.addItem(item)
        self._set_nav_item_widget(item, title)
        self.stack.addWidget(page)
        self.modules.append((title, module))

    def add_placeholder(self, title: str):
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"{title}\n\nComing soon..."))
        item = self._create_nav_item(title)
        self.nav.addItem(item)
        self._set_nav_item_widget(item, title)
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
        item = self._create_nav_item(title)
        self.nav.addItem(item)
        self._set_nav_item_widget(item, title)

        # Add a placeholder widget to the stack - will be replaced when loaded
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"Loading {title}..."))
        self.stack.addWidget(placeholder)

        # Store module info for later loading
        self.module_info.append(module_info)
        self.modules.append((title, None))

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
        item = self._create_nav_item('Backup & Restore')
        self.nav.addItem(item)
        self._set_nav_item_widget(item, 'Backup & Restore')

        # Add a placeholder widget to the stack
        from PySide6.QtWidgets import QLabel
        from utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel("Loading Backup & Restore..."))
        self.stack.addWidget(placeholder)

        # Store module info for later loading
        self.module_info.append(module_info)
        self.modules.append(('Backup & Restore', None))

    def _register_backup_restore_file_actions(self) -> None:
        if getattr(self, "_backup_restore_file_actions_registered", False):
            return

        file_menu = None
        for action in self.menuBar().actions():
            try:
                menu = action.menu()
                if menu and menu.title().replace("&", "").lower() == "file":
                    file_menu = menu
                    break
            except RuntimeError:
                continue

        if file_menu is None:
            file_menu = QMenu("&File", self.menuBar())
            self.menuBar().addMenu(file_menu)

        self._backup_restore_file_menu = file_menu
        self._backup_restore_backup_action = QAction("Backup Database…", self)
        self._backup_restore_backup_action.triggered.connect(self._open_backup_restore_backup_from_menu)
        self._backup_restore_restore_action = QAction("Restore Database…", self)
        self._backup_restore_restore_action.triggered.connect(self._open_backup_restore_restore_from_menu)

        if file_menu.actions() and not file_menu.actions()[-1].isSeparator():
            file_menu.addSeparator()
        file_menu.addAction(self._backup_restore_backup_action)
        file_menu.addAction(self._backup_restore_restore_action)
        self._backup_restore_file_actions_registered = True

    def _get_backup_restore_controller(self):
        idx = self._find_module_info_index("Backup & Restore")
        if idx is None:
            QMessageBox.warning(self, "Missing", "Backup & Restore module is not available.")
            return None

        if self.nav.currentRow() != idx:
            self.nav.setCurrentRow(idx)
        else:
            self._load_module_at_index(idx)

        if idx >= len(self.modules):
            QMessageBox.warning(self, "Missing", "Backup & Restore module could not be loaded.")
            return None

        controller = self.modules[idx][1]
        if controller is None:
            QMessageBox.warning(self, "Missing", "Backup & Restore module could not be loaded.")
            return None
        return controller

    def _open_backup_restore_backup_from_menu(self) -> None:
        controller = self._get_backup_restore_controller()
        if controller and hasattr(controller, "open_backup_dialog"):
            controller.open_backup_dialog()

    def _open_backup_restore_restore_from_menu(self) -> None:
        controller = self._get_backup_restore_controller()
        if controller and hasattr(controller, "open_restore_dialog"):
            controller.open_restore_dialog()

    def _set_backup_restore_file_actions_enabled(self, enabled: bool) -> None:
        for attr in ("_backup_restore_backup_action", "_backup_restore_restore_action"):
            action = getattr(self, attr, None)
            if action is not None:
                action.setEnabled(enabled)

    def _register_updater_actions(self) -> None:
        help_menu = None
        for action in self.menuBar().actions():
            try:
                menu = action.menu()
                if menu and menu.title().replace("&", "").lower() == "help":
                    help_menu = menu
                    break
            except RuntimeError:
                continue

        if help_menu is None:
            help_menu = QMenu("&Help", self.menuBar())
            self.menuBar().addMenu(help_menu)

        self._check_updates_action = QAction("Check for Updates…", self)
        self._check_updates_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(self._check_updates_action)

    def _get_updater_controller(self):
        controller = getattr(self, "_updater_controller", None)
        if controller is None:
            try:
                from inventory_management.modules.updater import UpdaterController
            except ModuleNotFoundError:
                return None
            controller = UpdaterController(self)
            self._updater_controller = controller
        return controller

    def _check_for_updates(self) -> None:
        self.open_module("Updates")
        self._get_updater_controller().check_now(manual=True)

    def open_module(self, title: str) -> bool:
        idx = self._find_module_info_index(title)
        if idx is None:
            return False
        if self.nav.currentRow() != idx:
            self.nav.setCurrentRow(idx)
        else:
            self._load_module_at_index(idx)
        return True

    def _create_nav_item(self, title: str) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, title)
        item.setToolTip(title)
        item.setSizeHint(QSize(120, 30))
        return item

    def _set_nav_item_widget(self, item: QListWidgetItem, title: str) -> None:
        section = self._sidebar_section_name(title)
        show_separator = title == "Updates"
        widget = MainWindow._SidebarNavItem(title, section=section, show_separator=show_separator, parent=self.nav)
        item.setSizeHint(widget.sizeHint())
        self.nav.setItemWidget(item, widget)
        self._refresh_nav_item_states()

    def _sidebar_section_name(self, title: str) -> str:
        if title in {"Updates", "Backup & Restore"}:
            return "system"
        return "management"

    def _refresh_nav_item_states(self, *_args) -> None:
        current_row = self.nav.currentRow()
        hovered_row = getattr(self, "_hovered_nav_row", -1)
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            widget = self.nav.itemWidget(item)
            if isinstance(widget, MainWindow._SidebarNavItem):
                widget.set_selected(row == current_row)
                widget.set_hovered(row == hovered_row)

    def _on_nav_item_hovered(self, item: QListWidgetItem) -> None:
        self._hovered_nav_row = self.nav.row(item)
        self._refresh_nav_item_states()

    def show_update_toast(
        self,
        *,
        title: str,
        message: str,
        primary_text: str,
        primary_callback,
        secondary_text: str,
        secondary_callback,
    ) -> None:
        from inventory_management.modules.updater.views import UpdateToast

        toast = getattr(self, "_update_toast", None)
        if toast is None:
            toast = UpdateToast(self)
            self._update_toast = toast
        toast.configure(
            title=title,
            message=message,
            primary_text=primary_text,
            primary_callback=primary_callback,
            secondary_text=secondary_text,
            secondary_callback=secondary_callback,
        )
        self._position_update_toast()
        toast.show()
        toast.raise_()

    def _position_update_toast(self) -> None:
        toast = getattr(self, "_update_toast", None)
        if toast is None:
            return
        margin = 18
        x = self.width() - toast.width() - margin
        y = self.height() - toast.height() - margin
        toast.move(max(margin, x), max(margin, y))

    def _on_nav_item_changed(self, index: int):
        """Load module when navigating to it."""
        if index < 0 or index >= len(self.module_info):
            return

        # Load the module if it hasn't been loaded yet
        self._load_module_at_index(index)

    def _load_module_at_index(self, index: int):
        """Load the module at the specified index if not already loaded."""
        if index < len(self.modules) and self.modules[index][1] is not None:
            # Module is already loaded, just show it
            self.stack.setCurrentIndex(index)
            ctrl = self.modules[index][1]
            if ctrl is not None and hasattr(ctrl, "refresh") and callable(ctrl.refresh):
                try:
                    ctrl.refresh()
                except Exception as e:
                    import sys
                    print(f"Error refreshing module: {e}", file=sys.stderr)
            return

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

            # Mark this nav index as loaded.
            self.modules[index] = (module_info['title'], controller)

        except Exception as e:
            _log_module_load_failure(
                module_info['title'],
                module_info['module_path'],
                module_info['class_name'],
                e,
            )
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
            signal = getattr(controller, "operation_controls_enabled_changed", None)
            if signal is not None:
                signal.connect(self._set_backup_restore_file_actions_enabled)

            # Replace the placeholder widget with the actual module widget
            widget = controller.get_widget()
            current_widget = self.stack.widget(index)

            # Remove the placeholder from the stack
            self.stack.removeWidget(current_widget)
            current_widget.deleteLater()

            # Add the actual module widget to the stack
            self.stack.insertWidget(index, widget)

            # Mark this nav index as loaded.
            self.modules[index] = (module_title, controller)

            # Register File menu actions (controller wires actions to Backup/Restore dialogs)
            if not getattr(self, "_backup_restore_file_actions_registered", False) and hasattr(controller, 'register_menu_actions'):
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

        if index < len(self.modules):
            self.modules[index] = (self.module_info[index]['title'], None)

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

    def _get_purchase_controller(self):
        info_idx = self._find_module_info_index("Purchases")
        if info_idx is None:
            QMessageBox.warning(self, "Missing", "Purchases module is not available.")
            return None

        self._load_module_at_index(info_idx)

        mod_idx = self._find_module_index("Purchases")
        if mod_idx is None or mod_idx >= len(self.modules):
            QMessageBox.warning(self, "Missing", "Purchases module could not be loaded.")
            return None

        return self.modules[mod_idx][1]

    def _invoke_purchase_action(self, action_name: str, error_message: str) -> None:
        ctrl = self._get_purchase_controller()
        if ctrl and hasattr(ctrl, action_name):
            try:
                getattr(ctrl, action_name)()
            except Exception:
                QMessageBox.warning(self, "Error", error_message)

    def _open_new_purchase(self):
        self._invoke_purchase_action("new_purchase", "Could not open New Purchase form.")

    def _register_global_shortcuts(self) -> None:
        self._global_shortcuts = [
            QShortcut(QKeySequence("Ctrl+Shift+P"), self),
            QShortcut(QKeySequence("Ctrl+Shift+S"), self),
            QShortcut(QKeySequence("Ctrl+Shift+Q"), self),
        ]
        for shortcut in self._global_shortcuts:
            shortcut.setContext(Qt.ApplicationShortcut)

        self._global_shortcuts[0].activated.connect(self._open_new_purchase)
        self._global_shortcuts[1].activated.connect(self._open_new_sale)
        self._global_shortcuts[2].activated.connect(self._open_new_quotation)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_update_toast()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._position_update_toast()

    def eventFilter(self, watched, event):
        if watched is self.nav.viewport() and event.type() == QEvent.Type.Leave:
            self._hovered_nav_row = -1
            self._refresh_nav_item_states()
        return super().eventFilter(watched, event)


def main():
    if _run_updater_bootstrap(sys.argv):
        return

    _bootstrap_inventory_management_namespace()

    # Hold named mutex on Windows during app execution to prevent installer collisions
    if sys.platform == "win32":
        import ctypes
        global _app_mutex
        _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)

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
    app.setOrganizationName(APP_NAME)

    # DB connection (ensure schema, etc.)
    conn = get_connection()
    unresolved_returns = get_unresolved_purchase_return_count(conn)
    if unresolved_returns:
        QMessageBox.warning(
            None,
            "Purchase return reconciliation required",
            f"{unresolved_returns} legacy purchase return(s) have no recoverable valuation. "
            "They remain excluded from financial totals until manually reconciled.",
        )

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
    updater = win._get_updater_controller()
    if updater is None:
        print("[main] updater module not available, skipping startup checks", file=sys.stderr)
    else:
        if not updater.verify_pending_installation():
            QMessageBox.warning(
                win,
                "Update installation failed",
                "The previous update did not finish installing.",
            )
        updater.check_on_startup()
    
    # Only call exec_ if we're running standalone (not under dev_launcher.py)
    # When running under dev_launcher.py, just return and let it handle the event loop
    if os.environ.get('__DEV_LAUNCHER__') != '1':
        sys.exit(app.exec())
    # If we're under dev_launcher.py, just return control


if __name__ == "__main__":
    main()
