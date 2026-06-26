"""Current purchase accounting behavior, preserved before cleanup."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    PurchaseInvoiceFinancials,
    PurchaseOutstanding,
    PurchaseFinancials,
    PurchasePaymentRow,
    PurchasePaymentStatus,
    PurchasePaymentSummary,
    PurchaseReturnEffect,
    PurchaseReturnInventoryPayload,
    PurchaseReturnPayload,
    PurchaseReturnPreviewPayload,
    PurchaseReturnResult,
    PurchaseReturnTotals,
    PurchaseReturnValue,
    PurchaseTotalInputLine,
    PurchaseTotals,
    SupplierRefundPayload,
    VendorAdvancePayload,
)
from .inventory_rules import (
    get_purchase_returnable_quantities,
    record_purchase_return_inventory_event,
)
from .vendor_rules import record_supplier_refund_event, record_vendor_advance_event


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def get_purchase_invoice_financials(
    conn: Connection,
    purchase_id: int | str,
) -> PurchaseInvoiceFinancials:
    # ACC-RULE-014: Purchase invoice financial context
    # Rebuilds purchase invoice totals, remaining due, and payment context.
    # Uses purchase header, items, vendor data, discounts, advances, and payments.
    # Supports invoice display without changing stored accounting state.
    row = conn.execute(
        """
        SELECT p.*, v.name AS vendor_name, v.contact_info AS vendor_contact_info,
               v.address AS vendor_address
        FROM purchases p
        JOIN vendors v ON p.vendor_id = v.vendor_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        return PurchaseInvoiceFinancials(purchase_id, {"purchase_id": purchase_id})

    doc = dict(row)
    vendor = {
        "name": doc.get("vendor_name", ""),
        "contact_info": doc.get("vendor_contact_info", ""),
        "address": doc.get("vendor_address", ""),
    }
    item_rows = conn.execute(
        """
        SELECT
            pi.item_id,
            pi.product_id,
            p.name AS product_name,
            pi.quantity,
            u.unit_name,
            u.unit_name AS uom_name,
            pi.purchase_price,
            pi.purchase_price AS unit_price,
            pi.sale_price,
            pi.item_discount,
            (pi.quantity * pi.purchase_price) AS line_total
        FROM purchase_items pi
        JOIN products p ON pi.product_id = p.product_id
        JOIN uoms u ON pi.uom_id = u.uom_id
        WHERE pi.purchase_id = ?
        ORDER BY pi.item_id
        """,
        (purchase_id,),
    ).fetchall()
    items = []
    for index, item_row in enumerate(item_rows, start=1):
        item = dict(item_row)
        item["uom_name"] = item.get("unit_name") or item.get("uom_name") or "N/A"
        item["idx"] = index
        items.append(item)

    subtotal = sum(float(item.get("line_total") or 0.0) for item in items)
    order_discount = float(doc.get("order_discount") or 0.0)
    total = max(0.0, subtotal - order_discount)
    paid_amount = float(doc.get("paid_amount") or 0.0)
    total_amount = float(doc.get("total_amount") or total)
    advance = float(doc.get("advance_payment_applied") or 0.0)

    payments = [
        dict(payment.__dict__)
        for payment in get_purchase_payment_history(conn, purchase_id)
    ]
    context = {
        "purchase_id": purchase_id,
        "doc": doc,
        "vendor": vendor,
        "items": items,
        "totals": {
            "subtotal_before_order_discount": subtotal,
            "line_discount_total": 0,
            "order_discount": order_discount,
            "total": total,
        },
        "paid_amount": paid_amount,
        "advance_payment_applied": advance,
        "remaining": max(0.0, total_amount - paid_amount - advance),
        "payments": payments,
        "initial_payment": payments[0] if payments else None,
    }
    doc["payment_status"] = doc.get("payment_status", "Unpaid")

    preview_context = dict(context)
    preview_context["totals"] = {
        "subtotal_before_order_discount": subtotal,
        "line_discount_total": 0,
        "order_discount": order_discount,
        "total": total,
    }
    latest = conn.execute(
        """
        SELECT
            pp.amount,
            pp.method,
            pp.date,
            pp.bank_account_id,
            pp.vendor_bank_account_id,
            pp.instrument_type,
            pp.instrument_no,
            pp.instrument_date,
            pp.deposited_date,
            pp.cleared_date,
            pp.ref_no,
            pp.notes,
            pp.clearing_state,
            ca.label AS bank_account_label,
            va.label AS vendor_bank_account_label
        FROM purchase_payments pp
        LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
        LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
        WHERE pp.purchase_id = ?
        ORDER BY pp.payment_id DESC
        LIMIT 1
        """,
        (purchase_id,),
    ).fetchone()
    preview_context["initial_payment"] = dict(latest) if latest else None

    return PurchaseInvoiceFinancials(purchase_id, context, preview_context)


