"""
Tests for the customer module.

This suite exercises the table model, form validation, action helpers,
controller flows, history service and repository logic for customers.
The goal is to mirror the level of coverage provided for purchases and vendors.

Where possible the tests operate against in-memory or temporary SQLite
databases to avoid interfering with the main test database.  For UI
interactions the pytest-qt `qtbot` fixture is used and PySide widgets
are stubbed when needed via monkeypatch.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from inventory_management.modules.customer.model import CustomersTableModel
from inventory_management.modules.customer.form import CustomerForm
from inventory_management.modules.customer.actions import (
    receive_payment,
    record_advance,
    apply_advance,
    open_payment_history,
)
from inventory_management.modules.customer.history import CustomerHistoryService
from inventory_management.database.repositories.customers_repo import CustomersRepo, DomainError, Customer
from inventory_management.database.repositories.customer_advances_repo import CustomerAdvancesRepo


# ---------------------------------------------------------------------------
# Suite A – Customer table & form
# ---------------------------------------------------------------------------

def test_a0_customers_table_model_basics(qtbot: pytest.fixture) -> None:
    """A0: CustomersTableModel should expose rows/columns and active flags."""
    # Prepare sample customers; attach is_active attributes dynamically
    row1 = Customer(customer_id=1, name="Alice", contact_info="123", address="Addr1")
    # row1 has no is_active attribute → defaults to active
    row2 = Customer(customer_id=2, name="Bob", contact_info="456", address="Addr2")
    setattr(row2, "is_active", 0)
    row3 = Customer(customer_id=3, name="Carol", contact_info="789", address=None)
    setattr(row3, "is_active", 1)

    model = CustomersTableModel([row1, row2, row3])

    # Row/column counts
    assert model.rowCount() == 3
    assert model.columnCount() == len(CustomersTableModel.HEADERS)

    # Header labels
    headers = [model.headerData(i, Qt.Horizontal, Qt.DisplayRole) for i in range(model.columnCount())]
    assert headers == CustomersTableModel.HEADERS

    # Data for each cell and active flags
    for r, row in enumerate([row1, row2, row3]):
        for c, expected in enumerate([
            row.customer_id,
            row.name,
            row.contact_info,
            (row.address or ""),
            "Active" if getattr(row, "is_active", 1) else "Inactive",
        ]):
            idx = model.index(r, c)
            assert model.data(idx, Qt.DisplayRole) == expected
        # Custom role exposes raw active flag (1/0)
        idx = model.index(r, 4)
        active_flag = 1 if getattr(row, "is_active", 1) else 0
        assert model.data(idx, CustomersTableModel.IS_ACTIVE_ROLE) == active_flag


def test_a1_customer_form_required_and_normalization(qtbot: pytest.fixture) -> None:
    """A1: CustomerForm should validate required fields and normalize inputs."""
    # Blank name should return None
    form = CustomerForm()
    form.name.setText("")
    form.contact.setPlainText("some contact")
    assert form.get_payload() is None
    # We intentionally avoid asserting .hasFocus() here due to event loop timing in tests.

    # Blank contact should return None
    form = CustomerForm()
    form.name.setText("Alice")
    form.contact.setPlainText("")
    payload = form.get_payload()
    assert payload is None

    # Normalization trims and collapses whitespace; empty address returns None
    form = CustomerForm()
    form.name.setText("  Alice   B.   ")
    form.contact.setPlainText("  phone  123  \n  email@example.com  ")
    form.addr.setPlainText("  123 Street\n\n Apt 4  ")
    payload = form.get_payload()
    assert payload is not None
    assert payload["name"] == "Alice B."
    assert payload["contact_info"] == "phone 123\nemail@example.com"
    # Normalized address preserves newlines and collapses spaces; blank lines in the middle are preserved
    assert payload["address"] == "123 Street\n\nApt 4"
    assert payload["is_active"] == 1  # default ON

    # Address entirely whitespace should be dropped
    form.addr.setPlainText("    \n   ")
    payload = form.get_payload()
    assert payload is not None
    assert payload["address"] is None


def test_a2_customer_form_duplicate_name_warning(monkeypatch, qtbot: pytest.fixture) -> None:
    """A2: The form should warn on duplicate names but still return the payload."""
    warnings: List[str] = []

    # Stub QMessageBox.warning to record calls (local import is fine too)
    from PySide6.QtWidgets import QMessageBox as _QMB

    def fake_warning(parent, title, text):
        warnings.append(text)
        return _QMB.Ok

    monkeypatch.setattr(_QMB, "warning", fake_warning)

    # dup_check always returns True to trigger warning
    def dup_check(name: str, current_id: Any) -> bool:
        return True

    form = CustomerForm(dup_check=dup_check)
    form.name.setText("Alice")
    form.contact.setPlainText("123")
    payload = form.get_payload()
    # Should still return payload
    assert payload is not None
    # Warning should have been called
    assert warnings, "expected duplicate warning to be shown"


# ---- New tests added (A3–A7) ------------------------------------------------

def test_a3_customer_form_initial_values(qtbot: pytest.fixture) -> None:
    """A3: Initial values populate the form and payload returns normalized fields."""
    initial = {
        "customer_id": 42,
        "name": "  John  ",
        "contact_info": "  123  ",
        "address": "  5th Avenue  ",
        "is_active": 0,
    }
    form = CustomerForm(initial=initial)
    # The widgets show raw initial values
    assert form.name.text() == initial["name"]
    assert form.contact.toPlainText() == initial["contact_info"]
    assert form.addr.toPlainText() == initial["address"]
    assert form.is_active.isChecked() is False  # is_active=0 → unchecked
    # The payload normalizes whitespace and carries through is_active=0
    payload = form.get_payload()
    assert payload["name"] == "John"
    assert payload["contact_info"] == "123"
    assert payload["address"] == "5th Avenue"
    assert payload["is_active"] == 0


def test_a4_customer_form_active_toggle(qtbot: pytest.fixture) -> None:
    """A4: The Active checkbox’s default state and its effect on the payload."""
    form = CustomerForm()
    form.name.setText("Alice")
    form.contact.setPlainText("contact")
    # Initially checked → is_active == 1
    payload = form.get_payload()
    assert payload is not None and payload["is_active"] == 1
    # Toggle off → is_active should be 0
    form.is_active.setChecked(False)
    payload2 = form.get_payload()
    assert payload2 is not None and payload2["is_active"] == 0


def test_a5_customer_form_dup_check_no_warning(monkeypatch, qtbot: pytest.fixture) -> None:
    """A5: When dup_check returns False, no warning should be shown and payload should be returned."""
    warnings: List[str] = []

    def fake_warning(parent, title, text):
        warnings.append(text)
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    # dup_check always returns False (no duplicate)
    def no_dup(name: str, current_id: Any) -> bool:
        return False

    form = CustomerForm(dup_check=no_dup)
    form.name.setText("Bob")
    form.contact.setPlainText("321")
    payload = form.get_payload()
    assert payload is not None
    assert not warnings  # no warning called


def test_a6_customer_form_dup_check_exception(monkeypatch, qtbot: pytest.fixture) -> None:
    """A6: If dup_check raises an exception, get_payload should still return a payload and show no warning."""
    warnings: List[str] = []

    def fake_warning(parent, title, text):
        warnings.append(text)
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    # dup_check raises an exception
    def bad_dup(name: str, current_id: Any) -> bool:
        raise RuntimeError("dup check failed")

    form = CustomerForm(dup_check=bad_dup)
    form.name.setText("Carol")
    form.contact.setPlainText("789")
    payload = form.get_payload()
    assert payload is not None
    assert not warnings  # the exception in dup_check shouldn’t surface as a warning


def test_a7_customer_form_accept_stores_payload(qtbot: pytest.fixture) -> None:
    """A7: accept() stores the payload on valid input and leaves it None on invalid input."""
    # Valid input: calling accept should populate _payload
    form = CustomerForm()
    form.name.setText("Dave")
    form.contact.setPlainText("999")
    assert form.payload() is None
    form.accept()  # accept triggers get_payload and sets _payload when valid
    p = form.payload()
    assert p is not None
    assert p["name"] == "Dave" and p["contact_info"] == "999"

    # Invalid input: blank name should prevent payload from being stored
    form2 = CustomerForm()
    form2.name.setText("")
    form2.contact.setPlainText("111")
    form2.accept()
    assert form2.payload() is None


# ---------------------------------------------------------------------------
# Suite B – Customer actions
# ---------------------------------------------------------------------------

class _StubRepo:
    """Simple stub for SalePaymentsRepo used by receive_payment."""
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def record_payment(self, **kwargs) -> int:
        self.calls.append(kwargs)
        # return a fake payment id
        return 42


def test_b1_receive_payment_happy(monkeypatch) -> None:
    """B1: receive_payment should succeed when defaults are valid and with_ui=False."""
    repo = _StubRepo()

    # Override repo factory to return our stub
    def repo_factory(db_path: str | Path):
        return repo

    result = receive_payment(
        db_path="/tmp/tmp.db",
        sale_id="S1",
        customer_id=1,
        form_defaults={"amount": 100.0, "method": "cash"},
        with_ui=False,
        repo_factory=repo_factory,
    )

    assert result.success is True
    assert result.id == 42
    assert repo.calls, "record_payment should have been called"


@pytest.mark.parametrize(
    "defaults,missing_field",
    [({"method": "cash"}, "amount"), ({"amount": 10.0}, "method")],
)
def test_b2_receive_payment_missing(monkeypatch, defaults: Dict[str, Any], missing_field: str) -> None:
    """B2: receive_payment should detect missing amount/method keys."""
    repo = _StubRepo()
    def repo_factory(db_path: str | Path):
        return repo

    result = receive_payment(
        db_path="/tmp/tmp.db",
        sale_id="S1",
        customer_id=1,
        form_defaults=defaults,
        with_ui=False,
        repo_factory=repo_factory,
    )
    assert result.success is False
    assert missing_field in result.message


def test_b3_receive_payment_ui_unavailable(monkeypatch) -> None:
    """B3: with with_ui=True and missing UI module, receive_payment returns failure with message."""
    import sys
    # Ensure the UI import fails by removing any loaded module
    modules_to_remove = [
        m for m in list(sys.modules.keys()) if m.startswith("payments.ui.customer_receipt_form")
    ]
    for m in modules_to_remove:
        monkeypatch.delitem(sys.modules, m, raising=False)

    result = receive_payment(
        db_path="/tmp/tmp.db",
        sale_id="S1",
        customer_id=1,
        form_defaults=None,
        with_ui=True,
    )
    assert result.success is False
    assert "Receipt form UI" in result.message


class _StubAdvancesRepo:
    """Stub for CustomerAdvancesRepo used in record/apply advance tests."""
    def __init__(self):
        self.granted: List[Dict[str, Any]] = []
        self.applied: List[Dict[str, Any]] = []

    def grant_credit(self, *, customer_id: int, amount: float, date: str | None, notes: str | None, created_by: int | None) -> int:
        if amount <= 0:
            raise ValueError("Deposit amount must be a positive number.")
        self.granted.append({
            "customer_id": customer_id,
            "amount": amount,
            "date": date,
            "notes": notes,
            "created_by": created_by,
        })
        return 99

    def apply_credit_to_sale(self, *, customer_id: int, sale_id: str, amount: float, date: str | None, notes: str | None, created_by: int | None) -> int:
        if amount > 0:
            raise ValueError("apply_credit_to_sale expects a negative amount from actions")
        self.applied.append({
            "customer_id": customer_id,
            "sale_id": sale_id,
            "amount": amount,
            "date": date,
            "notes": notes,
            "created_by": created_by,
        })
        return 88


def test_b4_record_advance(monkeypatch) -> None:
    """B4: record_advance should call grant_credit on repo and return success."""
    repo = _StubAdvancesRepo()
    def repo_factory(db_path: str | Path):
        return repo
    # Valid amount
    res = record_advance(db_path="/tmp/tmp.db", customer_id=1, amount=50.0, repo_factory=repo_factory)
    assert res.success is True and res.id == 99
    assert repo.granted
    # Invalid amount (zero)
    res2 = record_advance(db_path="/tmp/tmp.db", customer_id=1, amount=0, repo_factory=repo_factory)
    assert res2.success is False


def test_b5_apply_advance(monkeypatch) -> None:
    """B5: apply_advance stores negative amounts and validates input."""
    repo = _StubAdvancesRepo()
    def repo_factory(db_path: str | Path):
        return repo
    # Positive amount creates negative record
    res = apply_advance(
        db_path="/tmp/tmp.db",
        customer_id=1,
        sale_id="SO1",
        amount_to_apply=20.0,
        repo_factory=repo_factory,
    )
    assert res.success is True and res.id == 88
    assert repo.applied[0]["amount"] < 0
    # Non-positive input
    res2 = apply_advance(
        db_path="/tmp/tmp.db",
        customer_id=1,
        sale_id="SO1",
        amount_to_apply=0,
        repo_factory=repo_factory,
    )
    assert res2.success is False


def test_b6_open_payment_history(monkeypatch) -> None:
    """B6: open_payment_history returns payload when with_ui=False and falls back when UI missing."""
    stub_history_payload = {"summary": {"open_due_sum": 0.0}, "sales": [], "payments": [], "advances": {}, "timeline": []}

    class StubHistory:
        def __init__(self, db_path: str):
            pass
        def full_history(self, customer_id: int) -> Dict[str, Any]:
            return stub_history_payload

    # Patch the factory used by actions
    from inventory_management.modules.customer import actions as actions_mod
    monkeypatch.setattr(actions_mod, "_get_customer_history_service", lambda db_path: StubHistory(db_path))

    # with_ui=False returns payload
    res = open_payment_history(db_path="/tmp/tmp.db", customer_id=1, with_ui=False)
    assert res.success is True
    assert res.payload == stub_history_payload

    # with_ui=True but UI missing should return payload and message
    # Ensure payments.ui.payment_history_view import fails
    monkeypatch.setattr(actions_mod, "_get_customer_history_service", lambda db_path: StubHistory(db_path))
    res2 = open_payment_history(db_path="/tmp/tmp.db", customer_id=1, with_ui=True)
    assert res2.success is True
    assert res2.payload == stub_history_payload
    assert "History view UI is unavailable" in (res2.message or "")


# ---------------------------------------------------------------------------
# Suite C – Customer controller flows
# ---------------------------------------------------------------------------

# For controller tests we'll avoid constructing the real controller with a full UI.
# Instead we create a minimal dummy object that binds the unbound methods from
# CustomerController and stubs out dependencies.

from inventory_management.modules.customer.controller import CustomerController as _CC


class DummyController:
    """A lightweight stand-in for CustomerController for unit testing."""
    def __init__(self):
        # attributes normally set on real controller
        self.view = object()
        self.conn = None  # may be overridden in tests
        # placeholders for capturing side-effects
        self.info_calls: List[tuple] = []
        self.reload_called = False

    # Methods that forward to static implementations on real controller
    _preflight = _CC._preflight
    _on_receive_payment = _CC._on_receive_payment
    _on_record_advance = _CC._on_record_advance
    _on_apply_advance = _CC._on_apply_advance
    _on_payment_history = _CC._on_payment_history
    _eligible_sales_for_application = _CC._eligible_sales_for_application

    # Stubs for methods accessed by flows
    def _selected_id(self) -> int | None:
        return self._selected_stub() if hasattr(self, "_selected_stub") else None

    def _fetch_is_active(self, cid: int) -> int:
        return 1

    def _ensure_db_path_or_toast(self) -> str | None:
        return getattr(self, "_db_path_stub", ":memory:")

    def _db_path_from_conn(self) -> str | None:
        return getattr(self, "_db_path_stub", ":memory:")

    def _lazy_attr(self, dotted: str, *, toast_title: str, on_fail: str):
        return self._lazy_map.get(dotted)

    def _sale_belongs_to_customer_and_is_sale(self, sale_id: str, customer_id: int) -> bool:
        return getattr(self, "_sale_valid", True)

    def _reload(self):
        self.reload_called = True

    # Replace info with our capture via QMessageBox.information patch
    def _capture_info(self, parent: Any, title: str, msg: str) -> None:
        self.info_calls.append((title, msg))


def test_c1_preflight(monkeypatch) -> None:
    """C1: _preflight should enforce selection, active status and file DB presence."""
    dc = DummyController()
    # Patch QMessageBox.information used by controller to our capture
    def fake_information(parent, title, text, *args, **kwargs):
        dc._capture_info(parent, title, text)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox, "information", fake_information)
    # Case: no selection
    dc._selected_stub = lambda: None
    cid, dbp = dc._preflight(require_active=True, require_file_db=True)
    assert cid is None and dbp is None
    assert any("Select" in t for t, _ in dc.info_calls)
    dc.info_calls.clear()
    # Case: inactive customer
    dc._selected_stub = lambda: 1
    dc._fetch_is_active = lambda cid: 0
    cid, dbp = dc._preflight(require_active=True, require_file_db=True)
    assert cid is None and dbp is None
    assert any("Inactive" in t for t, _ in dc.info_calls)
    dc.info_calls.clear()
    # Case: file DB required but unavailable
    dc._fetch_is_active = lambda cid: 1
    dc._db_path_stub = None
    cid, dbp = dc._preflight(require_active=True, require_file_db=True)
    assert cid is None and dbp is None
    # Case: success with in-memory DB allowed
    dc._db_path_stub = None
    cid, dbp = dc._preflight(require_active=True, require_file_db=False)
    assert cid == 1 and dbp == ":memory:"


def test_c2_eligible_sales_for_application() -> None:
    """C2: _eligible_sales_for_application returns only rows with remaining_due>0."""
    # Create fake connection returning three rows
    class FakeConn:
        def execute(self, sql: str, params: tuple):
            class Cursor:
                def fetchall(self_inner):
                    return [
                        {"sale_id": "S1", "date": "2025-01-01", "total_calc": 100.0, "paid_amount": 80.0},
                        {"sale_id": "S2", "date": "2025-01-02", "total_calc": 200.0, "paid_amount": 200.0},
                        {"sale_id": "S3", "date": "2025-01-03", "total_calc": 150.0, "paid_amount": 0.0},
                    ]
            return Cursor()

    dc = DummyController()
    dc.conn = FakeConn()
    result = dc._eligible_sales_for_application(customer_id=1)
    # Should include S1 (remaining 20) and S3 (150) but not S2 (0)
    sale_ids = {r["sale_id"] for r in result}
    assert sale_ids == {"S1", "S3"}
    # Check remaining_due calculation
    for r in result:
        if r["sale_id"] == "S1":
            assert pytest.approx(r["remaining_due"]) == 20.0
        if r["sale_id"] == "S3":
            assert pytest.approx(r["remaining_due"]) == 150.0


def test_c3_on_receive_payment(monkeypatch) -> None:
    """C3: _on_receive_payment validates sale ownership and records payment."""
    dc = DummyController()
    # Stub preflight to return cid/db_path (no self arg in stub)
    dc._preflight = lambda **kwargs: (5, "/tmp/test.db")
    # Stub lazy_attr to supply open_receipt_form and SalePaymentsRepo
    captured_payment: List[Dict[str, Any]] = []
    def stub_open_receipt_form(**kwargs):
        # Simulate user selecting a sale and entering amount/method
        return {"sale_id": "S1", "amount": 50.0, "method": "cash"}
    class StubRepo:
        def __init__(self, db_path: str):
            pass
        def record_payment(self, **kwargs):
            captured_payment.append(kwargs)
            return 7
    dc._lazy_map = {
        "payments.ui.customer_receipt_form.open_receipt_form": stub_open_receipt_form,
        "inventory_management.database.repositories.sale_payments_repo.SalePaymentsRepo": StubRepo,
    }
    dc._sale_valid = True
    # Patch QMessageBox.information to capture controller messages
    def fake_information(parent, title, text, *args, **kwargs):
        dc._capture_info(parent, title, text)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox, "information", fake_information)
    # Invoke
    dc._on_receive_payment()
    # Payment should be recorded and reload called
    assert captured_payment
    assert dc.reload_called is True
    # Title for saved message captured
    assert any("Saved" in title for title, _ in dc.info_calls)
    # Now test invalid sale guard
    dc.info_calls.clear(); captured_payment.clear(); dc.reload_called = False
    dc._sale_valid = False
    dc._on_receive_payment()
    assert not captured_payment
    assert not dc.reload_called
    assert any("Invalid" in title for title, _ in dc.info_calls)
    # Test missing sale_id guard
    def stub_open_receipt_form2(**kwargs):
        return {"amount": 50.0, "method": "cash"}
    dc._sale_valid = True
    dc._lazy_map["payments.ui.customer_receipt_form.open_receipt_form"] = stub_open_receipt_form2
    dc.info_calls.clear(); captured_payment.clear(); dc.reload_called = False
    dc._on_receive_payment()
    assert not captured_payment
    assert any("Required" in title for title, _ in dc.info_calls)


def test_c4_on_record_advance(monkeypatch) -> None:
    """C4: _on_record_advance should call grant_credit and handle errors."""
    dc = DummyController()
    dc._preflight = lambda **kwargs: (3, "/tmp/test.db")
    def fake_information(parent, title, text, *args, **kwargs):
        dc._capture_info(parent, title, text)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox, "information", fake_information)
    # Success path
    adv_repo = _StubAdvancesRepo()
    def stub_open_form(**kwargs):
        return {"amount": 40.0, "date": None, "notes": None, "created_by": None}
    class StubAdvRepoFactory:
        def __init__(self, db_path: str):
            self.repo = adv_repo
        def grant_credit(self, **kwargs):
            return adv_repo.grant_credit(**kwargs)
    dc._lazy_map = {
        "payments.ui.customer_advance_form.open_record_advance_form": stub_open_form,
        "inventory_management.database.repositories.customer_advances_repo.CustomerAdvancesRepo": StubAdvRepoFactory,
    }
    dc._on_record_advance()
    assert adv_repo.granted
    assert dc.reload_called is True
    # Error path: repo raises
    dc.reload_called = False
    adv_repo = _StubAdvancesRepo()
    class StubErrRepoFactory:
        def __init__(self, db_path: str):
            pass
        def grant_credit(self, **kwargs):
            raise ValueError("bad deposit")
    dc._lazy_map["inventory_management.database.repositories.customer_advances_repo.CustomerAdvancesRepo"] = StubErrRepoFactory
    dc._on_record_advance()
    # Should surface Not saved message and not reload
    assert not dc.reload_called
    assert any("Not saved" in title for title, _ in dc.info_calls)


def test_c5_on_apply_advance(monkeypatch) -> None:
    """C5: _on_apply_advance applies credit when valid and blocks invalid cases."""
    dc = DummyController()
    dc._preflight = lambda **kwargs: (2, "/tmp/test.db")
    def fake_information(parent, title, text, *args, **kwargs):
        dc._capture_info(parent, title, text)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox, "information", fake_information)
    # Success path
    adv_repo = _StubAdvancesRepo()
    # eligible sales list not used by this test, but stub to avoid errors
    dc._eligible_sales_for_application = lambda customer_id: [
        {"sale_id": "S1", "date": "2025-01-01", "remaining_due": 50.0, "total": 100.0, "paid": 50.0}
    ]
    def stub_apply_form(**kwargs):
        return {"sale_id": "S1", "amount_to_apply": 10.0, "date": None, "notes": None, "created_by": None}
    class StubAdvRepoFactory:
        def __init__(self, db_path: str):
            pass
        def apply_credit_to_sale(self, **kwargs):
            return adv_repo.apply_credit_to_sale(**kwargs)
    dc._lazy_map = {
        "payments.ui.apply_advance_form.open_apply_advance_form": stub_apply_form,
        "inventory_management.database.repositories.customer_advances_repo.CustomerAdvancesRepo": StubAdvRepoFactory,
    }
    dc._sale_valid = True
    dc._on_apply_advance()
    assert adv_repo.applied
    assert dc.reload_called is True
    # Sale does not belong
    dc.reload_called = False
    dc._sale_valid = False
    dc.info_calls.clear()
    dc._on_apply_advance()
    assert not adv_repo.applied or len(adv_repo.applied) == 1
    assert not dc.reload_called
    assert any("Invalid" in title for title, _ in dc.info_calls)
    # Missing sale_id or amount
    dc._sale_valid = True
    def stub_apply_form2(**kwargs):
        return {"amount_to_apply": None}
    dc._lazy_map["payments.ui.apply_advance_form.open_apply_advance_form"] = stub_apply_form2
    dc.info_calls.clear(); dc.reload_called = False
    dc._on_apply_advance()
    assert not dc.reload_called
    assert any("Required" in title for title, _ in dc.info_calls)


def test_c6_on_payment_history(monkeypatch) -> None:
    """C6: _on_payment_history opens history UI or falls back."""
    dc = DummyController()
    dc._preflight = lambda **kwargs: (4, "/tmp/test.db")
    def fake_information(parent, title, text, *args, **kwargs):
        dc._capture_info(parent, title, text)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox, "information", fake_information)
    # Stub history service and UI
    called_history: List[tuple] = []
    class StubHistSvc:
        def __init__(self, db_path: str):
            pass
        def full_history(self, cid: int):
            return {"summary": {}}
    def stub_open_history(**kwargs):
        called_history.append(kwargs)
    dc._lazy_map = {
        "inventory_management.modules.customer.history.CustomerHistoryService": StubHistSvc,
        "payments.ui.payment_history_view.open_customer_history": stub_open_history,
    }
    dc._on_payment_history()
    # Should call UI
    assert called_history
    # Now test fallback when UI missing
    called_history.clear()
    dc._lazy_map["payments.ui.payment_history_view.open_customer_history"] = None
    dc.info_calls.clear()
    dc._on_payment_history()
    # Should call info and not UI
    assert not called_history
    assert any("Unavailable" in title for title, _ in dc.info_calls)


# ---------------------------------------------------------------------------
# Suite D – Customer history service
# ---------------------------------------------------------------------------

def _build_history_db(tmp_path: str) -> None:
    """Create a temporary SQLite database with minimal schema and seed data for history tests."""
    con = sqlite3.connect(tmp_path)
    con.execute("PRAGMA foreign_keys = ON;")
    # Schema
    con.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT,
            contact_info TEXT,
            address TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE sales (
            sale_id TEXT PRIMARY KEY,
            customer_id INTEGER,
            date TEXT,
            total_amount REAL,
            paid_amount REAL,
            advance_payment_applied REAL,
            payment_status TEXT,
            order_discount REAL,
            notes TEXT,
            created_by INTEGER,
            source_type TEXT,
            source_id TEXT,
            doc_type TEXT
        );
        CREATE TABLE sale_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT,
            product_id INTEGER,
            quantity REAL,
            uom_id INTEGER,
            unit_price REAL,
            item_discount REAL
        );
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE uoms (uom_id INTEGER PRIMARY KEY, unit_name TEXT);
        CREATE TABLE sale_detailed_totals (
            sale_id TEXT PRIMARY KEY,
            subtotal_before_order_discount REAL,
            calculated_total_amount REAL
        );
        CREATE TABLE sale_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT,
            date TEXT,
            amount REAL,
            method TEXT,
            bank_account_id INTEGER,
            instrument_type TEXT,
            instrument_no TEXT,
            instrument_date TEXT,
            deposited_date TEXT,
            cleared_date TEXT,
            clearing_state TEXT,
            ref_no TEXT,
            notes TEXT,
            created_by INTEGER
        );
        CREATE TABLE customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            tx_date TEXT,
            amount REAL,
            source_type TEXT,
            source_id TEXT,
            notes TEXT,
            created_by INTEGER
        );
        CREATE VIEW v_customer_advance_balance AS
            SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
            FROM customer_advances
            GROUP BY customer_id;
        """
    )
    # Seed reference data
    con.executemany("INSERT INTO products(product_id, name) VALUES (?, ?)", [(1, "Widget"), (2, "Gadget")])
    con.executemany("INSERT INTO uoms(uom_id, unit_name) VALUES (?, ?)", [(1, "pcs")])
    # Seed customer
    con.execute("INSERT INTO customers(customer_id, name, contact_info, address) VALUES (99, 'Cust', 'C', 'A')")
    # Sales
    con.executemany(
        "INSERT INTO sales(sale_id, customer_id, date, total_amount, paid_amount, advance_payment_applied, payment_status, order_discount, notes, created_by, source_type, source_id, doc_type)"
        " VALUES (?, ?, ?, ?, ?, ?, 'unpaid', 0, NULL, NULL, NULL, NULL, 'sale')",
        [
            ("S1", 99, "2025-01-01", 100.0, 120.0, 0.0),
            ("S2", 99, "2025-01-03", 200.0, 50.0, 0.0),
        ],
    )
    # Detailed totals (matches totals)
    con.executemany(
        "INSERT INTO sale_detailed_totals(sale_id, subtotal_before_order_discount, calculated_total_amount) VALUES (?, ?, ?)",
        [("S1", 100.0, 100.0), ("S2", 200.0, 200.0)],
    )
    # Sale items
    con.executemany(
        "INSERT INTO sale_items(sale_id, product_id, quantity, uom_id, unit_price, item_discount) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("S1", 1, 1.0, 1, 40.0, 0.0),
            ("S1", 2, 1.0, 1, 60.0, 0.0),
            ("S2", 1, 2.0, 1, 50.0, 0.0),
        ],
    )
    # Payments
    con.executemany(
        "INSERT INTO sale_payments(sale_id, date, amount, method, bank_account_id, instrument_type, instrument_no, instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by)"
        " VALUES (?, ?, ?, 'cash', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
        [
            ("S1", "2025-01-04", 60.0),
            ("S2", "2025-01-05", 50.0),
        ],
    )
    # Advances: deposit and application
    con.executemany(
        "INSERT INTO customer_advances(customer_id, tx_date, amount, source_type, source_id, notes, created_by)"
        " VALUES (99, ?, ?, ?, ?, NULL, NULL)",
        [
            ("2025-01-02", 50.0, 'deposit', None),
            ("2025-01-06", -20.0, 'applied_to_sale', 'S1'),
        ],
    )
    con.commit()
    con.close()


