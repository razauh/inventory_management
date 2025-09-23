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
from dataclasses import dataclass
from typing import Optional, List, Dict


class DomainError(Exception):
    """Domain-level error raised for validation issues."""
    pass


@dataclass
class ExpenseCategory:
    category_id: int | None
    name: str


@dataclass
class Expense:
    expense_id: int | None
    description: str
    amount: float
    date: str
    category_id: int | None
    category_name: str | None


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
        if not name or not name.strip():
            raise DomainError("Name cannot be empty.")
        name_n = name.strip()
        cur = self.conn.execute(
            "INSERT INTO expense_categories(name) VALUES (?)", (name_n,)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_category(self, category_id: int, name: str) -> None:
        """Update the name of an existing category."""
        if not name or not name.strip():
            raise DomainError("Name cannot be empty.")
        name_n = name.strip()
        self.conn.execute(
            "UPDATE expense_categories SET name=? WHERE category_id=?",
            (name_n, category_id),
        )
        self.conn.commit()

    def delete_category(self, category_id: int) -> None:
        """Remove a category. Translate FK violations into a domain error."""
        try:
            self.conn.execute(
                "DELETE FROM expense_categories WHERE category_id=?",
                (category_id,),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            # category is referenced by existing expenses
            raise DomainError(
                "Cannot delete a category that is used by existing expenses."
            ) from e

    # ------------------------------------------------------------------
    # Expense operations
    # ------------------------------------------------------------------

    def list_expenses(self, category_id: Optional[int] = None) -> List[Dict]:
        """
        List expenses, optionally filtering by category_id.

        Returns a list of dictionaries with keys:
          expense_id, description, amount, date, category_id, category_name
        Sorted by descending date then descending expense_id.
        """
        if category_id is not None:
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
        return [dict(r) for r in rows]

    def search_expenses(
        self,
        query: str = "",
        date: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> List[Dict]:
        """
        Search expenses by description, optional date and category.

        Performs a LIKE search on description.  Date filter uses DATE() to
        compare calendar days.  Category filter matches on exact ID.
        Returns matching rows ordered by date descending then expense_id.
        """
        where: List[str] = []
        params: List = []
        if query:
            where.append("e.description LIKE ?")
            params.append(f"%{query.strip()}%")
        if date:
            where.append("DATE(e.date) = DATE(?)")
            params.append(date)
        if category_id is not None:
            where.append("e.category_id = ?")
            params.append(category_id)
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
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY DATE(e.date) DESC, e.expense_id DESC"
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def search_expenses_adv(
        self,
        query: str = "",
        date_from: Optional[str] = None,   # 'YYYY-MM-DD'
        date_to: Optional[str] = None,     # 'YYYY-MM-DD'
        category_id: Optional[int] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
    ) -> List[Dict]:
        """
        Advanced search by description, date range, category, and amount range.

        - query: LIKE match on description (case-insensitive per collation)
        - date_from/date_to: inclusive range on calendar days using DATE()
        - category_id: exact match on category id
        - amount_min/amount_max: inclusive numeric range (cast to REAL)

        Returns rows ordered by date (DESC) then expense_id (DESC).
        """
        where: List[str] = []
        params: List = []

        if query:
            where.append("e.description LIKE ?")
            params.append(f"%{query.strip()}%")

        if date_from:
            where.append("DATE(e.date) >= DATE(?)")
            params.append(date_from)

        if date_to:
            where.append("DATE(e.date) <= DATE(?)")
            params.append(date_to)

        if category_id is not None:
            where.append("e.category_id = ?")
            params.append(category_id)

        if amount_min is not None:
            where.append("CAST(e.amount AS REAL) >= ?")
            params.append(float(amount_min))

        if amount_max is not None:
            where.append("CAST(e.amount AS REAL) <= ?")
            params.append(float(amount_max))

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
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY DATE(e.date) DESC, e.expense_id DESC"

        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

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
        if not description or not description.strip():
            raise DomainError("Description cannot be empty.")
        if amount is None or float(amount) < 0:
            raise DomainError("Amount must be non-negative.")
        desc_n = description.strip()
        cur = self.conn.execute(
            "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
            (desc_n, float(amount), date, category_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

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
        if not description or not description.strip():
            raise DomainError("Description cannot be empty.")
        if amount is None or float(amount) < 0:
            raise DomainError("Amount must be non-negative.")
        desc_n = description.strip()
        self.conn.execute(
            """
            UPDATE expenses
            SET description = ?, amount = ?, date = ?, category_id = ?
            WHERE expense_id = ?
            """,
            (desc_n, float(amount), date, category_id, expense_id),
        )
        self.conn.commit()

    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense by ID."""
        self.conn.execute(
            "DELETE FROM expenses WHERE expense_id = ?",
            (expense_id,),
        )
        self.conn.commit()

    def get_expense(self, expense_id: int) -> Dict | None:
        """
        Fetch a single expense by ID.  Returns None if not found.
        """
        row = self.conn.execute(
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
        return dict(row) if row else None

    def total_by_category(self) -> List[Dict]:
        """
        Compute the total amount spent in each category.

        Includes categories with no expenses (total = 0.0).  Returns a list
        ordered by category name with keys: category_id, category_name,
        total_amount.
        """
        rows = self.conn.execute(
            """
            SELECT c.category_id,
                   c.name AS category_name,
                   CAST(COALESCE(SUM(e.amount), 0) AS REAL) AS total_amount
            FROM expense_categories c
            LEFT JOIN expenses e ON e.category_id = c.category_id
            GROUP BY c.category_id
            ORDER BY c.name
            """
        ).fetchall()
        return [dict(r) for r in rows]