def preview_purchase_total(
    items: tuple[PurchaseTotalInputLine, ...],
    order_discount: Decimal,
) -> PurchaseTotals:
    # ACC-RULE-015: Purchase total preview
    # Calculates subtotal after item discounts and clamps order discount at zero.
    # Produces a non-negative purchase net total without database writes.
    # Supports purchase entry previews before an order is saved.
    subtotal = sum(
        line.quantity * (line.purchase_price - line.item_discount) for line in items
    )
    order_discount = max(Decimal("0"), order_discount)
    net_total = max(Decimal("0"), subtotal - order_discount)
    return PurchaseTotals(
        purchase_id=None,
        subtotal_before_order_discount=subtotal,
        order_discount=order_discount,
        returned_value=Decimal("0"),
        net_total=net_total,
    )


def preview_purchase_return_effect(
    payload: PurchaseReturnPreviewPayload,
) -> PurchaseReturnEffect:
    # ACC-RULE-016: Purchase return value preview
    # Allocates order discount proportionally across returned purchase lines.
    # Calculates return quantities and values from purchase prices and discounts.
    # Supports return previews before inventory and settlement records are written.
    subtotal = sum(
        line.quantity * max(Decimal("0"), line.purchase_price - line.item_discount)
        for line in payload.lines
    )
    order_discount = max(Decimal("0"), payload.order_discount)
    if subtotal > Decimal("0"):
        order_discount = min(order_discount, subtotal)
        value_factor = (subtotal - order_discount) / subtotal
    else:
        value_factor = Decimal("0")
    line_values = tuple(
        max(
            Decimal("0"),
            line.return_qty
            * max(Decimal("0"), line.purchase_price - line.item_discount)
            * value_factor,
        )
        for line in payload.lines
    )
    return PurchaseReturnEffect(
        value_factor=value_factor,
        total_qty=sum((line.return_qty for line in payload.lines), Decimal("0")),
        total_value=sum(line_values, Decimal("0")),
        line_values=line_values,
    )


