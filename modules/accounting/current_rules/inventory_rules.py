"""Current inventory accounting behavior, preserved before cleanup."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from sqlite3 import Connection

from ..dto import (
    InventoryValue,
    InventoryAccountingEvent,
    PurchaseInventoryPayload,
    PurchaseInventoryResult,
    PurchaseReturnInventoryPayload,
    PurchaseReturnInventoryResult,
    SaleInventoryPayload,
    SaleInventoryResult,
    SaleReturnInventoryPayload,
    SaleReturnInventoryResult,
    StockAdjustmentPayload,
    StockAdjustmentResult,
)


def _rebuild_dirty_valuations(conn: Connection) -> None:
    try:
        from ....database.repositories.inventory_repo import rebuild_dirty_valuations
    except ImportError:
        from database.repositories.inventory_repo import rebuild_dirty_valuations

    rebuild_dirty_valuations(conn)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _cell(row: object, key: str, index: int) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (TypeError, KeyError, IndexError):
        return row[index]  # type: ignore[index]


def get_inventory_value(
    conn: Connection,
    product_id: int | None = None,
) -> InventoryValue | tuple[InventoryValue, ...]:
    _rebuild_dirty_valuations(conn)
    params: tuple[object, ...] = ()
    where = ""
    if product_id is not None:
        where = "WHERE p.product_id = ?"
        params = (int(product_id),)
    rows = conn.execute(
        f"""
        SELECT
          p.product_id,
          COALESCE(CAST(v.qty_in_base AS REAL), 0.0) AS quantity,
          COALESCE(CAST(v.unit_value AS REAL), 0.0) AS unit_value,
          COALESCE(CAST(v.total_value AS REAL), 0.0) AS total_value,
          (
            SELECT svh.valuation_date
            FROM stock_valuation_history svh
            WHERE svh.product_id = p.product_id
            ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
            LIMIT 1
          ) AS valuation_date
        FROM products p
        LEFT JOIN v_stock_on_hand v ON v.product_id = p.product_id
        {where}
        ORDER BY p.product_id
        """,
        params,
    ).fetchall()

    values = tuple(
        InventoryValue(
            product_id=int(_cell(row, "product_id", 0)),
            quantity=_decimal(_cell(row, "quantity", 1)),
            unit_value=_decimal(_cell(row, "unit_value", 2)),
            total_value=_decimal(_cell(row, "total_value", 3)),
            valuation_date=_cell(row, "valuation_date", 4),
        )
        for row in rows
    )
    if product_id is None:
        return values
    if values:
        return values[0]
    return InventoryValue(
        product_id=int(product_id),
        quantity=Decimal("0"),
        unit_value=Decimal("0"),
        total_value=Decimal("0"),
        valuation_date=None,
    )


def record_stock_adjustment_event(
    conn: Connection,
    payload: StockAdjustmentPayload,
) -> StockAdjustmentResult:
    try:
        from ....database.repositories.inventory_repo import (
            DomainError,
            next_inventory_txn_seq,
        )
    except ImportError:
        from database.repositories.inventory_repo import DomainError, next_inventory_txn_seq

    uom_row = conn.execute(
        """
        SELECT CAST(factor_to_base AS REAL) AS factor_to_base
        FROM product_uoms
        WHERE product_id=? AND uom_id=?
        LIMIT 1
        """,
        (int(payload.product_id), int(payload.uom_id)),
    ).fetchone()
    if not uom_row:
        raise DomainError(
            "Selected unit of measure does not belong to the chosen product. "
            "Please pick a valid UoM for this product."
        )

    qty = float(payload.quantity)
    if qty == 0.0:
        raise DomainError("Adjustment quantity must be non-zero.")

    if qty < 0.0:
        _rebuild_dirty_valuations(conn)
        factor_to_base = float(_cell(uom_row, "factor_to_base", 0) or 1.0)
        on_hand_row = conn.execute(
            """
            SELECT CAST(qty_in_base AS REAL) AS qty_in_base
            FROM v_stock_on_hand
            WHERE product_id = ?
            """,
            (int(payload.product_id),),
        ).fetchone()
        on_hand_base = (
            float(_cell(on_hand_row, "qty_in_base", 0) or 0.0)
            if on_hand_row
            else 0.0
        )
        reduction_base = abs(qty) * factor_to_base
        if reduction_base > on_hand_base + 1e-9:
            raise DomainError("Adjustment quantity exceeds available stock for this product.")

    cur = conn.execute(
        """
        INSERT INTO inventory_transactions
            (product_id, quantity, uom_id, transaction_type,
             reference_table, reference_id, reference_item_id,
             date, txn_seq, notes, created_by)
        VALUES
            (?, ?, ?, 'adjustment',
             NULL, NULL, NULL,
             ?, ?, ?, ?)
        """,
        (
            int(payload.product_id),
            qty,
            int(payload.uom_id),
            payload.date,
            next_inventory_txn_seq(conn, payload.date),
            payload.notes,
            payload.created_by,
        ),
    )
    _rebuild_dirty_valuations(conn)
    return StockAdjustmentResult(
        transaction_id=int(cur.lastrowid),
        product_id=int(payload.product_id),
    )


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
    *,
    stock_aware: bool = False,
) -> dict[int, Decimal]:
    rows = conn.execute(
        """
        SELECT
          pi.item_id,
          pi.product_id,
          pi.uom_id,
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

    res: dict[int, Decimal] = {}
    for row in rows:
        item_id = int(row["item_id"])
        product_id = int(row["product_id"])
        uom_id = int(row["uom_id"])
        returnable = _decimal(row["returnable"])

        if stock_aware:
            _rebuild_dirty_valuations(conn)
            stock_row = conn.execute(
                "SELECT qty_in_base FROM v_stock_on_hand WHERE product_id=?",
                (product_id,),
            ).fetchone()
            on_hand = float(stock_row["qty_in_base"] if stock_row else 0.0)

            factor_row = conn.execute(
                "SELECT COALESCE(CAST(factor_to_base AS REAL), 1.0) AS factor FROM product_uoms WHERE product_id=? AND uom_id=?",
                (product_id, uom_id),
            ).fetchone()
            factor = float(factor_row["factor"] if factor_row else 1.0)
            on_hand_in_uom = Decimal(str(on_hand / factor))

            returnable = max(Decimal("0"), min(returnable, on_hand_in_uom))

        res[item_id] = returnable
    return res


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


