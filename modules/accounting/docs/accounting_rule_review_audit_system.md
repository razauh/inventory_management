# Accounting Rule Review Audit System

This is a pilot review layer. It records write-side accounting rule events after
the current business rule code succeeds. It does not replace the current rules
and it does not add ledger tables.

## Tables

- `accounting_rule_audit_events` stores append-only audit events.
- `accounting_rule_audit_reviews` stores reviewer status, notes, expected
  behavior, and linked issue references.

Audit events contain rule id, rule name, rule area, rule version, event type,
source reference, party reference, amount in PKR, compact JSON snapshots, side
effects, business date, human summary, technical summary, and source function.

Review rows are separate so the UI can change review state without editing audit
events.

## Rule Registry

The registry is loaded from `modules/accounting/docs/accounting_rule_index.md`.
Duplicate rows in the index are collapsed by rule id. The pilot expects 111
unique `ACC-RULE-*` ids.

## Logged Events

The pilot logs business writes through `AccountingService` wrappers:

- vendor payment, payment state update, advance, advance auto-apply, supplier refund
- purchase inventory posting and purchase return
- customer payment, payment state update, payment reopen
- customer credit and credit application
- quotation conversion
- sale inventory posting, sale return inventory posting, sale return settlement
- stock adjustment
- expense and expense category create, update, delete

Read-side accounting calls do not log audit events by default.

## UI Flow

The `Accounting Review` screen is visible in the main navigation for all users.
It supports filtering by date range, rule area, rule id/name, event type, status,
party, source type, and amount range.

The table shows created time, business date, rule, event type, source, party,
amount, summary, and status. The detail panel shows source, party, snapshots,
side effects, source references, status, notes, expected behavior, and linked
issue. Saving a review inserts a review row only.

CSV export uses the existing safe CSV escaping helper.

## Limits

This pilot is app-level append-only. It does not add database triggers to block
direct updates to audit rows. It uses the same SQLite connection as the business
write, so rollback removes the business write and its audit event together.

Future ledger work should keep double-entry invariants and source-document
traceability outside this pilot review layer.
