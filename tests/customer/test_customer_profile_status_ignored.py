import sqlite3

from PySide6.QtWidgets import QCheckBox

from inventory_management.database.repositories.customers_repo import CustomersRepo, Customer
from inventory_management.database.schema import SQL
from inventory_management.modules.customer.form import CustomerForm
from inventory_management.modules.customer.model import CustomersTableModel
from inventory_management.modules.customer.details import CustomerDetails


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


def test_customer_form_payload_contains_only_profile_fields(qtbot):
    form = CustomerForm()
    qtbot.addWidget(form)

    form.name.setText("  Customer   One  ")
    form.contact.setPlainText("  555-0100  ")
    form.addr.setPlainText("  Main   Street  ")

    assert form.get_payload() == {
        "name": "Customer One",
        "contact_info": "555-0100",
        "address": "Main Street",
    }
    assert form.findChildren(QCheckBox) == []


def test_customer_repo_reads_ignore_legacy_status_column():
    conn = make_db()
    repo = CustomersRepo(conn)
    first_id = repo.create("Customer One", "555-0100", "Main Street")
    second_id = repo.create("Customer Two", "555-0200", "Second Street")
    conn.execute("UPDATE customers SET is_active = 0 WHERE customer_id = ?", (first_id,))
    conn.commit()

    listed_ids = [row.customer_id for row in repo.list_customers()]
    found_ids = [row.customer_id for row in repo.search("Customer")]

    assert listed_ids == [second_id, first_id]
    assert found_ids == [second_id, first_id]
    assert repo.get(first_id).__dict__ == {
        "customer_id": first_id,
        "name": "Customer One",
        "contact_info": "555-0100",
        "address": "Main Street",
    }
    conn.close()


def test_customer_table_and_details_have_no_status_ui(qtbot):
    details = CustomerDetails()
    qtbot.addWidget(details)

    assert CustomersTableModel.HEADERS == ["ID", "Name", "Contact", "Address"]
    assert not hasattr(CustomersTableModel, "IS_ACTIVE_ROLE")
    assert not hasattr(details, "lab_status")
