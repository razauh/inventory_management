# Accounting Rules Correction Log

## Purpose

This file is the required post-implementation log for accounting-rule correction cards in `modules/accounting/docs/accounting_rules_correction_task_cards.md`.

Use it to record what changed, what tests proved the change, and what unresolved follow-up remains after each correction card is implemented.

If older migration logs are mentioned elsewhere, treat them as background only. This file is the required correction log for these rule-fix cards.

## Rules

- Add one entry after every completed correction card.
- Use the exact card ID and problem ID in the entry heading.
- Record the focused tests that were added or updated before the production fix.
- State whether behavior changed intentionally.
- Call out data repair or backfill steps if any are needed.
- If the card was `Investigation First`, record the business-rule decision that unlocked the green step.
- Do not use this file as a brainstorming note. Record only implemented work or a clearly blocked investigation outcome.

## Entries

Copy this template for each completed card:

```markdown
## ACC-FIX-XXX: <short card title>

- Problem ID:
  - `ACC-PROB-XXX`
- Related rule IDs:
  - `<RULE-ID>`
- Card mode:
  - `Direct Fix` | `Investigation First`
- Tests added or updated:
  - `path::test_name`
- Production files changed:
  - `path`
- Behavior before:
  - <short fact>
- Behavior after:
  - <short fact>
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.
```


## ACC-FIX-010: Use real customer ID for repo overpayment conversion

- Problem ID:
  - `ACC-PROB-010`
- Related rule IDs:
  - `SAL-RULE-006`
  - `CUST-RULE-001`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_payment_event.py::test_sale_payments_repo_overpayment_uses_sale_customer_id`
  - `tests/accounting/test_customer_sales_payment_event.py::test_repo_overpayment_credit_posts_to_sale_customer`
- Production files changed:
  - `database/repositories/sale_payments_repo.py`
- Behavior before:
  - SalePaymentsRepo built CustomerPaymentPayload with customer_id=0, causing overpayment advances to be credited to customer 0.
- Behavior after:
  - SalePaymentsRepo queries the sales table for the real customer_id associated with the sale_id and passes it to the payment event payload.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