def record_sale_inventory_event(
    conn: Connection,
    payload: SaleInventoryPayload,
) -> SaleInventoryResult:
    row = conn.execute(
        "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
        (payload.date,),
    ).fetchone()
    next_seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10

    txn_ids: list[int] = []
    for line in payload.lines:
        cur = conn.execute(
            "INSERT INTO inventory_transactions(product_id, quantity, uom_id, transaction_type, "
            "reference_table, reference_id, reference_item_id, date, txn_seq, notes, created_by) "
            "VALUES (?, ?, ?, 'sale', 'sales', ?, ?, ?, ?, ?, ?)",
            (line.product_id, float(line.quantity), line.uom_id,
             payload.sale_id, line.item_id,
             payload.date, next_seq, payload.notes, payload.created_by),
        )
        txn_ids.append(int(cur.lastrowid))
        next_seq += 10

    _rebuild_dirty_valuations(conn)
    return SaleInventoryResult(payload.sale_id, tuple(txn_ids))


def record_sale_return_inventory_event(
    conn: Connection,
    payload: SaleReturnInventoryPayload,
) -> SaleReturnInventoryResult:
    row = conn.execute(
        "SELECT COALESCE(MAX(txn_seq), 0) AS max_seq FROM inventory_transactions WHERE date = ?",
        (payload.date,),
    ).fetchone()
    seq = int(row["max_seq"] if isinstance(row, sqlite3.Row) else row[0]) + 10
    if seq < 100:
        seq = 100

    txn_ids: list[int] = []
    for line in payload.lines:
        chk = conn.execute(
            "SELECT product_id, uom_id FROM sale_items WHERE item_id=? AND sale_id=?",
            (line.get("item_id"), payload.sale_id),
        ).fetchone()
        if not chk:
            raise ValueError(f"Sale item mismatch for item_id {line.get('item_id')}")
        pid = int(chk["product_id"] if isinstance(chk, sqlite3.Row) else chk[0])
        uid = int(chk["uom_id"] if isinstance(chk, sqlite3.Row) else chk[1])
        cur = conn.execute(
            "INSERT INTO inventory_transactions(product_id, quantity, uom_id, transaction_type, "
            "reference_table, reference_id, reference_item_id, date, txn_seq, notes, created_by) "
            "VALUES (?, ?, ?, 'sale_return', 'sales', ?, ?, ?, ?, ?, ?)",
            (pid, float(line["qty_return"]), uid,
             payload.sale_id, int(line["item_id"]),
             payload.date, seq, payload.notes, payload.created_by),
        )
        txn_ids.append(int(cur.lastrowid))
        seq += 10

    _rebuild_dirty_valuations(conn)
    return SaleReturnInventoryResult(payload.sale_id, tuple(txn_ids))


def get_sale_returnable_quantities(
    conn: Connection, sale_id: int | str
) -> dict[int, Decimal]:
    rows = conn.execute(
        """
        SELECT si.item_id, CAST(si.quantity AS REAL) -
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='sale_return'
              AND it.reference_table='sales'
              AND it.reference_id = si.sale_id
              AND it.reference_item_id = si.item_id
          ), 0.0) AS returnable
        FROM sale_items si
        WHERE si.sale_id = ?
        """,
        (sale_id,),
    ).fetchall()
    return {int(row["item_id"]): _decimal(row["returnable"]) for row in rows}
