"""Current extracted expense accounting behavior.

These rules mirror current code first. They are not assumed correct.
"""

from decimal import Decimal
import sqlite3
from typing import Optional, Any
from ..dto import ExpenseFinancialSummary, ExpenseCategoryTotal, ExpenseReportLine, ExpenseProfitLossSummary


def _build_where_clause(
    query: str = "",
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
) -> tuple[str, list]:
    where = []
    params = []
    if query:
        where.append("e.description LIKE ?")
        params.append(f"%{query.strip()}%")
    if date:
        where.append("DATE(e.date) = DATE(?)")
        params.append(date)
    if date_from:
        where.append("DATE(e.date) >= DATE(?)")
        params.append(date_from)
    if date_to:
        where.append("DATE(e.date) <= DATE(?)")
        params.append(date_to)
    if category_id is not None:
        if category_id == 0:
            where.append("e.category_id IS NULL")
        else:
            where.append("e.category_id = ?")
            params.append(category_id)
    if amount_min is not None:
        where.append("CAST(e.amount AS REAL) >= ?")
        params.append(float(amount_min))
    if amount_max is not None:
        where.append("CAST(e.amount AS REAL) <= ?")
        params.append(float(amount_max))
    return " AND ".join(where), params


def get_expense_financial_summary(
    conn: sqlite3.Connection,
    expense_id: int,
) -> Optional[ExpenseFinancialSummary]:
    row = conn.execute(
        """
        SELECT e.expense_id,
               e.description,
               CAST(e.amount AS REAL) AS amount,
               e.date,
               e.category_id,
               c.name AS category_name
        FROM expenses e
        LEFT JOIN expense_categories c ON c.category_id = e.category_id
        WHERE e.expense_id = ?
        """,
        (expense_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    return ExpenseFinancialSummary(
        expense_id=d["expense_id"],
        description=d["description"],
        amount=Decimal(str(d["amount"])) if d["amount"] is not None else Decimal("0.00"),
        date=d["date"],
        category_id=d["category_id"],
        category_name=d["category_name"],
    )


def list_expense_rows(
    conn: sqlite3.Connection,
    query: str = "",
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
) -> tuple[ExpenseFinancialSummary, ...]:
    where_str, params = _build_where_clause(
        query=query,
        date=date,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        amount_min=amount_min,
        amount_max=amount_max,
    )
    sql = """
        SELECT e.expense_id,
               e.description,
               CAST(e.amount AS REAL) AS amount,
               e.date,
               e.category_id,
               c.name AS category_name
        FROM expenses e
        LEFT JOIN expense_categories c ON c.category_id = e.category_id
    """
    if where_str:
        sql += " WHERE " + where_str
    sql += " ORDER BY DATE(e.date) DESC, e.expense_id DESC"

    rows = conn.execute(sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(
            ExpenseFinancialSummary(
                expense_id=d["expense_id"],
                description=d["description"],
                amount=Decimal(str(d["amount"])) if d["amount"] is not None else Decimal("0.00"),
                date=d["date"],
                category_id=d["category_id"],
                category_name=d["category_name"],
            )
        )
    return tuple(out)


def get_expense_screen_category_totals(
    conn: sqlite3.Connection,
    query: str = "",
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[int] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
) -> tuple[ExpenseCategoryTotal, ...]:
    where_str, params = _build_where_clause(
        query=query,
        date=date,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        amount_min=amount_min,
        amount_max=amount_max,
    )

    if where_str:
        on_clause = f" ON e.category_id = c.category_id AND {where_str} "
    else:
        on_clause = " ON e.category_id = c.category_id "

    sql_parts = []
    sql_parts.append(f"""
        SELECT c.category_id,
               c.name AS category_name,
               CAST(COALESCE(SUM(e.amount), 0) AS REAL) AS total_amount
        FROM expense_categories c
        LEFT JOIN expenses e {on_clause}
        GROUP BY c.category_id, c.name
    """)

    if category_id is None or category_id == 0:
        uncat_where_str, uncat_params = _build_where_clause(
            query=query,
            date=date,
            date_from=date_from,
            date_to=date_to,
            category_id=None,
            amount_min=amount_min,
            amount_max=amount_max,
        )
        if uncat_where_str:
            uncat_clause = f" e.category_id IS NULL AND {uncat_where_str} "
        else:
            uncat_clause = " e.category_id IS NULL "

        sql_parts.append(f"""
            UNION ALL

            SELECT 0 AS category_id,
                   '(Uncategorized)' AS category_name,
                   CAST(COALESCE(SUM(e.amount), 0) AS REAL) AS total_amount
            FROM expenses e
            WHERE {uncat_clause}
        """)
        exec_params = params + uncat_params
    else:
        exec_params = params

    full_sql = f"""
        SELECT category_id, category_name, total_amount
        FROM (
            {" ".join(sql_parts)}
        )
        ORDER BY category_name
    """

    rows = conn.execute(full_sql, tuple(exec_params)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(
            ExpenseCategoryTotal(
                category_id=d["category_id"],
                category_name=d["category_name"],
                total_amount=Decimal(str(d["total_amount"])) if d["total_amount"] is not None else Decimal("0.00"),
            )
        )
    return tuple(out)


def get_expense_report_category_totals(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    category_id: Optional[int],
) -> tuple[ExpenseCategoryTotal, ...]:
    if category_id is not None:
        if category_id == 0:
            sql = """
            SELECT
                0                                  AS category_id,
                '(Uncategorized)'                  AS category_name,
                SUM(CAST(e.amount AS REAL))        AS total_amount
            FROM expenses e
            WHERE e.category_id IS NULL
              AND e.date >= ?
              AND e.date <= ?
            GROUP BY e.category_id
            """
            params = [date_from, date_to]
        else:
            sql = """
            SELECT
                e.category_id                      AS category_id,
                ec.name                            AS category_name,
                SUM(CAST(e.amount AS REAL))        AS total_amount
            FROM expenses e
            JOIN expense_categories ec ON ec.category_id = e.category_id
            WHERE e.category_id = ?
              AND e.date >= ?
              AND e.date <= ?
            GROUP BY e.category_id, ec.name
            """
            params = [category_id, date_from, date_to]
    else:
        sql = """
        SELECT
            COALESCE(e.category_id, 0)          AS category_id,
            COALESCE(ec.name, '(Uncategorized)') AS category_name,
            SUM(CAST(e.amount AS REAL))        AS total_amount
        FROM expenses e
        LEFT JOIN expense_categories ec ON ec.category_id = e.category_id
        WHERE e.date >= ?
          AND e.date <= ?
        GROUP BY e.category_id, ec.name
        ORDER BY category_name COLLATE NOCASE
        """
        params = [date_from, date_to]

    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(
            ExpenseCategoryTotal(
                category_id=d["category_id"],
                category_name=d["category_name"],
                total_amount=Decimal(str(d["total_amount"])) if d["total_amount"] is not None else Decimal("0.00"),
            )
        )
    return tuple(out)


def get_expense_report_lines(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    category_id: Optional[int],
) -> tuple[ExpenseReportLine, ...]:
    params = [date_from, date_to]
    where_extra = ""
    if category_id is not None:
        if category_id == 0:
            where_extra = " AND e.category_id IS NULL "
        else:
            where_extra = " AND e.category_id = ? "
            params.append(category_id)

    sql = f"""
    SELECT
        e.expense_id                 AS expense_id,
        e.date                       AS date,
        COALESCE(ec.name, '(Uncategorized)') AS category_name,
        e.description                AS description,
        COALESCE(CAST(e.amount AS REAL), 0.0) AS amount
    FROM expenses e
    LEFT JOIN expense_categories ec ON ec.category_id = e.category_id
    WHERE e.date >= ?
      AND e.date <= ?
      {where_extra}
    ORDER BY e.date DESC, e.expense_id DESC
    """

    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(
            ExpenseReportLine(
                expense_id=d["expense_id"],
                date=d["date"],
                category_name=d["category_name"],
                description=d["description"] or "",
                amount=Decimal(str(d["amount"])) if d["amount"] is not None else Decimal("0.00"),
            )
        )
    return tuple(out)


def get_profit_loss_expense_summary(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> ExpenseProfitLossSummary:
    sql = """
    SELECT
      ec.category_id                     AS category_id,
      ec.name                            AS category_name,
      COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS total_amount
    FROM expense_categories ec
    LEFT JOIN expenses e
           ON e.category_id = ec.category_id
          AND e.date >= ? AND e.date <= ?
    GROUP BY ec.category_id, ec.name
    
    UNION ALL
    
    SELECT
      0                                  AS category_id,
      '(Uncategorized)'                  AS category_name,
      COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS total_amount
    FROM expenses e
    WHERE e.category_id IS NULL
      AND e.date >= ? AND e.date <= ?
    ORDER BY category_name COLLATE NOCASE
    """
    rows = conn.execute(sql, [date_from, date_to, date_from, date_to]).fetchall()
    expenses = []
    total_val = Decimal("0.00")
    for r in rows:
        d = dict(r)
        amt = Decimal(str(d["total_amount"])) if d["total_amount"] is not None else Decimal("0.00")
        total_val += amt
        expenses.append(
            ExpenseCategoryTotal(
                category_id=d["category_id"],
                category_name=d["category_name"],
                total_amount=amt,
            )
        )
    return ExpenseProfitLossSummary(
        expenses=tuple(expenses),
        total_expenses=total_val,
    )


def get_dashboard_expense_total(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> Decimal:
    sql = """
        SELECT COALESCE(SUM(CAST(e.amount AS REAL)), 0.0) AS v
        FROM expenses e
        WHERE e.date >= ? AND e.date <= ?
    """
    row = conn.execute(sql, (date_from, date_to)).fetchone()
    val = row["v"] if row else 0.0
    return Decimal(str(val)) if val is not None else Decimal("0.00")


def record_expense_create_event(
    conn: sqlite3.Connection,
    description: str,
    amount: float,
    date: str,
    category_id: int | None,
) -> int:
    from ..validators import validate_expense_input
    validate_expense_input(description, amount, date, category_id)

    was_in_transaction = conn.in_transaction
    desc_n = description.strip()
    cur = conn.execute(
        "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
        (desc_n, float(amount), date, category_id),
    )
    if not was_in_transaction:
        conn.commit()
    return int(cur.lastrowid)


def record_expense_update_event(
    conn: sqlite3.Connection,
    expense_id: int,
    description: str,
    amount: float,
    date: str,
    category_id: int | None,
) -> None:
    from ..validators import validate_expense_input
    validate_expense_input(description, amount, date, category_id)

    was_in_transaction = conn.in_transaction
    desc_n = description.strip()
    cur = conn.execute(
        """
        UPDATE expenses
        SET description = ?, amount = ?, date = ?, category_id = ?
        WHERE expense_id = ?
        """,
        (desc_n, float(amount), date, category_id, expense_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Expense with ID {expense_id} not found.")
    if not was_in_transaction:
        conn.commit()


def record_expense_delete_event(
    conn: sqlite3.Connection,
    expense_id: int,
) -> None:
    was_in_transaction = conn.in_transaction
    cur = conn.execute(
        "DELETE FROM expenses WHERE expense_id = ?",
        (expense_id,),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Expense with ID {expense_id} not found.")
    if not was_in_transaction:
        conn.commit()


def record_expense_category_create_event(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    from ..validators import validate_expense_category_input
    validate_expense_category_input(name)

    was_in_transaction = conn.in_transaction
    name_n = name.strip()
    cur = conn.execute(
        "INSERT INTO expense_categories(name) VALUES (?)",
        (name_n,),
    )
    if not was_in_transaction:
        conn.commit()
    return int(cur.lastrowid)


def record_expense_category_update_event(
    conn: sqlite3.Connection,
    category_id: int,
    name: str,
) -> None:
    from ..validators import validate_expense_category_input
    validate_expense_category_input(name)

    was_in_transaction = conn.in_transaction
    name_n = name.strip()
    cur = conn.execute(
        "UPDATE expense_categories SET name = ? WHERE category_id = ?",
        (name_n, category_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Category with ID {category_id} not found.")
    if not was_in_transaction:
        conn.commit()


def record_expense_category_delete_event(
    conn: sqlite3.Connection,
    category_id: int,
) -> None:
    was_in_transaction = conn.in_transaction
    try:
        cur = conn.execute(
            "DELETE FROM expense_categories WHERE category_id = ?",
            (category_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Category with ID {category_id} not found.")
        if not was_in_transaction:
            conn.commit()
    except sqlite3.IntegrityError as e:
        if not was_in_transaction:
            conn.rollback()
        raise ValueError(
            "Cannot delete a category that is used by existing expenses."
        ) from e
