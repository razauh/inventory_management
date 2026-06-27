from decimal import Decimal
from datetime import date

from modules.accounting.audit.dto import AuditEventDraft
from modules.accounting.audit.repository import AccountingAuditRepository
from modules.accounting_review.controller import AccountingReviewController


def test_review_controller_saves_review_without_editing_event(conn, qapp):
    repo = AccountingAuditRepository(conn)
    event_id = repo.insert_event(
        AuditEventDraft(
            rule_id="ACC-RULE-102",
            event_type="expense_create",
            source_type="expense",
            source_id=1,
            amount=Decimal("9"),
            business_date=date.today().isoformat(),
            human_summary="Expense created.",
        )
    )
    controller = AccountingReviewController(conn, current_user={})
    controller.refresh()
    controller.view.table.selectRow(0)

    controller.save_review("unclear", "Need invoice.", "Should match receipt.", "TASK-2")

    row = repo.get_event(event_id)
    assert row.review_status == "unclear"
    assert row.review_notes == "Need invoice."
    assert row.human_summary == "Expense created."
