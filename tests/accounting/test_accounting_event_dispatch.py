import pytest

from modules.accounting import AccountingService


def test_purchase_event_dispatch_calls_current_paths(monkeypatch):
    service = AccountingService()
    calls = []

    mapping = {
        "inventory_purchase": "record_purchase_inventory_event",
        "payment": "record_vendor_payment_event",
        "return": "record_purchase_return_event",
        "return_inventory": "record_purchase_return_inventory_event",
        "supplier_refund": "record_supplier_refund_event",
        "vendor_advance": "record_vendor_advance_event",
        "vendor_advance_auto_apply": "record_vendor_advance_with_auto_apply",
    }
    for event_type, method_name in mapping.items():
        monkeypatch.setattr(service, method_name, lambda payload, et=event_type: calls.append((et, payload)))
        service.record_purchase_event(event_type, {"id": event_type})

    assert calls == [(event_type, {"id": event_type}) for event_type in mapping]


def test_sale_event_dispatch_calls_current_paths(monkeypatch):
    service = AccountingService()
    calls = []

    mapping = {
        "inventory_sale": "record_sale_inventory_event",
        "payment": "record_customer_payment_event",
        "return": "record_sale_return_event",
        "return_inventory": "record_sale_return_inventory_event",
        "customer_credit": "record_customer_credit_event",
        "customer_credit_application": "record_customer_credit_application_event",
        "quotation_conversion": "record_quotation_conversion_event",
    }
    for event_type, method_name in mapping.items():
        monkeypatch.setattr(service, method_name, lambda payload, et=event_type: calls.append((et, payload)))
        service.record_sale_event(event_type, {"id": event_type})

    assert calls == [(event_type, {"id": event_type}) for event_type in mapping]


def test_sale_payment_state_update_dispatch_uses_keyword_payload(monkeypatch):
    service = AccountingService()
    calls = []
    monkeypatch.setattr(
        service,
        "update_customer_payment_state",
        lambda payment_id, **payload: calls.append((payment_id, payload)),
    )

    service.record_sale_event(
        "payment_state_update",
        {"payment_id": 4, "clearing_state": "cleared", "cleared_date": "2026-06-21"},
    )

    assert calls == [
        (4, {"clearing_state": "cleared", "cleared_date": "2026-06-21"})
    ]


def test_expense_event_dispatch_calls_current_paths(monkeypatch):
    service = AccountingService()
    calls = []
    monkeypatch.setattr(service, "record_expense_create_event", lambda **payload: calls.append(("create", payload)))
    monkeypatch.setattr(service, "record_expense_update_event", lambda **payload: calls.append(("update", payload)))
    monkeypatch.setattr(service, "record_expense_delete_event", lambda expense_id: calls.append(("delete", expense_id)))

    service.record_expense_event("create", {"description": "Coffee", "amount": 10.0, "date": "2026-06-23", "category_id": None})
    service.record_expense_event("update", {"expense_id": 1, "description": "Tea", "amount": 12.0, "date": "2026-06-24", "category_id": None})
    service.record_expense_event("delete", 1)

    assert calls == [
        ("create", {"description": "Coffee", "amount": 10.0, "date": "2026-06-23", "category_id": None}),
        ("update", {"expense_id": 1, "description": "Tea", "amount": 12.0, "date": "2026-06-24", "category_id": None}),
        ("delete", 1),
    ]


def test_unknown_event_type_raises_value_error():
    service = AccountingService()

    with pytest.raises(ValueError):
        service.record_purchase_event("missing", None)
    with pytest.raises(ValueError):
        service.record_sale_event("missing", None)
    with pytest.raises(ValueError):
        service.record_expense_event("missing", None)
