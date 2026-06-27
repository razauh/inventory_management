from decimal import Decimal

from modules.accounting.audit.dto import AuditEventDraft
from modules.accounting.audit.repository import AccountingAuditRepository


def test_audit_repository_inserts_json_safe_event_and_reads_by_id(conn):
    repo = AccountingAuditRepository(conn)
    event_id = repo.insert_event(
        AuditEventDraft(
            rule_id="ACC-RULE-075",
            event_type="vendor_payment",
            source_type="purchase",
            source_id="PO-1",
            party_type="vendor",
            party_id=1,
            amount=Decimal("12.50"),
            business_date="2026-01-02",
            input_snapshot={"amount": Decimal("12.50")},
            output_snapshot={"payment_id": 99},
            side_effects={"rows": (1, 2)},
            human_summary="Vendor payment recorded.",
            technical_summary="test",
            source_module="tests",
            source_function="test",
        )
    )

    row = repo.get_event(event_id)

    assert row is not None
    assert row.rule_id == "ACC-RULE-075"
    assert row.rule_name == "Vendor payment posting"
    assert row.rule_area == "vendor"
    assert row.amount == Decimal("12.50")
    assert row.currency == "PKR"
    assert row.input_snapshot["amount"] == "12.50"
    assert row.side_effects["rows"] == [1, 2]
    assert row.review_status == "unreviewed"


def test_audit_repository_filters_events(conn):
    repo = AccountingAuditRepository(conn)
    repo.insert_event(
        AuditEventDraft(
            rule_id="ACC-RULE-046",
            event_type="customer_payment",
            source_type="sale",
            source_id="S-1",
            party_type="customer",
            party_id=2,
            amount=Decimal("30"),
            business_date="2026-02-01",
        )
    )
    repo.insert_event(
        AuditEventDraft(
            rule_id="ACC-RULE-102",
            event_type="expense_create",
            source_type="expense",
            source_id=1,
            amount=Decimal("5"),
            business_date="2026-02-03",
        )
    )

    rows = repo.list_events({"rule_area": "sales", "amount_min": 20})

    assert len(rows) == 1
    assert rows[0].event_type == "customer_payment"


def test_review_update_leaves_audit_event_unchanged(conn):
    repo = AccountingAuditRepository(conn)
    event_id = repo.insert_event(
        AuditEventDraft(
            rule_id="ACC-RULE-102",
            event_type="expense_create",
            source_type="expense",
            source_id=1,
            amount=Decimal("5"),
            business_date="2026-02-03",
            human_summary="Expense created.",
        )
    )
    before = repo.get_event(event_id)

    review = repo.upsert_review(
        event_id,
        status="accepted",
        notes="Looks right.",
        expected_behavior="Expense should exist.",
        linked_issue="TASK-1",
        reviewed_by=None,
    )
    after = repo.get_event(event_id)

    assert review.status == "accepted"
    assert after.review_status == "accepted"
    assert after.review_notes == "Looks right."
    assert after.expected_behavior == "Expense should exist."
    assert after.linked_issue == "TASK-1"
    assert before.human_summary == after.human_summary
    assert before.input_snapshot == after.input_snapshot
