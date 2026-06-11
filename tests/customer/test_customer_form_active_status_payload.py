import sqlite3
import importlib.util
import sys
from pathlib import Path

from PySide6.QtWidgets import QCheckBox


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_symbol(path: Path, name: str, module_name: str | None = None):
    spec = importlib.util.spec_from_file_location(module_name or path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, name)


CustomersRepo = load_symbol(
    PROJECT_ROOT / "database" / "repositories" / "customers_repo.py",
    "CustomersRepo",
)
SQL = load_symbol(PROJECT_ROOT / "database" / "schema.py", "SQL")
CustomerForm = load_symbol(
    PROJECT_ROOT / "modules" / "customer" / "form.py",
    "CustomerForm",
    "inventory_management.modules.customer.form",
)


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


def test_customer_form_create_payload_excludes_active_status(qtbot):
    conn = make_db()
    repo = CustomersRepo(conn)
    form = CustomerForm()
    qtbot.addWidget(form)

    form.name.setText("  Customer   One  ")
    form.contact.setPlainText("  555-0100  ")
    form.addr.setPlainText("  Main   Street  ")

    payload = form.get_payload()

    assert payload == {
        "name": "Customer One",
        "contact_info": "555-0100",
        "address": "Main Street",
    }
    assert "is_active" not in payload
    customer_id = repo.create(**payload)
    row = conn.execute(
        "SELECT is_active FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    assert row["is_active"] == 1
    conn.close()


def test_customer_form_edit_payload_does_not_change_active_status(qtbot):
    conn = make_db()
    repo = CustomersRepo(conn)
    customer_id = repo.create("Customer Two", "555-0200", "Old Address")
    conn.execute(
        "UPDATE customers SET is_active = 0 WHERE customer_id = ?",
        (customer_id,),
    )
    conn.commit()
    initial = dict(
        conn.execute(
            "SELECT customer_id, name, contact_info, address, is_active "
            "FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    )
    form = CustomerForm(initial=initial)
    qtbot.addWidget(form)

    form.name.setText("Customer Two Updated")
    form.contact.setPlainText("555-0222")
    form.addr.setPlainText("")

    payload = form.get_payload()

    assert "is_active" not in payload
    repo.update(customer_id, **payload)
    row = conn.execute(
        "SELECT name, contact_info, address, is_active "
        "FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    assert dict(row) == {
        "name": "Customer Two Updated",
        "contact_info": "555-0222",
        "address": None,
        "is_active": 0,
    }
    conn.close()


def test_customer_form_has_no_active_status_control(qtbot):
    form = CustomerForm()
    qtbot.addWidget(form)

    checkboxes = form.findChildren(QCheckBox)

    assert checkboxes == []