def test_d1_sales_with_items_clamps_negative() -> None:
    """D1: sales_with_items should calculate remaining_due and clamp negatives to 0."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _build_history_db(tmp.name)
        svc = CustomerHistoryService(tmp.name)
        sales = svc.sales_with_items(99)
        # Two sales expected ordered by date
        assert [s["sale_id"] for s in sales] == ["S1", "S2"]
        # Sale1 paid more than total → remaining_due clamped to 0
        assert sales[0]["remaining_due"] == 0.0
        # Sale2 due = 200 - 50 = 150
        assert sales[1]["remaining_due"] == 150.0


def test_d2_payments_and_advances_ledger() -> None:
    """D2: sale_payments and advances_ledger return chronological entries and balances."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _build_history_db(tmp.name)
        svc = CustomerHistoryService(tmp.name)
        pay = svc.sale_payments(99)
        assert [p["amount"] for p in pay] == [60.0, 50.0]
        # Advances ledger entries and balance
        adv = svc.advances_ledger(99)
        amounts = [e["amount"] for e in adv["entries"]]
        # deposit then application
        assert amounts == [50.0, -20.0]
        assert adv["balance"] == 30.0


def test_d3_timeline_sorting() -> None:
    """D3: timeline merges sale/payment/advances chronologically with priority rules."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _build_history_db(tmp.name)
        svc = CustomerHistoryService(tmp.name)
        tl = svc.timeline(99)
        # Expect 6 events: two sales, two payments, deposit, applied credit
        kinds = [e["kind"] for e in tl]
        assert kinds == ["sale", "advance", "sale", "receipt", "receipt", "advance_applied"]
        # Ensure sale events come before receipts on same day (S2 sale date < payments)
        assert tl[2]["kind"] == "sale" and tl[3]["kind"] == "receipt"


def test_d4_overview_and_full_history() -> None:
    """D4: overview computes summary fields and full_history aggregates all parts."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _build_history_db(tmp.name)
        svc = CustomerHistoryService(tmp.name)
        ov = svc.overview(99)
        assert ov["sales_count"] == 2
        assert ov["open_due_sum"] == 150.0
        assert ov["credit_balance"] == 30.0
        assert ov["last_sale_date"] == "2025-01-03"
        assert ov["last_payment_date"] == "2025-01-05"
        assert ov["last_advance_date"] == "2025-01-06"
        full = svc.full_history(99)
        assert set(full.keys()) == {"summary", "sales", "payments", "advances", "timeline"}


