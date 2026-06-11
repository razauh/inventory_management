from modules.customer.history import CustomerHistoryService


def test_timeline_labels_negative_sale_payment_as_refund(monkeypatch):
    service = CustomerHistoryService(":memory:")
    monkeypatch.setattr(service, "sales_with_items", lambda _customer_id: [])
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
