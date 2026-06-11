from modules.customer.history import CustomerHistoryService


def test_timeline_labels_negative_sale_payment_as_refund(monkeypatch):
    service = CustomerHistoryService(":memory:")
    monkeypatch.setattr(service, "sales_with_items", lambda _customer_id: [])
    monkeypatch.setattr(service, "sale_returns", lambda _customer_id: [])
    monkeypatch.setattr(
        service,
        "sale_payments",
        lambda _customer_id: [
            {
                "payment_id": 7,
                "sale_id": "SALE-1",
                "date": "2026-06-11",
                "amount": -25.0,
                "method": "Cash",
                "clearing_state": "cleared",
                "instrument_no": None,
                "notes": "Refund",
            }
        ],
    )
    monkeypatch.setattr(service, "advances_ledger", lambda _customer_id: {"entries": []})

    assert service.timeline(1)[0]["kind"] == "refund"


def test_timeline_keeps_non_negative_sale_payment_as_receipt(monkeypatch):
    service = CustomerHistoryService(":memory:")
    monkeypatch.setattr(service, "sales_with_items", lambda _customer_id: [])
    monkeypatch.setattr(service, "sale_returns", lambda _customer_id: [])
    monkeypatch.setattr(
        service,
        "sale_payments",
        lambda _customer_id: [
            {
                "payment_id": 8,
                "sale_id": "SALE-2",
                "date": "2026-06-11",
                "amount": 25.0,
                "method": "Cash",
                "clearing_state": "cleared",
                "instrument_no": None,
                "notes": None,
            }
        ],
    )
    monkeypatch.setattr(service, "advances_ledger", lambda _customer_id: {"entries": []})

    assert service.timeline(1)[0]["kind"] == "receipt"


def test_timeline_includes_returned_item_before_settlement(monkeypatch):
    service = CustomerHistoryService(":memory:")
    monkeypatch.setattr(service, "sales_with_items", lambda _customer_id: [])
    monkeypatch.setattr(
        service,
        "sale_returns",
        lambda _customer_id: [
            {
                "transaction_id": 9,
                "sale_id": "SALE-3",
                "date": "2026-06-11",
                "amount": -45.0,
                "product_name": "Widget",
                "quantity": 2.0,
                "uom_name": "Piece",
                "notes": "[Return]",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "sale_payments",
        lambda _customer_id: [
            {
                "payment_id": 10,
                "sale_id": "SALE-3",
                "date": "2026-06-11",
                "amount": -45.0,
                "method": "Cash",
                "clearing_state": "cleared",
                "instrument_no": None,
                "notes": "[Return refund]",
            }
        ],
    )
    monkeypatch.setattr(service, "advances_ledger", lambda _customer_id: {"entries": []})

    events = service.timeline(1)

    assert [event["kind"] for event in events] == ["sale_return", "refund"]
    assert events[0]["description"] == "Widget: 2 Piece"
    assert events[0]["amount"] == -45.0
