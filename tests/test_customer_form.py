# tests/test_customer_form.py

import pytest

# Skip the entire module if PySide6 is not available
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

# Import the real CustomerForm from your repository
from inventory_management.modules.customer.form import CustomerForm


def ensure_app():
    """Ensure a QApplication instance exists; return it."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_customer_form_get_payload_valid():
    """
    Valid input should return a normalized payload with collapsed spaces,
    stripped lines, and a numeric `is_active` flag.
    """
    ensure_app()
    form = CustomerForm()
    # Populate fields with extra whitespace and newlines
    form.name.setText("  Alice   ")
    form.contact.setPlainText(" 123-456 \n  email@  exa mp le.com \n\n")
    form.addr.setPlainText("\n 123   Main St \nApt 5 \n\n")
    form.is_active.setChecked(True)

    payload = form.get_payload()
    # Name should be trimmed and collapsed
    assert payload["name"] == "Alice"
    # Each line in contact is stripped and internal whitespace collapsed
    assert payload["contact_info"] == "123-456\nemail@ exa mp le.com"
    # Address should be normalized and trailing blank lines removed
    assert payload["address"] == "123 Main St\nApt 5"
    # is_active should be 1 (not True/False)
    assert payload["is_active"] == 1


def test_customer_form_get_payload_empty_name_invalid():
    """
    An empty name should cause get_payload to return None.
    """
    ensure_app()
    form = CustomerForm()
    form.name.setText("")
    form.contact.setPlainText("someone@example.com")
    # We don't need to set address/is_active for this validation
    payload = form.get_payload()
    assert payload is None


def test_customer_form_get_payload_empty_contact_invalid():
    """
    An empty contact info should cause get_payload to return None.
    """
    ensure_app()
    form = CustomerForm()
    form.name.setText("Bob")
    form.contact.setPlainText("")
    payload = form.get_payload()
    assert payload is None


def test_customer_form_dup_check_invoked():
    """
    The duplicate-check callback should be invoked with the normalized name
    and current_id, but it does not block submission.
    """
    ensure_app()
    calls = []

    def dup_check(name: str, current_id):
        calls.append((name, current_id))
        # Simulate finding a duplicate; form should warn but still return payload
        return True

    form = CustomerForm(dup_check=dup_check)
    form.name.setText(" Jane  Doe ")
    form.contact.setPlainText("555-1234")
    # Call get_payload, which should trigger the dup_check callback
    payload = form.get_payload()
    # Verify the callback was called once with normalized name and None for current_id
    assert calls == [("Jane Doe", None)]
    # The payload should still be returned despite the duplicate warning
    assert payload["name"] == "Jane Doe"
    assert payload["contact_info"] == "555-1234"
    assert payload["address"] is None
    assert payload["is_active"] == 1