def get_purchase_financials(conn: Connection, purchase_id: int | str) -> PurchaseFinancials:
    # ACC-RULE-017: Purchase financial position
    # Calculates net total, paid amount, applied credit, returns, and refunds.
    # Uses purchase totals, cleared payments, return credits, and refund rows.
    # Supports payable decisions and remaining refundable amount checks.
    row = conn.execute(
        """
        SELECT
          p.total_amount,
          COALESCE(p.paid_amount, 0.0)              AS paid_amount,
          COALESCE(p.advance_payment_applied, 0.0)  AS advance_payment_applied,
          COALESCE((
            SELECT SUM(CAST(va.amount AS REAL))
            FROM vendor_advances va
            WHERE va.source_id = p.purchase_id
              AND va.source_type = 'return_credit'
          ), 0.0) AS return_credit_amount,
          COALESCE((
            SELECT SUM(CAST(prv.return_value AS REAL))
            FROM purchase_return_valuations prv
            WHERE prv.purchase_id = p.purchase_id
          ), 0.0) AS returned_value,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount,
          COALESCE((
            SELECT SUM(CAST(pr.amount AS REAL))
            FROM purchase_refunds pr
            WHERE pr.purchase_id = p.purchase_id
              AND pr.clearing_state = 'cleared'
          ), 0.0) AS prior_refunded_amount,
          COALESCE((
            SELECT SUM(CAST(pp.amount AS REAL))
            FROM purchase_payments pp
            WHERE pp.purchase_id = p.purchase_id
              AND pp.clearing_state = 'cleared'
          ), 0.0) AS cleared_direct_payments
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?;
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        return PurchaseFinancials(
            purchase_id=purchase_id,
            net_total=Decimal("0"),
            paid_amount=Decimal("0"),
            applied_credit=Decimal("0"),
            returned_value=Decimal("0"),
            refunded_amount=Decimal("0"),
            outstanding=Decimal("0"),
            clamped_outstanding=Decimal("0"),
        )
    calc = _decimal(row["calculated_total_amount"])
    paid = _decimal(row["paid_amount"])
    adv = _decimal(row["advance_payment_applied"])
    prior_refunded = _decimal(row["prior_refunded_amount"])
    cleared_direct = _decimal(row["cleared_direct_payments"])
    remaining_signed = calc - paid - adv
    remaining_clamped = max(Decimal("0"), remaining_signed)
    return PurchaseFinancials(
        purchase_id=purchase_id,
        net_total=calc,
        paid_amount=paid,
        applied_credit=adv,
        returned_value=_decimal(row["returned_value"]),
        refunded_amount=prior_refunded,
        outstanding=remaining_signed,
        clamped_outstanding=remaining_clamped,
        total_amount=_decimal(row["total_amount"]),
        return_credit_amount=_decimal(row["return_credit_amount"]),
        is_fully_paid=remaining_clamped <= Decimal("0.000000001"),
        remaining_refundable_amount=max(Decimal("0"), cleared_direct - prior_refunded),
    )


def get_purchase_return_values(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[PurchaseReturnValue, ...]:
    # ACC-RULE-018: Purchase return valuation rows
    # Reads stored valuation snapshots for each purchase return transaction.
    # Uses returned quantity, buy price, discount, status, and value data.
    # Supports return reports and settlement calculations.
    rows = conn.execute(
        """
        SELECT
          transaction_id,
          item_id,
          CAST(qty_returned  AS REAL) AS qty_returned,
          CAST(unit_buy_price AS REAL) AS unit_buy_price,
          CAST(unit_discount  AS REAL) AS unit_discount,
          return_date,
          valuation_status,
          CAST(return_value   AS REAL) AS return_value
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """,
        (purchase_id,),
    ).fetchall()
    return tuple(
        PurchaseReturnValue(
            transaction_id=int(row["transaction_id"]),
            item_id=row["item_id"],
            qty_returned=_decimal(row["qty_returned"]),
            unit_buy_price=_decimal(row["unit_buy_price"]),
            unit_discount=_decimal(row["unit_discount"]),
            return_date=row["return_date"],
            valuation_status=row["valuation_status"],
            return_value=_decimal(row["return_value"]),
        )
        for row in rows
    )


def get_purchase_return_totals(
    conn: Connection,
    purchase_id: int | str,
) -> PurchaseReturnTotals:
    # ACC-RULE-019: Purchase return totals
    # Sums returned quantities and values for a purchase.
    # Uses purchase return valuation rows as the accounting source.
    # Supports purchase financial summaries and return displays.
    values = get_purchase_return_values(conn, purchase_id)
    return PurchaseReturnTotals(
        qty=sum((value.qty_returned for value in values), Decimal("0")),
        value=sum((value.return_value for value in values), Decimal("0")),
    )


def record_purchase_return_event(
    conn: Connection,
    payload: PurchaseReturnPayload,
) -> PurchaseReturnResult:
    # ACC-RULE-020: Atomic purchase return event
    # Records purchase return inventory, valuation, settlement, and audit together.
    # Uses a savepoint so partial accounting state is rolled back on failure.
    # Protects purchase returns from half-posted inventory or payable records.
    savepoint = "purchase_return_record"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        result = _record_purchase_return_event(conn, payload)
        recalculate_purchase_payment_status(conn, payload.purchase_id)
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return result
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _record_purchase_return_event(
    conn: Connection,
    payload: PurchaseReturnPayload,
) -> PurchaseReturnResult:
    try:
        from ....database.repositories.inventory_repo import rebuild_dirty_valuations
    except ImportError:
        from database.repositories.inventory_repo import rebuild_dirty_valuations

    pid = payload.purchase_id
    lines = list(payload.lines)
    date = payload.date
    created_by = payload.created_by
    notes = payload.notes
    settlement = payload.settlement
    if not lines:
        return PurchaseReturnResult(pid, (), Decimal("0"), Decimal("0"))

    hdr = conn.execute("SELECT vendor_id FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    if not hdr:
        raise ValueError(f"Unknown purchase_id: {pid}")
    vendor_id = int(hdr["vendor_id"] if isinstance(hdr, sqlite3.Row) else hdr[0])

    mode = (settlement.get("mode") or "").lower() if settlement else ""
    if mode == "refund":
        mode = "refund_now"

    requested_per_item: dict[int, float] = {}
    for line in lines:
        item_id = int(line["item_id"])
        requested_per_item[item_id] = requested_per_item.get(item_id, 0.0) + float(
            line["qty_return"]
        )

    totals_row = conn.execute(
        """
        SELECT
          COALESCE(SUM(
            CAST(pi.quantity AS REAL) *
            MAX(0.0, CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL))
          ), 0.0) AS subtotal,
          COALESCE(CAST(p.order_discount AS REAL), 0.0) AS order_discount
        FROM purchases p
        LEFT JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        GROUP BY p.purchase_id
        """,
        (pid,),
    ).fetchone()
    purchase_subtotal = float(totals_row["subtotal"] or 0.0) if totals_row else 0.0
    order_discount = float(totals_row["order_discount"] or 0.0) if totals_row else 0.0
    effective_order_discount = min(max(0.0, order_discount), purchase_subtotal)
    return_value_factor = (
        (purchase_subtotal - effective_order_discount) / purchase_subtotal
        if purchase_subtotal > 0.0
        else 0.0
    )
    requested_return_value = 0.0
    returnable_by_item = get_purchase_returnable_quantities(conn, pid)

    for item_id, batch_qty in requested_per_item.items():
        # ACC-RULE-021: Purchase return quantity cap
        # Rejects return quantities above the item quantity still returnable.
        # Uses prior purchase return inventory transactions by purchase item.
        # Protects purchase returns from refunding the same item twice.
        row = conn.execute(
            """
            SELECT
              pi.product_id, pi.uom_id,
              CAST(pi.purchase_price AS REAL) AS purchase_price,
              CAST(pi.item_discount AS REAL) AS item_discount
            FROM purchase_items pi
            WHERE pi.item_id = ? AND pi.purchase_id = ?
            """,
            (item_id, pid),
        ).fetchone()
        if not row:
            raise ValueError(f"Invalid purchase item: {item_id} for purchase {pid}")

        remaining = float(returnable_by_item.get(item_id, Decimal("0")))
        if batch_qty > remaining + 1e-9:
            raise ValueError(
                f"Return qty exceeds remaining for item {item_id}: requested {batch_qty:g}, remaining {remaining:g}"
            )

        requested_return_value += batch_qty * return_value_factor * max(
            0.0,
            float(row["purchase_price"] or 0.0)
            - float(row["item_discount"] or 0.0),
        )

        product_id = int(row["product_id"])
        uom_id = int(row["uom_id"])
        # ACC-RULE-022: Purchase return stock cap
        # Rejects vendor returns that exceed current stock on hand.
        # Converts requested return quantity into base stock units.
        # Protects inventory valuation from negative stock caused by returns.
        factor_row = conn.execute(
            """
            SELECT COALESCE(CAST(factor_to_base AS REAL), 1.0) AS factor
            FROM product_uoms
            WHERE product_id=? AND uom_id=?
            """,
            (product_id, uom_id),
        ).fetchone()
        factor = float(factor_row["factor"] if factor_row else 1.0)
        return_qty_base = batch_qty * factor

        rebuild_dirty_valuations(conn, product_id)
        stock_row = conn.execute(
            "SELECT qty_in_base FROM v_stock_on_hand WHERE product_id=?",
            (product_id,),
        ).fetchone()
        on_hand = float(stock_row["qty_in_base"] if stock_row else 0.0)
        if return_qty_base > on_hand + 1e-9:
            raise ValueError(
                f"Cannot return {batch_qty:g} units for product {product_id}: "
                f"only {on_hand / factor:.2f} available in stock."
            )

    direct_paid = 0.0
    advance_applied = 0.0
    remaining_due = 0.0
    prior_refunds = 0.0
    prior_credit_notes = 0.0
    settlement_amount = 0.0
    prop_adv = 0.0

    if requested_return_value > 0:
        # ACC-RULE-023: Purchase return settlement amount
        # Calculates settlement from funded amount minus post-return total.
        # Uses cleared direct payments, applied advances, refunds, and credits.
        # Supports deciding whether return value becomes refund or vendor credit.
        position = conn.execute(
            """
            SELECT
              COALESCE(pdt.calculated_total_amount, p.total_amount, 0.0) AS net_total,
              COALESCE((
                SELECT SUM(CAST(pp.amount AS REAL))
                FROM purchase_payments pp
                WHERE pp.purchase_id = p.purchase_id
                  AND pp.clearing_state = 'cleared'
              ), 0.0) AS direct_paid,
              COALESCE(p.advance_payment_applied, 0.0) AS advance_applied,
              COALESCE((
                SELECT SUM(CAST(va.amount AS REAL))
                FROM vendor_advances va
                WHERE va.source_type = 'return_credit'
                  AND va.source_id = p.purchase_id
              ), 0.0) AS prior_credit_notes,
              COALESCE((
                SELECT SUM(CAST(pr.amount AS REAL))
                FROM purchase_refunds pr
                WHERE pr.purchase_id = p.purchase_id
                  AND pr.clearing_state = 'cleared'
              ), 0.0) AS prior_refunds
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt
              ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?
            """,
            (pid,),
        ).fetchone()
        if position:
            direct_paid = float(position["direct_paid"] or 0.0)
            advance_applied = float(position["advance_applied"] or 0.0)
            prior_credit_notes = float(position["prior_credit_notes"] or 0.0)
            prior_refunds = float(position["prior_refunds"] or 0.0)
            net_total_before = float(position["net_total"] or 0.0)

            funded_amount = direct_paid + advance_applied
            remaining_due = max(0.0, net_total_before - funded_amount)
            prior_settlement = prior_credit_notes + prior_refunds
            post_return_total = max(0.0, net_total_before - requested_return_value)
            settlement_amount = max(
                0.0,
                funded_amount - post_return_total - prior_settlement,
            )

            net_advance_applied = max(0.0, advance_applied - prior_credit_notes)
            if net_total_before > 1e-9:
                prop_adv = (requested_return_value / net_total_before) * advance_applied
                prop_adv = min(prop_adv, net_advance_applied)
            else:
                prop_adv = 0.0

        if settlement and mode == "refund_now":
            # ACC-RULE-024: Purchase refund-now eligibility
            # Allows immediate supplier refund only when purchase is fully settled.
            # Caps refund against direct cleared payments not already refunded.
            # Protects payable state from refunding unpaid or credited balances.
            if remaining_due > 1e-9:
                raise ValueError(
                    "Refund Now requires a fully settled purchase; "
                    f"remaining due is {remaining_due:.2f}."
                )
            refundable_direct_payment = max(0.0, direct_paid - prior_refunds)
            if settlement_amount > refundable_direct_payment + 1e-9:
                raise ValueError(
                    "Refund exceeds the remaining refundable direct payment "
                    f"of {refundable_direct_payment:.2f}."
                )

    inventory_result = record_purchase_return_inventory_event(
        conn,
        PurchaseReturnInventoryPayload(
            purchase_id=pid,
            date=date,
            created_by=created_by,
            lines=tuple(lines),
            notes=notes,
        ),
    )
    inserted_txn_ids = list(inventory_result.transaction_ids)

    if inserted_txn_ids:
        # ACC-RULE-025: Purchase return valuation snapshot required
        # Requires every return inventory transaction to have a valuation snapshot.
        # Uses purchase_return_snapshots for the new transaction ids.
        # Protects settlement math from missing return valuation data.
        placeholders = ",".join("?" for _ in inserted_txn_ids)
        val_row = conn.execute(
            f"""
            SELECT COUNT(*) AS snapshot_count,
                   COALESCE(SUM(CAST(return_value AS REAL)), 0.0) AS return_value
            FROM purchase_return_snapshots
            WHERE transaction_id IN ({placeholders})
            """,
            inserted_txn_ids,
        ).fetchone()
        snapshot_count = int(val_row["snapshot_count"] if val_row else 0)
        if snapshot_count != len(inserted_txn_ids):
            raise sqlite3.IntegrityError(
                "Purchase return valuation snapshot capture failed"
            )
        return_value = float(val_row["return_value"] if val_row else 0.0)
    else:
        return_value = 0.0

    if return_value > 0 and settlement_amount > 1e-9:
        # ACC-RULE-026: Purchase return settlement split
        # Splits settlement into supplier cash refund and vendor return credit.
        # Uses direct payment refunds first, then records remaining vendor credit.
        # Supports fully paid purchase returns and later credit application.
        mode = settlement.get("mode") if settlement else None
        if mode == "refund":
            mode = "refund_now"

        if mode == "refund_now":
            refundable_direct_payment = max(0.0, direct_paid - prior_refunds)
            cash_refund_amount = min(
                max(0.0, settlement_amount - prop_adv),
                refundable_direct_payment,
            )
            credit_amount = max(0.0, settlement_amount - cash_refund_amount)
        else:
            cash_refund_amount = 0.0
            credit_amount = settlement_amount

        if credit_amount > 1e-9:
            record_vendor_advance_event(
                conn,
                VendorAdvancePayload(
                    vendor_id=vendor_id,
                    amount=Decimal(str(credit_amount)),
                    date=date,
                    notes=settlement.get("notes") or notes if settlement else notes,
                    created_by=created_by,
                    source_id=pid,
                    source_type="return_credit",
                    method=settlement.get("method") if settlement else None,
                    bank_account_id=settlement.get("bank_account_id") if settlement else None,
                    vendor_bank_account_id=settlement.get("vendor_bank_account_id") if settlement else None,
                    instrument_type=settlement.get("instrument_type") if settlement else None,
                    instrument_no=settlement.get("instrument_no") if settlement else None,
                    instrument_date=settlement.get("instrument_date") if settlement else None,
                    deposited_date=settlement.get("deposited_date") if settlement else None,
                    cleared_date=settlement.get("cleared_date") if settlement else None,
                    clearing_state=settlement.get("clearing_state") if settlement else None,
                    ref_no=settlement.get("ref_no") if settlement else None,
                    temp_vendor_bank_name=settlement.get("temp_vendor_bank_name") if settlement else None,
                    temp_vendor_bank_number=settlement.get("temp_vendor_bank_number") if settlement else None,
                ),
            )

        if cash_refund_amount > 1e-9:
            record_supplier_refund_event(
                conn,
                SupplierRefundPayload(
                    purchase_id=pid,
                    vendor_id=vendor_id,
                    amount=Decimal(str(cash_refund_amount)),
                    date=settlement.get("date") or date if settlement else date,
                    method=settlement.get("method") or "Other" if settlement else "Other",
                    bank_account_id=settlement.get("bank_account_id") if settlement else None,
                    vendor_bank_account_id=settlement.get("vendor_bank_account_id") if settlement else None,
                    instrument_type=settlement.get("instrument_type") if settlement else None,
                    instrument_no=settlement.get("instrument_no") if settlement else None,
                    instrument_date=settlement.get("instrument_date") if settlement else None,
                    deposited_date=settlement.get("deposited_date") if settlement else None,
                    cleared_date=settlement.get("cleared_date") or date if settlement else date,
                    clearing_state="cleared",
                    ref_no=settlement.get("ref_no") if settlement else None,
                    temp_vendor_bank_name=settlement.get("temp_vendor_bank_name") if settlement else None,
                    temp_vendor_bank_number=settlement.get("temp_vendor_bank_number") if settlement else None,
                    notes=settlement.get("notes") or notes if settlement else notes,
                    created_by=created_by,
                ),
            )

    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            created_by,
            "return",
            "purchases",
            pid,
            f"Returned items with total value of {return_value:g}. "
            f"Settlement amount: {settlement_amount:g}. Lines: {len(lines)}",
        ),
    )
    return PurchaseReturnResult(
        purchase_id=pid,
        transaction_ids=tuple(inserted_txn_ids),
        return_value=Decimal(str(return_value)),
        settlement_amount=Decimal(str(settlement_amount)),
    )


def get_purchase_totals(conn: Connection, purchase_id: int | str) -> PurchaseTotals:
    # ACC-RULE-027: Stored purchase totals read
    # Reads purchase subtotal, order discount, returned value, and net total.
    # Uses detailed totals when present and purchase header as fallback.
    # Supports purchase screens that compare calculated and stored totals.
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          CAST(p.total_amount AS REAL) AS stored_total,
          COALESCE(CAST(pdt.order_discount AS REAL), CAST(p.order_discount AS REAL), 0.0)
            AS order_discount,
          COALESCE(CAST(pdt.subtotal_before_order_discount AS REAL), CAST(p.total_amount AS REAL), 0.0)
            AS subtotal_before_order_discount,
          COALESCE(CAST(pdt.calculated_total_amount AS REAL), CAST(p.total_amount AS REAL), 0.0)
            AS net_total,
          COALESCE((
            SELECT SUM(CAST(prv.return_value AS REAL))
            FROM purchase_return_valuations prv
            WHERE prv.purchase_id = p.purchase_id
          ), 0.0) AS returned_value
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")
    return PurchaseTotals(
        purchase_id=row["purchase_id"],
        subtotal_before_order_discount=_decimal(row["subtotal_before_order_discount"]),
        order_discount=_decimal(row["order_discount"]),
        returned_value=_decimal(row["returned_value"]),
        net_total=_decimal(row["net_total"]),
        stored_total=_decimal(row["stored_total"]),
    )


def get_purchase_outstanding(
    conn: Connection,
    purchase_id: int | str,
    *,
    clamp: bool = False,
) -> PurchaseOutstanding:
    # ACC-RULE-028: Purchase outstanding balance
    # Calculates purchase balance as total minus paid amount and applied advance.
    # Uses detailed total fallback and can clamp negative balances to zero.
    # Supports payables, headers, and open purchase lists.
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
          COALESCE(p.paid_amount, 0.0) AS paid_amount,
          COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")

    outstanding = (
        _decimal(row["total_calc"])
        - _decimal(row["paid_amount"])
        - _decimal(row["advance_payment_applied"])
    )
    if clamp:
        outstanding = max(Decimal("0"), outstanding)
    return PurchaseOutstanding(purchase_id=row["purchase_id"], outstanding=outstanding)


def get_purchase_payment_status(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentStatus:
    # ACC-RULE-029: Purchase payment status
    # Classifies purchase as paid, partial, or unpaid from cleared payments.
    # Uses purchase total, cleared direct payments, and applied vendor credit.
    # Supports payable state and payment status display.
    row = conn.execute(
        """
        SELECT
          p.purchase_id,
          COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
          COALESCE((
            SELECT SUM(CAST(amount AS REAL))
            FROM purchase_payments
            WHERE purchase_id = p.purchase_id
              AND COALESCE(clearing_state, 'posted') = 'cleared'
          ), 0.0) AS cleared_paid,
          COALESCE(p.advance_payment_applied, 0.0) AS advance_payment_applied
        FROM purchases p
        LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
        WHERE p.purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown purchase_id: {purchase_id}")

    paid = max(Decimal("0"), _decimal(row["cleared_paid"]))
    applied_credit = _decimal(row["advance_payment_applied"])
    remaining_due = _decimal(row["total_calc"]) - paid - applied_credit
    if remaining_due <= Decimal("0.000000001"):
        status = "paid"
    elif paid > Decimal("0.000000001") or applied_credit > Decimal("0.000000001"):
        status = "partial"
    else:
        status = "unpaid"
    return PurchasePaymentStatus(
        purchase_id=row["purchase_id"],
        status=status,
        paid_amount=paid,
        applied_credit=applied_credit,
        remaining_due=remaining_due,
    )


