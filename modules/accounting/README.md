# Accounting Module

This package is a scaffold for the future central accounting service.

It does not change current accounting behavior. Existing vendor, purchase,
sales, customer, inventory, expense, bank, and reporting code still owns the
runtime behavior until that logic is audited and moved here.

Future accounting work should enter through `AccountingService` first, then
delegate to current-rule adapters, ledger code, validators, or report builders.
