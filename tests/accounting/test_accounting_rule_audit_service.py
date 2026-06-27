from decimal import Decimal

from modules.accounting import AccountingService
from modules.accounting.audit.repository import AccountingAuditRepository
from modules.accounting.dto import CustomerCreditPayload


def test_customer_credit_write_creates_audit_event(conn):
    customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]

    result = AccountingService(conn).record_customer_credit_event(
        CustomerCreditPayload(
            customer_id=customer_id,
            amount=Decimal("7.25"),
            date="2026-03-01",
            notes="audit test",
        )
    )

    rows = AccountingAuditRepository(conn).list_events({"event_type": "customer_credit"})
    assert rows
    assert rows[0].rule_id == "ACC-RULE-063"
    assert rows[0].source_id == str(result.tx_id)
    assert rows[0].party_id == customer_id
    assert rows[0].amount == Decimal("7.25")


def test_audit_event_rolls_back_with_business_write(conn):
    customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]
    conn.execute("SAVEPOINT audit_rollback")
    AccountingService(conn).record_customer_credit_event(
        CustomerCreditPayload(
            customer_id=customer_id,
            amount=Decimal("3.00"),
            date="2026-03-02",
        )
    )
    assert AccountingAuditRepository(conn).list_events({"event_type": "customer_credit"})

    conn.execute("ROLLBACK TO audit_rollback")
    conn.execute("RELEASE audit_rollback")

    rows = AccountingAuditRepository(conn).list_events({"event_type": "customer_credit"})
    assert not rows


def test_read_side_balance_does_not_create_audit_event(conn):
    customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]
    before = len(AccountingAuditRepository(conn).list_events({}))

    AccountingService(conn).get_customer_balance(customer_id)

    after = len(AccountingAuditRepository(conn).list_events({}))
    assert after == before