# ---------------------------------------------------------------------------
# Suite E – Repository tests
# ---------------------------------------------------------------------------

def _create_customers_repo_db() -> sqlite3.Connection:
    """Create an in-memory DB with customers table for repo tests."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE customers (\n"
        "  customer_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "  name TEXT NOT NULL,\n"
        "  contact_info TEXT NOT NULL,\n"
        "  address TEXT,\n"
        "  is_active INTEGER DEFAULT 1\n"
        ");"
    )
    con.row_factory = sqlite3.Row
    return con


def test_e1_customers_repo_crud_and_search() -> None:
    """E1: CustomersRepo should validate, normalize, search and delete."""
    con = _create_customers_repo_db()
    repo = CustomersRepo(con)
    # create rejects blank name/contact
    with pytest.raises(DomainError):
        repo.create(name="", contact_info="", address=None)
    with pytest.raises(DomainError):
        repo.create(name="John", contact_info="", address=None)
    # create with leading/trailing whitespace should trim
    cid = repo.create(name="  John  ", contact_info="  123  ", address="  addr  ")
    row = con.execute("SELECT name, contact_info, address FROM customers WHERE customer_id=?", (cid,)).fetchone()
    assert row["name"] == "John" and row["contact_info"] == "123" and row["address"] == "addr"
    # insert inactive manually
    con.execute("INSERT INTO customers(name, contact_info, address, is_active) VALUES ('Inactive', 'i', 'a', 0)")
    # list_customers active_only
    active = repo.list_customers()
    assert all(getattr(c, "name") != "Inactive" for c in active)
    # list_customers include inactive
    all_customers = repo.list_customers(active_only=False)
    assert any(getattr(c, "name") == "Inactive" for c in all_customers)
    # search by name/contact/address/id
    assert repo.search("John")
    assert repo.search("123")
    assert repo.search(str(cid))
    assert not repo.search("Nonexistent")
    # delete removes row
    repo.delete(cid)
    assert repo.get(cid) is None


# ---------------------------------------------------------------------------
# Suite F – CustomerAdvancesRepo tests
# ---------------------------------------------------------------------------

def _create_adv_repo_db() -> str:
    """Create a temporary SQLite file with tables for customer advances tests."""
    fd, path = tempfile.mkstemp()
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON;")
    con.executescript(
        """
        CREATE TABLE sales (
            sale_id TEXT PRIMARY KEY,
            customer_id INTEGER,
            total_amount REAL,
            paid_amount REAL,
            advance_payment_applied REAL,
            doc_type TEXT
        );
        CREATE TABLE customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            tx_date TEXT,
            amount REAL,
            source_type TEXT,
            source_id TEXT,
            notes TEXT,
            created_by INTEGER
        );
        CREATE VIEW v_customer_advance_balance AS
            SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
            FROM customer_advances GROUP BY customer_id;
        """
    )
    # Insert a sample sale for apply tests
    con.execute(
        "INSERT INTO sales(sale_id, customer_id, total_amount, paid_amount, advance_payment_applied, doc_type)"
        " VALUES ('S1', 10, 100.0, 20.0, 30.0, 'sale')"
    )
    # Insert a quotation sale
    con.execute(
        "INSERT INTO sales(sale_id, customer_id, total_amount, paid_amount, advance_payment_applied, doc_type)"
        " VALUES ('Q1', 10, 50.0, 0.0, 0.0, 'quotation')"
    )
    con.commit()
    con.close()
    return path


def test_f1_customer_advances_repo_validation_and_apply() -> None:
    """F1: CustomerAdvancesRepo should validate amounts and sale constraints."""
    db_path = _create_adv_repo_db()
    repo = CustomerAdvancesRepo(db_path)
    # grant_credit positive
    tx = repo.grant_credit(customer_id=10, amount=50.0, date="2025-01-01", notes=None, created_by=None)
    assert tx == 1
    # grant_credit zero raises
    with pytest.raises(ValueError):
        repo.grant_credit(customer_id=10, amount=0.0, date="2025-01-01", notes=None, created_by=None)
    # add_return_credit positive
    tx2 = repo.add_return_credit(customer_id=10, amount=20.0, sale_id="S1", date="2025-01-02", notes=None, created_by=None)
    assert tx2 == 2
    # add_return_credit zero raises
    with pytest.raises(ValueError):
        repo.add_return_credit(customer_id=10, amount=0.0, sale_id=None, date=None, notes=None, created_by=None)
    # apply_credit_to_sale: invalid sale id
    with pytest.raises(ValueError):
        repo.apply_credit_to_sale(customer_id=10, sale_id="NOSALE", amount=10.0, date="2025-01-03", notes=None, created_by=None)
    # apply_credit_to_sale: quotation sale
    with pytest.raises(ValueError):
        repo.apply_credit_to_sale(customer_id=10, sale_id="Q1", amount=10.0, date="2025-01-03", notes=None, created_by=None)
    # apply_credit_to_sale: wrong customer
    with pytest.raises(ValueError):
        repo.apply_credit_to_sale(customer_id=20, sale_id="S1", amount=10.0, date="2025-01-03", notes=None, created_by=None)
    # apply_credit_to_sale: over application (remaining due = 100-20-30=50)
    with pytest.raises(ValueError):
        repo.apply_credit_to_sale(customer_id=10, sale_id="S1", amount=60.0, date="2025-01-03", notes=None, created_by=None)
    # apply_credit_to_sale: valid amount (40) writes negative and returns id
    tx3 = repo.apply_credit_to_sale(customer_id=10, sale_id="S1", amount=40.0, date="2025-01-04", notes=None, created_by=None)
    assert tx3 == 3
    # Check ledger row inserted is negative
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT amount, source_type, source_id FROM customer_advances WHERE tx_id=?", (tx3,)).fetchone()
    assert row["amount"] == -40.0 and row["source_type"] == "applied_to_sale" and row["source_id"] == "S1"
    con.close()


def test_f2_customer_advances_balance_and_ledger() -> None:
    """F2: get_balance and list_ledger reflect deposits and applications in order."""
    db_path = _create_adv_repo_db()
    repo = CustomerAdvancesRepo(db_path)
    # Add deposits and application
    repo.grant_credit(customer_id=10, amount=100.0, date="2025-01-01", notes=None, created_by=None)
    repo.grant_credit(customer_id=10, amount=50.0, date="2025-01-02", notes=None, created_by=None)
    repo.apply_credit_to_sale(customer_id=10, sale_id="S1", amount=30.0, date="2025-01-03", notes=None, created_by=None)
    # Balance = 100 + 50 - 30
    assert repo.get_balance(10) == 120.0
    # Ledger entries ordered by date then id
    entries = repo.list_ledger(10)
    amounts = [e["amount"] for e in entries]
    assert amounts == [100.0, 50.0, -30.0]
