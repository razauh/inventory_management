from decimal import Decimal

import modules.accounting.service as service_module
from modules.accounting import (
    AccountingService,
    CustomerCreditApplicationPayload,
    CustomerCreditApplicationResult,
    CustomerPaymentEffect,
    CustomerPaymentPayload,
    CustomerPaymentResult,
    PurchaseReturnPayload,
    PurchaseReturnResult,
    SaleReturnEffect,
    SaleReturnPayload,
    VendorPaymentEffect,
    VendorPaymentPayload,
    VendorPaymentResult,
)
from modules.accounting.audit.repository import AccountingAuditRepository


def _events(conn, event_type):
    return AccountingAuditRepository(conn).list_events({"event_type": event_type})


def test_vendor_payment_wrapper_logs_audit_event(conn, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "record_current_vendor_payment_event",
        lambda _conn, payload: VendorPaymentResult(
            payment_id=10,
            credit_tx_id=None,
            effect=VendorPaymentEffect(
                purchase_id=payload.purchase_id,
                vendor_id=1,
                amount_due=Decimal("20"),
                payment_amount=payload.amount,
                overpayment_credit=Decimal("0"),
            ),
        ),
    )

    AccountingService(conn).record_vendor_payment_event(
        VendorPaymentPayload(purchase_id="PO-AUD", amount=Decimal("4"), method="Cash", date="2026-05-01")
    )

    assert _events(conn, "vendor_payment")[0].rule_id == "ACC-RULE-075"


def test_purchase_return_wrapper_logs_audit_event(conn, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "record_current_purchase_return_event",
        lambda _conn, payload: PurchaseReturnResult(
            purchase_id=payload.purchase_id,
            transaction_ids=(1,),
            return_value=Decimal("6"),
            settlement_amount=Decimal("0"),
        ),
    )

    AccountingService(conn).record_purchase_return_event(
        PurchaseReturnPayload(purchase_id="PO-AUD", date="2026-05-02", created_by=None, lines=())
    )

    assert _events(conn, "purchase_return")[0].rule_id == "ACC-RULE-020"


def test_customer_payment_wrapper_logs_audit_event(conn, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "record_current_customer_payment_event",
        lambda _conn, payload: CustomerPaymentResult(
            payment_id=20,
            effect=CustomerPaymentEffect(
                sale_id=payload.sale_id,
                customer_id=payload.customer_id,
                amount=payload.amount,
                clearing_state=payload.clearing_state,
            ),
        ),
    )

    AccountingService(conn).record_customer_payment_event(
        CustomerPaymentPayload(
            sale_id="S-AUD",
            customer_id=1,
            amount=Decimal("11"),
            method="Cash",
            date="2026-05-03",
        )
    )

    assert _events(conn, "customer_payment")[0].rule_id == "ACC-RULE-046"


def test_sale_return_wrapper_logs_audit_event(conn, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "record_current_sale_return_event",
        lambda _conn, payload: SaleReturnEffect(
            return_value=Decimal("8"),
            allocated_order_discount=Decimal("0"),
            cogs_reversal_value=Decimal("2"),
            remaining_due_before_return=Decimal("0"),
            settlement_due=Decimal("0"),
            cash_refund_cap=Decimal("0"),
            cash_refund=Decimal("0"),
            credit_amount=Decimal("8"),
        ),
    )

    AccountingService(conn).record_sale_return_event(
        SaleReturnPayload(sale_id="S-AUD", date="2026-05-04", created_by=None, lines=())
    )

    assert _events(conn, "sale_return_settlement")[0].rule_id == "ACC-RULE-043"


def test_credit_application_wrapper_logs_audit_event(conn, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "record_current_customer_credit_application_event",
        lambda _conn, payload: CustomerCreditApplicationResult(
            tx_id=30,
            customer_id=payload.customer_id,
            sale_id=payload.sale_id,
            amount=payload.amount,
        ),
    )

    AccountingService(conn).record_customer_credit_application_event(
        CustomerCreditApplicationPayload(
            customer_id=1,
            sale_id="S-AUD",
            amount=Decimal("3"),
            date="2026-05-05",
        )
    )

    assert _events(conn, "customer_credit_application")[0].rule_id == "ACC-RULE-065"


def test_expense_create_update_delete_wrappers_log_audit_events(conn, monkeypatch):
    monkeypatch.setattr(service_module, "record_current_expense_create_event", lambda *_a, **_k: 40)
    monkeypatch.setattr(service_module, "record_current_expense_update_event", lambda *_a, **_k: None)
    monkeypatch.setattr(service_module, "record_current_expense_delete_event", lambda *_a, **_k: None)

    svc = AccountingService(conn)
    svc.record_expense_create_event("Fuel", 5.0, "2026-05-06", None)
    svc.record_expense_update_event(40, "Fuel", 6.0, "2026-05-07", None)
    svc.record_expense_delete_event(40)

    assert _events(conn, "expense_create")[0].rule_id == "ACC-RULE-102"
    assert _events(conn, "expense_update")[0].rule_id == "ACC-RULE-103"
    assert _events(conn, "expense_delete")[0].rule_id == "ACC-RULE-104"