def recalculate_purchase_payment_status(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentStatus:
    # ACC-RULE-030: Persist purchase payment status
    # Recomputes purchase payment status and writes header paid/status fields.
    # Uses the purchase payment status rule as the source of truth.
    # Supports payment, credit, and return flows that alter payable state.
    status = get_purchase_payment_status(conn, purchase_id)
    conn.execute(
        "UPDATE purchases SET paid_amount = ?, payment_status = ? WHERE purchase_id = ?",
        (float(status.paid_amount), status.status, purchase_id),
    )
    return status


def _payment_row(row: object) -> PurchasePaymentRow:
    return PurchasePaymentRow(
        payment_id=int(row["payment_id"]),
        purchase_id=row["purchase_id"],
        date=row["date"],
        amount=_decimal(row["amount"]),
        method=row["method"],
        bank_account_id=row["bank_account_id"],
        vendor_bank_account_id=row["vendor_bank_account_id"],
        instrument_type=row["instrument_type"],
        instrument_no=row["instrument_no"],
        instrument_date=row["instrument_date"],
        deposited_date=row["deposited_date"],
        cleared_date=row["cleared_date"],
        clearing_state=row["clearing_state"],
        ref_no=row["ref_no"],
        notes=row["notes"],
        created_by=row["created_by"],
        bank_account_label=row["bank_account_label"],
        vendor_bank_account_label=row["vendor_bank_account_label"],
    )


def get_purchase_payment_history(
    conn: Connection,
    purchase_id: int | str,
) -> tuple[PurchasePaymentRow, ...]:
    rows = conn.execute(
        """
        SELECT
          pp.payment_id,
          pp.purchase_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.instrument_type,
          pp.instrument_no,
          pp.instrument_date,
          pp.deposited_date,
          pp.cleared_date,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.created_by,
          ca.label AS bank_account_label,
          va.label AS vendor_bank_account_label
        FROM purchase_payments pp
        LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
        LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
        WHERE pp.purchase_id = ?
        ORDER BY DATE(pp.date) ASC, pp.payment_id ASC
        """,
        (purchase_id,),
    ).fetchall()
    return tuple(_payment_row(row) for row in rows)


def get_purchase_payment_summary(
    conn: Connection,
    purchase_id: int | str,
) -> PurchasePaymentSummary:
    # ACC-RULE-031: Purchase payment summary
    # Combines payment status, latest payment, and overpayment credit.
    # Uses purchase payments and vendor advance credit conversion rows.
    # Supports purchase detail payment panels.
    status = get_purchase_payment_status(conn, purchase_id)
    latest = conn.execute(
        """
        SELECT
          pp.payment_id,
          pp.purchase_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.instrument_type,
          pp.instrument_no,
          pp.instrument_date,
          pp.deposited_date,
          pp.cleared_date,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.created_by,
          ca.label AS bank_account_label,
          va.label AS vendor_bank_account_label
        FROM purchase_payments pp
        LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
        LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
        WHERE pp.purchase_id = ?
        ORDER BY DATE(pp.date) DESC, pp.payment_id DESC
        LIMIT 1
        """,
        (purchase_id,),
    ).fetchone()
    overpayment = conn.execute(
        """
        SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS overpay
        FROM vendor_advances
        WHERE source_type='deposit'
          AND source_id=?
          AND notes LIKE 'Excess payment converted to vendor credit%'
        """,
        (purchase_id,),
    ).fetchone()
    return PurchasePaymentSummary(
        purchase_id=status.purchase_id,
        latest_payment=_payment_row(latest) if latest else None,
        paid_amount=status.paid_amount,
        applied_credit=status.applied_credit,
        remaining_due=status.remaining_due,
        status=status.status,
        overpayment_credited=_decimal(overpayment["overpay"] if overpayment else 0),
    )
