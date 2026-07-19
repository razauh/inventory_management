from inventory_management.modules.customer.actions import open_payment_history


class FakeAccounting:
    def __init__(self):
        self.customer_ids = []

    def get_customer_history(self, customer_id):
        self.customer_ids.append(customer_id)
        return {
            "summary": {"customer_id": customer_id},
            "sales": [],
            "payments": [],
            "advances": {"entries": [], "balance": 0.0},
            "timeline": [],
        }


def test_open_payment_history_uses_supplied_accounting_service(tmp_path, monkeypatch):
    accounting = FakeAccounting()
    monkeypatch.setattr(
        "inventory_management.modules.customer.actions._get_invoice_company_context",
        lambda _db_path: {},
    )

    result = open_payment_history(
        db_path=tmp_path / "unused.db",
        customer_id=42,
        with_ui=False,
        accounting=accounting,
    )

    assert result.success is True
    assert accounting.customer_ids == [42]
    assert result.payload["summary"]["customer_id"] == 42
