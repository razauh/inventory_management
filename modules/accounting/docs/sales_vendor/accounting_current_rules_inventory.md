# Accounting Current Rules Inventory

Use this file later to audit current accounting behavior. Do not treat listed
behavior as correct until it is verified.

## Vendor rules

- Vendor advance balances are signed from `vendor_advances` and exposed through
  `AccountingService.get_vendor_advance_balance(s)`.
- Vendor open purchases and statements are compatibility read models over
  current purchase/payment/advance tables.
- Vendor credit application still relies on schema constraints for final
  integrity and service validation for metadata.

## Customer rules

## Purchase rules

- Purchase totals use current item subtotal, per-item discount, order discount,
  and return valuations. These are exposed through `get_purchase_totals`.
- Purchase payment status and outstanding amounts are service-owned wrappers
  around the existing cleared-payment and applied-credit behavior.
- Purchase payment history, summaries, and invoice financial context are service
  read models. The purchase invoice preview intentionally preserves the legacy
  fallback that shows order discount as zero.

## Sales rules

## Inventory rules

- Purchase inventory rows and purchase-return inventory rows are written by
  `AccountingService` current inventory rules.
- Returnable quantity reads are service-owned. Return snapshot triggers remain
  schema-owned and are not removed.

## Bank/cash rules

- Vendor cash movements, bank ledger rows, AP summary, vendor aging, and payment
  activity are service read models over existing report SQL.
- Supplier refunds are netted in disbursement reports using current
  `purchase_disbursements_by_day` behavior.

## Expense rules

## Returns/refunds

- Purchase return valuation preview, stored return values, return totals, and
  return write/settlement behavior are service-owned.
- Supplier refund event writes are service-owned. Existing triggers and views
  remain the durability layer for snapshots and payment status updates.

## Advances/credits

- Vendor advance grant and credit application use service entry points.
- Repository methods that remain public are compatibility wrappers and should
  not own separate balance, payable, or credit math.

## Known inconsistencies

- Purchase invoice preview and printed invoice still use different discount
  fallbacks by design. This is preserved, not corrected.
- Reporting modules still keep some filtered SQL branches for row-shape and UI
  compatibility. New Vendor + Purchase financial report reads should enter
  through `AccountingService` first.
- Schema triggers/views remain source-of-truth for several invariants. Do not
  delete them during service cleanup.
- No double-entry ledger has been introduced yet. Current rules mirror app
  behavior, not final accounting correctness.

## Files/functions to inspect

- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/reports/ar_ap_summary.py`
- `modules/accounting/reports/party_ledger.py`
- `database/repositories/purchases_repo.py` compatibility wrappers
- `database/repositories/purchase_payments_repo.py` compatibility wrappers
- `database/repositories/vendor_advances_repo.py` compatibility wrappers
- `modules/purchase/controller.py` invoice/payment/return service calls
- `modules/reporting/*` report service entry points and legacy filtered SQL
