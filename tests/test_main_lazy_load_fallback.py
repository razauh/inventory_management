import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main


def test_lazy_load_failure_logs_target_and_keeps_placeholder(qtbot, monkeypatch):
    def fake_lazy_get(module_path, class_name):
        raise ImportError(f"boom for {module_path}.{class_name}")

    monkeypatch.setattr(main, "_lazy_get", fake_lazy_get)

    stderr = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = stderr
    try:
        window = main.MainWindow(conn=object(), current_user={"role": "admin"})
        qtbot.addWidget(window)

        products_index = window._find_module_info_index("Products")
        assert products_index == 1

        window._load_module_at_index(products_index)
    finally:
        sys.stderr = old_stderr

    current_widget = window.stack.widget(products_index)
    label = current_widget.findChild(main.QLabel)
    assert label is not None
    assert label.text() == "Products\n\nLoading failed"

    output = stderr.getvalue()
    assert "[Products] failed to load inventory_management.modules.product.controller.ProductController" in output
    assert "boom for inventory_management.modules.product.controller.ProductController" in output
