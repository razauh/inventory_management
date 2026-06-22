"""Current inventory accounting behavior, preserved before cleanup."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    InventoryAccountingEvent,
    PurchaseInventoryPayload,
    PurchaseInventoryResult,
    PurchaseReturnInventoryPayload,
    PurchaseReturnInventoryResult,
)


def _rebuild_dirty_valuations(conn: Connection) -> None:
    try:
        from ....database.repositories.inventory_repo import rebuild_dirty_valuations
    except ImportError:
        from database.repositories.inventory_repo import rebuild_dirty_valuations

    rebuild_dirty_valuations(conn)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _delete_purchase_inventory_rows(
    conn: Connection,
    purchase_id: int | str,
    transaction_types: tuple[str, ...] | None,
) -> None:
    if transaction_types is None:
        conn.execute(
            """
            DELETE FROM inventory_transactions
             WHERE reference_table='purchases'
               AND reference_id=?
            """,
            (purchase_id,),
        )
        return

    if not transaction_types:
        return

    placeholders = ",".join("?" for _ in transaction_types)
    conn.execute(
        f"""
        DELETE FROM inventory_transactions
         WHERE reference_table='purchases'
           AND reference_id=?
           AND transaction_type IN ({placeholders})
        """,
        (purchase_id, *transaction_types),
    )


def record_purchase_inventory_event(
    conn: Connection,
    payload: PurchaseInventoryPayload,
) -> PurchaseInventoryResult:
    if payload.replace_existing:
        _delete_purchase_inventory_rows(
            conn,
            payload.purchase_id,
            payload.delete_transaction_types,
        )

    if not payload.lines:
        _rebuild_dirty_valuations(conn)
        return PurchaseInventoryResult(payload.purchase_id, ())

    row = conn.execute(
        "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
        (payload.date,),
    ).fetchone()
    next_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10

    transaction_ids: list[int] = []
    for line in payload.lines:
        cur = conn.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id,
                date, txn_seq, notes, created_by
            )
            VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?, ?, ?)
            """,
            (
                line.product_id,
                float(line.quantity),
                line.uom_id,
                payload.purchase_id,
                line.item_id,
                payload.date,
                next_seq,
                payload.notes,
                payload.created_by,
            ),
        )
        transaction_ids.append(int(cur.lastrowid))
        next_seq += 10

    _rebuild_dirty_valuations(conn)
    return PurchaseInventoryResult(payload.purchase_id, tuple(transaction_ids))


def record_purchase_return_inventory_event(
    conn: Connection,
    payload: PurchaseReturnInventoryPayload,
) -> PurchaseReturnInventoryResult:
    row = conn.execute(
        "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
        (payload.date,),
    ).fetchone()
    start_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10
    if start_seq < 100:
        start_seq = 100
    seq = start_seq

    transaction_ids: list[int] = []
    for line in payload.lines:
        chk = conn.execute(
            "SELECT product_id, uom_id FROM purchase_items WHERE item_id=? AND purchase_id=?",
            (line["item_id"], payload.purchase_id),
        ).fetchone()
        if not chk:
            raise ValueError(f"Purchase item mismatch for item_id {line['item_id']}")

        prod_id = int(chk["product_id"] if isinstance(chk, sqlite3.Row) else chk[0])
        uom_id = int(chk["uom_id"] if isinstance(chk, sqlite3.Row) else chk[1])
        cur = conn.execute(
            """
            INSERT INTO inventory_transactions(
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id,
                date, txn_seq, notes, created_by
            )
            VALUES (?, ?, ?, 'purchase_return', 'purchases', ?, ?, ?, ?, ?, ?)
            """,
            (
                prod_id,
                float(line["qty_return"]),
                uom_id,
                payload.purchase_id,
                int(line["item_id"]),
                payload.date,
                seq,
                payload.notes,
                payload.created_by,
            ),
        )
        transaction_ids.append(int(cur.lastrowid))
        seq += 10

    _rebuild_dirty_valuations(conn)
    return PurchaseReturnInventoryResult(payload.purchase_id, tuple(transaction_ids))


def get_purchase_returnable_quantities(
    conn: Connection,
    purchase_id: int | str,
) -> dict[int, Decimal]:
    rows = conn.execute(
        """
        SELECT
          pi.item_id,
          CAST(pi.quantity AS REAL) -
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='purchase_return'
              AND it.reference_table='purchases'
              AND it.reference_id = pi.purchase_id
              AND it.reference_item_id = pi.item_id
          ), 0.0) AS returnable
        FROM purchase_items pi
        WHERE pi.purchase_id=?
        """,
        (purchase_id,),
    ).fetchall()
    return {int(row["item_id"]): _decimal(row["returnable"]) for row in rows}


def get_inventory_accounting_events(
    conn: Connection,
    source_type: str | None = None,
    source_id: int | str | None = None,
) -> tuple[InventoryAccountingEvent, ...]:
    where: list[str] = []
    params: list[object] = []
    if source_type is not None:
        where.append("reference_table = ?")
        params.append(source_type)
    if source_id is not None:
        where.append("reference_id = ?")
        params.append(source_id)

    sql = """
        SELECT
          transaction_id,
          product_id,
          quantity,
          uom_id,
          transaction_type,
          reference_table,
          reference_id,
          reference_item_id,
          date,
          txn_seq,
          notes,
          created_by
        FROM inventory_transactions
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date, txn_seq, transaction_id"

    return tuple(
        InventoryAccountingEvent(
            transaction_id=int(row["transaction_id"]),
            product_id=int(row["product_id"]),
            quantity=_decimal(row["quantity"]),
            uom_id=row["uom_id"],
            transaction_type=row["transaction_type"],
            source_type=row["reference_table"],
            source_id=row["reference_id"],
            source_item_id=row["reference_item_id"],
            date=row["date"],
            txn_seq=row["txn_seq"],
            notes=row["notes"],
            created_by=row["created_by"],
        )
        for row in conn.execute(sql, params).fetchall()
    )
