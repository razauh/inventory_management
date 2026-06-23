from __future__ import annotations

"""
Repository for expenses and expense categories.

This module exposes a simple API to manage expense categories and individual
expenses.  It mirrors the style used by other repositories in this project
(e.g. `CustomersRepo`, `SalesRepo`) by performing basic validation and
normalization before writing to the database.  All monetary amounts are
stored and returned as `float` for convenience, but underlying storage is
numeric to preserve precision.

Schema reference (see `database/schema.py`):

CREATE TABLE expense_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL
);

CREATE TABLE expenses (
    expense_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT   NOT NULL,
    amount      NUMERIC NOT NULL CHECK (CAST(amount AS REAL) >= 0),
    date        DATE    NOT NULL DEFAULT CURRENT_DATE,
    category_id INTEGER,
    FOREIGN KEY (category_id) REFERENCES expense_categories(category_id)
);

The repository does not enforce complex business rules beyond ensuring
non-empty descriptions and non-negative amounts.  Consumers (e.g. UI
controllers) should handle any additional logic (such as preventing
deletion of categories that are still referenced).
"""

import sqlite3
import math
from datetime import date as py_date
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


class DomainError(Exception):
    """Domain-level error raised for validation issues."""
    pass


@dataclass
class ExpenseCategory:
    category_id: int | None
    name: str

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class Expense:
    expense_id: int | None
    description: str
    amount: float
    date: str
    category_id: int | None
    category_name: str | None

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class ExpensesRepo:
    """
    Repository for CRUD operations on expense categories and expenses.

    The repository accepts a `sqlite3.Connection` in its constructor and
    persists changes immediately (auto-commit behaviour) after write
    operations.  It exposes high-level methods for listing, searching,
    creating, updating and deleting both categories and expenses, as well
    as computing simple aggregates (e.g. total spent per category).
    """

    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn

    # ------------------------------------------------------------------
    # Category operations
    # ------------------------------------------------------------------

    def list_categories(self) -> List[ExpenseCategory]:
        """Return all expense categories ordered by name."""
        rows = self.conn.execute(
            "SELECT category_id, name FROM expense_categories ORDER BY name"
        ).fetchall()
        return [ExpenseCategory(**dict(r)) for r in rows]

    def create_category(self, name: str) -> int:
        """
        Insert a new expense category.

        Raises DomainError if the name is blank.  If the name already exists
        a UNIQUE constraint violation will be raised by SQLite.
        Returns the new category_id.
        """
        from modules.accounting.service import AccountingService
        try:
            return AccountingService(self.conn).record_expense_category_create_event(name)
        except ValueError as e:
            raise DomainError(str(e))

    def update_category(self, category_id: int, name: str) -> None:
        """Update the name of an existing category."""
        from modules.accounting.service import AccountingService
        try:
            AccountingService(self.conn).record_expense_category_update_event(category_id, name)
        except ValueError as e:
            raise DomainError(str(e))

    def delete_category(self, category_id: int) -> None:
        """Remove a category. Translate FK violations into a domain error."""
        from modules.accounting.service import AccountingService
        try:
            AccountingService(self.conn).record_expense_category_delete_event(category_id)
        except ValueError as e:
            raise DomainError(str(e))

    # ------------------------------------------------------------------
    # Expense operations
    # ------------------------------------------------------------------

    def _build_where_clause(
        self,
        query: str = "",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category_id: Optional[int] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
    ) -> tuple[str, list]:
        where: List[str] = []
        params: List = []
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

    def list_expenses(self, category_id: Optional[int] = None) -> List[Expense]:
        """
        List expenses, optionally filtering by category_id.

        Returns a list of Expense objects.
        Sorted by descending date then descending expense_id.
        """
        if category_id is not None:
            if category_id == 0:
                rows = self.conn.execute(
                    """
                    SELECT e.expense_id,
                           e.description,
                           CAST(e.amount AS REAL) AS amount,
                           e.date,
                           e.category_id,
                           NULL AS category_name
                    FROM expenses e
                    WHERE e.category_id IS NULL
                    ORDER BY DATE(e.date) DESC, e.expense_id DESC
                    """
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT e.expense_id,
                           e.description,
                           CAST(e.amount AS REAL) AS amount,
                           e.date,
                           e.category_id,
                           c.name AS category_name
                    FROM expenses e
                    LEFT JOIN expense_categories c ON c.category_id = e.category_id
                    WHERE e.category_id = ?
                    ORDER BY DATE(e.date) DESC, e.expense_id DESC
                    """,
                    (category_id,),
                ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT e.expense_id,
                       e.description,
                       CAST(e.amount AS REAL) AS amount,
                       e.date,
                       e.category_id,
                       c.name AS category_name
                FROM expenses e
                LEFT JOIN expense_categories c ON c.category_id = e.category_id
                ORDER BY DATE(e.date) DESC, e.expense_id DESC
                """
            ).fetchall()
        return [Expense(**dict(r)) for r in rows]

    def search_expenses(
        self,
        query: str = "",
        date: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> List[Expense]:
        """
        Search expenses by description, optional date and category.

        Performs a LIKE search on description.  Date filter uses DATE() to
        compare calendar days.  Category filter matches on exact ID.
        Returns matching rows as Expense objects ordered by date descending then expense_id.
        """
        where_str, params = self._build_where_clause(
            query=query, date=date, category_id=category_id
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
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [Expense(**dict(r)) for r in rows]

    def search_expenses_adv(
        self,
        query: str = "",
        date: Optional[str] = None,
        date_from: Optional[str] = None,   # 'YYYY-MM-DD'
        date_to: Optional[str] = None,     # 'YYYY-MM-DD'
        category_id: Optional[int] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
    ) -> List[Expense]:
        """
        Advanced search by description, optional date, date range, category, and amount range.

        - query: LIKE match on description (case-insensitive per collation)
        - date: exact match on calendar day using DATE()
        - date_from/date_to: inclusive range on calendar days using DATE()
        - category_id: exact match on category id
        - amount_min/amount_max: inclusive numeric range (cast to REAL)

        Returns rows ordered by date (DESC) then expense_id (DESC).
        """
        from modules.accounting.service import AccountingService
        rows = AccountingService(self.conn).list_expense_rows(
            query=query,
            date=date,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            amount_min=amount_min,
            amount_max=amount_max,
        )
        return [
            Expense(
                expense_id=r.expense_id,
                description=r.description,
                amount=float(r.amount),
                date=r.date,
                category_id=r.category_id,
                category_name=r.category_name,
            )
            for r in rows
        ]

    def create_expense(
        self,
        description: str,
        amount: float,
        date: str,
        category_id: Optional[int],
    ) -> int:
        """
        Insert a new expense.

        `description` must be non-empty and `amount` must be non-negative.
        `date` should be a valid ISO date string (enforced by SQLite only on
        DATE() functions).  `category_id` may be None.
        Returns the newly inserted expense_id.
        """
        from modules.accounting.service import AccountingService
        try:
            return AccountingService(self.conn).record_expense_create_event(
                description=description,
                amount=amount,
                date=date,
                category_id=category_id,
            )
        except ValueError as e:
            raise DomainError(str(e))

    def update_expense(
        self,
        expense_id: int,
        description: str,
        amount: float,
        date: str,
        category_id: Optional[int],
    ) -> None:
        """
        Update an existing expense.

        Same validation rules as `create_expense` apply.
        """
        from modules.accounting.service import AccountingService
        try:
            AccountingService(self.conn).record_expense_update_event(
                expense_id=expense_id,
                description=description,
                amount=amount,
                date=date,
                category_id=category_id,
            )
        except ValueError as e:
            raise DomainError(str(e))

    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense by ID."""
        from modules.accounting.service import AccountingService
        try:
            AccountingService(self.conn).record_expense_delete_event(expense_id)
        except ValueError as e:
            raise DomainError(str(e))

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """
        Fetch a single expense by ID.  Returns None if not found.
        """
        from modules.accounting.service import AccountingService
        summary = AccountingService(self.conn).get_expense_financial_summary(expense_id)
        if not summary:
            return None
        return Expense(
            expense_id=summary.expense_id,
            description=summary.description,
            amount=float(summary.amount),
            date=summary.date,
            category_id=summary.category_id,
            category_name=summary.category_name,
        )

    def total_by_category(
        self,
        query: str = "",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category_id: Optional[int] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
    ) -> List[Dict]:
        """
        Compute the total amount spent in each category.

        Includes categories with no expenses (total = 0.0).  Returns a list
        ordered by category name with keys: category_id, category_name,
        total_amount.
        """
        from modules.accounting.service import AccountingService
        totals = AccountingService(self.conn).get_expense_screen_category_totals(
            query=query,
            date=date,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            amount_min=amount_min,
            amount_max=amount_max,
        )
        return [
            {
                "category_id": t.category_id,
                "category_name": t.category_name,
                "total_amount": float(t.total_amount),
            }
            for t in totals
        ]
