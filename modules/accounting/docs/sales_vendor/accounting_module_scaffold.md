# Accounting Module Scaffold

## Why this module exists

Accounting behavior is currently spread across vendor, purchase, sales,
customer, inventory, expense, bank/payment, and reporting flows. This package
creates one future home for accounting calculations, posting rules, allocations,
validations, and ledger-derived reports.

## Problem it solves

Future accounting changes need a single façade so behavior can be
characterized, moved, tested, and corrected without changing unrelated UI or
workflow code.

## What it does not do yet

- It does not implement accounting logic.
- It does not change current runtime behavior.
- It does not add tables or migrations.
- It does not add UI screens or reports.
- It does not assume current scattered calculations are correct.

## Migration strategy

1. Add characterization tests for existing behavior before moving it.
2. Extract current behavior into `current_rules/` without changing outputs.
3. Route callers through `AccountingService` after tests prove parity.
4. Add ledger concepts only after source-document behavior is captured.
5. Correct accounting behavior with focused tests and explicit migration notes.

## Service rule

Future accounting-related calculations and posting operations should go through
`modules/accounting/service.py` or an approved accounting service API.
