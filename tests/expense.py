# tests/test_expense_module_all.py
# Combined from:
# - tests/test_expenses_repo.py
# - tests/test_expense_models.py
# - tests/test_expense_view.py
# - tests/test_expense_form.py
# - tests/test_expense_controller.py

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # safe for headless CI

import sqlite3
from typing import Any, List, Dict, Optional

import pytest

# ========================= Repo tests (original: tests/test_expenses_repo.py) =========================

# Import the repo + error exactly as specified
from inventory_management.database.repositories.expenses_repo import (
    ExpensesRepo,
    DomainError,
)

# --- Minimal schema exactly as documented (no extras) ---
SCHEMA = """
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
"""

def make_conn() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    # foreign_keys pragma is unspecified in the description, so we do not enforce it.
    con.executescript(SCHEMA)
    return con

# ---------- Category tests ----------

def test_list_categories_empty():
    con = make_conn()
    repo = ExpensesRepo(con)
    assert repo.list_categories() == []  # ordered by name, empty OK

def test_create_category_rejects_blank_name():
    con = make_conn()
    repo = ExpensesRepo(con)
    with pytest.raises(DomainError):  # per spec: blank → DomainError
        repo.create_category("  ")

def test_create_category_then_list_is_ordered_by_name():
    con = make_conn()
    repo = ExpensesRepo(con)
    a = repo.create_category("Travel")
    b = repo.create_category("Meals")
    # list is ORDER BY name, so Meals comes before Travel
    cats = repo.list_categories()
    assert [c.name for c in cats] == ["Meals", "Travel"]
    assert sorted([c.category_id for c in cats]) == sorted([a, b])

def test_create_category_duplicate_raises_unique_violation():
    con = make_conn()
    repo = ExpensesRepo(con)
    repo.create_category("Utilities")
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_category("Utilities")  # spec: UNIQUE violation raised by SQLite

def test_update_category_validation_and_effect():
    con = make_conn()
    repo = ExpensesRepo(con)
    cid = repo.create_category("Misc")
    with pytest.raises(DomainError):
        repo.update_category(cid, "  ")
    repo.update_category(cid, "Miscellaneous")
    out = repo.list_categories()
    assert any(c.category_id == cid and c.name == "Miscellaneous" for c in out)

def test_delete_category_removes_row_without_extra_checks():
    con = make_conn()
    repo = ExpensesRepo(con)
    cid = repo.create_category("Temp")
    # No additional business rules enforced by repo; just delete
    con.execute("DELETE FROM expense_categories WHERE category_id=?", (cid,))
    con.commit()
    assert [c.category_id for c in repo.list_categories()] == []

# ---------- Expense tests ----------

def _seed_expenses(con: sqlite3.Connection):
    con.execute("INSERT INTO expense_categories(name) VALUES (?)", ("Meals",))
    con.execute("INSERT INTO expense_categories(name) VALUES (?)", ("Travel",))
    c_meals = con.execute("SELECT category_id FROM expense_categories WHERE name='Meals'").fetchone()[0]
    c_travel = con.execute("SELECT category_id FROM expense_categories WHERE name='Travel'").fetchone()[0]
    con.execute(
        "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
        ("Lunch with client", 150.0, "2025-01-10", c_meals),
    )
    con.execute(
        "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
        ("Taxi to airport",  900.0, "2025-01-11", c_travel),
    )
    con.execute(
        "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
        ("Coffee",  250.0, "2025-01-11", c_meals),
    )
    con.commit()
    return c_meals, c_travel

def test_create_expense_validations():
    con = make_conn()
    repo = ExpensesRepo(con)
    with pytest.raises(DomainError):
        repo.create_expense("", 10, "2025-01-01", None)
    with pytest.raises(DomainError):
        repo.create_expense("ok", -1, "2025-01-01", None)
    eid = repo.create_expense("ok", 0, "2025-01-01", None)
    row = con.execute("SELECT * FROM expenses WHERE expense_id=?", (eid,)).fetchone()
    assert row["description"] == "ok" and float(row["amount"]) == 0.0 and row["date"] == "2025-01-01"

def test_update_expense_validations_and_effect():
    con = make_conn()
    repo = ExpensesRepo(con)
    eid = repo.create_expense("init", 10, "2025-02-01", None)
    with pytest.raises(DomainError):
        repo.update_expense(eid, "  ", 10, "2025-02-01", None)
    with pytest.raises(DomainError):
        repo.update_expense(eid, "x", -0.01, "2025-02-01", None)
    repo.update_expense(eid, "new", 12.5, "2025-02-02", None)
    r = con.execute("SELECT * FROM expenses WHERE expense_id=?", (eid,)).fetchone()
    assert r["description"] == "new" and float(r["amount"]) == 12.5 and r["date"] == "2025-02-02"

def test_delete_expense_removes_row():
    con = make_conn()
    repo = ExpensesRepo(con)
    eid = repo.create_expense("to delete", 5, "2025-01-01", None)
    repo.delete_expense(eid)
    assert con.execute("SELECT COUNT(*) FROM expenses WHERE expense_id=?", (eid,)).fetchone()[0] == 0

def test_list_expenses_ordering_and_join():
    con = make_conn()
    repo = ExpensesRepo(con)
    _seed_expenses(con)
    rows = repo.search_expenses("")  # same ORDER as list: date DESC, id DESC
    # Expect 2025-01-11 entries first (highest expense_id first), then 2025-01-10
    assert [r["date"] for r in rows] == ["2025-01-11", "2025-01-11", "2025-01-10"]
    # category_name joined correctly
    assert set(r["category_name"] for r in rows) == {"Meals", "Travel"}

def test_search_expenses_filters_query_date_category():
    con = make_conn()
    repo = ExpensesRepo(con)
    c_meals, c_travel = _seed_expenses(con)
    # Description LIKE
    res = repo.search_expenses("Coffee")
    assert len(res) == 1 and res[0]["description"] == "Coffee"
    # Date equality (DATE() comparison)
    res = repo.search_expenses("", date="2025-01-10")
    assert len(res) == 1 and res[0]["description"] == "Lunch with client"
    # Category filter exact ID
    res = repo.search_expenses("", category_id=c_travel)
    assert len(res) == 1 and res[0]["category_name"] == "Travel"

# ========================= Model tests (original: tests/test_expense_models.py) =========================

from PySide6.QtCore import Qt, QModelIndex  # noqa: E402
from inventory_management.modules.expense.model import (  # noqa: E402
    ExpenseCategoriesModel,
    ExpensesTableModel,
)
from inventory_management.utils.helpers import fmt_money  # noqa: E402

def test_expense_categories_model_basics():
    rows = [{"category_id": 1, "name": "Meals"}, {"category_id": 2, "name": "Travel"}]
    m = ExpenseCategoriesModel(rows)
    assert m.rowCount() == 2 and m.columnCount() == 2
    # headers
    assert m.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "ID"
    assert m.headerData(1, Qt.Horizontal, Qt.DisplayRole) == "Name"
    # data mapping
    idx0 = m.index(0, 0)
    idx1 = m.index(0, 1)
    assert m.data(idx0, Qt.DisplayRole) == 1
    assert m.data(idx1, Qt.DisplayRole) == "Meals"

def test_expenses_table_model_formatting_and_mapping():
    rows = [{
        "expense_id": 5,
        "date": "2025-01-11",
        "category_name": None,  # should render as ""
        "description": "Coffee",
        "amount": 250.0
    }]
    m = ExpensesTableModel(rows)
    assert m.HEADERS == ["ID", "Date", "Category", "Description", "Amount"]
    assert m.rowCount() == 1 and m.columnCount() == 5
    idxs = [m.index(0, c) for c in range(5)]
    assert [m.data(i, Qt.DisplayRole) for i in idxs[:4]] == [5, "2025-01-11", "", "Coffee"]
    # Amount formatted by fmt_money
    assert m.data(idxs[4], Qt.DisplayRole) == fmt_money(250.0)

# Citations for model behavior: headers & mapping in ExpensesTableModel and ExpenseCategoriesModel ; fmt_money formatting .

# ========================= View tests (original: tests/test_expense_view.py) =========================

from PySide6.QtWidgets import QApplication  # noqa: E402
from inventory_management.modules.expense.view import ExpenseView  # noqa: E402

def _qapp():
    app = QApplication.instance()
    return app or QApplication([])

def test_expense_view_widgets_and_defaults():
    _qapp()
    v = ExpenseView()
    # widgets exist
    assert hasattr(v, "txt_search") and hasattr(v, "date_filter") and hasattr(v, "cmb_category")
    assert hasattr(v, "btn_add") and hasattr(v, "btn_edit") and hasattr(v, "btn_delete")
    assert hasattr(v, "tbl_expenses")
    # defaults / convenience props
    assert v.search_text == ""
    # date was set then cleared in constructor ⇒ property should return None when empty
    assert v.selected_date is None
    # no categories yet ⇒ currentData is None
    assert v.selected_category_id is None

# Citations for view structure and convenience properties: .

# ========================= Form tests (original: tests/test_expense_form.py) =========================

from PySide6.QtCore import QDate  # noqa: E402
from inventory_management.modules.expense.form import ExpenseForm  # noqa: E402

def test_expense_form_validation_and_payload_roundtrip():
    _qapp()
    cats = [(1, "Meals"), (2, "Travel")]
    dlg = ExpenseForm(None, categories=cats, initial=None)

    # invalid: empty description
    dlg.edt_description.setText("   ")
    dlg.spin_amount.setValue(100.0)
    dlg.date_edit.setDate(QDate.fromString("2025-01-15", "yyyy-MM-dd"))
    dlg.cmb_category.setCurrentIndex(1)  # "(None)" is index 0, so 1 => cat id 1
    assert dlg.get_payload() is None  # invalid description

    # invalid: negative amount
    dlg.edt_description.setText("Taxi")
    dlg.spin_amount.setValue(-1.0)
    assert dlg.get_payload() is None

    # valid payload
    dlg.spin_amount.setValue(900.0)
    dlg.date_edit.setDate(QDate.fromString("2025-01-15", "yyyy-MM-dd"))
    payload = dlg.get_payload()
    assert payload == {
        "expense_id": None,
        "description": "Taxi",
        "amount": 900.0,
        "date": "2025-01-15",
        "category_id": 1,
    }

    # accept should stash the payload and close OK
    dlg.accept()
    assert dlg.payload() == payload

def test_expense_form_initial_prefill_for_editing():
    _qapp()
    cats = [(1, "Meals"), (2, "Travel")]
    initial = {"expense_id": 7, "description": "Lunch", "amount": 150.5, "date": "2025-01-10", "category_id": 2}
    dlg = ExpenseForm(None, categories=cats, initial=initial)
    # fields reflect initial
    assert dlg._expense_id == 7
    assert dlg.edt_description.text() == "Lunch"
    assert dlg.spin_amount.value() == 150.5
    assert dlg.date_edit.date().toString("yyyy-MM-dd") == "2025-01-10"
    # category combobox currentData matches 2
    assert dlg.cmb_category.currentData() == 2

# Citations for ExpenseForm behavior (validation, payload shape, initial prefill): .

# ========================= Controller tests (original: tests/test_expense_controller.py) =========================

from PySide6.QtWidgets import QMessageBox  # noqa: E402
from PySide6.QtCore import Qt as QtCoreQt  # alias to avoid shadowing above Qt import  # noqa: E402

# Import controller and model exactly as described
from inventory_management.modules.expense.controller import ExpenseController  # noqa: E402
from inventory_management.modules.expense.model import ExpensesTableModel as _ExpensesTableModel  # noqa: E402

# We'll patch these within the controller module namespace
import inventory_management.modules.expense.controller as ctrl_mod  # noqa: E402

class FakeRepo:
    def __init__(self, *a, **k):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._cats = [
            # dataclass-like mapping; controller only needs id & name
            type("C", (), {"category_id": 1, "name": "Travel"})(),
            type("C", (), {"category_id": 2, "name": "Meals"})(),
        ]
        self._rows: list[dict] = []

    def list_categories(self):
        self.calls.append(("list_categories", (), {}))
        return self._cats

    def search_expenses(self, query: str = "", date: Optional[str] = None, category_id: Optional[int] = None) -> List[Dict[str, Any]]:
        self.calls.append(("search_expenses", (query, date, category_id), {}))
        # Echo filters for verification – controller doesn't care about contents
        return self._rows or [{
            "expense_id": 5, "date": date or "2025-01-01",
            "category_name": "Travel" if category_id == 1 else "Meals" if category_id == 2 else "",
            "description": f"desc:{query}" if query else "desc",
            "amount": 12.0,
        }]

    def delete_expense(self, expense_id: int) -> None:
        self.calls.append(("delete_expense", (expense_id,), {}))

def test_controller_builds_ui_loads_categories_and_initial_reload(monkeypatch):
    _qapp()
    fake = FakeRepo()
    monkeypatch.setattr(ctrl_mod, "ExpensesRepo", lambda conn: fake)
    c = ExpenseController(conn=None)  # controller constructs UI in __init__
    # "(All)" + 2 categories → 3 items
    assert c.cmb_category.count() == 1 + 2
    # initial reload should have built a model on the table
    assert isinstance(c.table.model(), _ExpensesTableModel)
    # repo called
    names = [name for (name, *_rest) in fake.calls]
    assert "list_categories" in names and "search_expenses" in names

def test_controller_reload_passes_filters(monkeypatch):
    _qapp()
    fake = FakeRepo()
    monkeypatch.setattr(ctrl_mod, "ExpensesRepo", lambda conn: fake)
    c = ExpenseController(conn=None)

    # set filters
    c.txt_search.setText("coffee")
    # choose a date via the widget; controller reads to "yyyy-MM-dd"
    from PySide6.QtCore import QDate
    c.date_filter.setDate(QDate.fromString("2025-01-15", "yyyy-MM-dd"))
    # pick category "Travel" (id=1)
    idx = c.cmb_category.findText("Travel", Qt.MatchExactly)
    c.cmb_category.setCurrentIndex(idx)

    # explicit reload
    c._reload()

    # last search_expenses call has our filters
    last = [call for call in fake.calls if call[0] == "search_expenses"][-1]
    assert last[1] == ("coffee", "2025-01-15", 1)

def test_controller_delete_no_selection_shows_info(monkeypatch):
    _qapp()
    fake = FakeRepo()
    monkeypatch.setattr(ctrl_mod, "ExpensesRepo", lambda conn: fake)

    # capture info messages
    seen = []
    monkeypatch.setattr(ctrl_mod.ui, "info", lambda parent, title, text: seen.append((title, text)))

    c = ExpenseController(conn=None)
    # no selection yet
    c._on_delete()
    assert seen and seen[-1][0] == "Select"  # "Please select an expense to delete."

def test_controller_delete_with_selection_calls_repo_and_reload(monkeypatch):
    _qapp()
    fake = FakeRepo()
    monkeypatch.setattr(ctrl_mod, "ExpensesRepo", lambda conn: fake)

    # Stub QMessageBox.question to auto-confirm
    monkeypatch.setattr(
        ctrl_mod, "QMessageBox",
        type("MB", (), {"question": staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)})
    )

    c = ExpenseController(conn=None)

    # Put a row in the table and select it
    rows = [{"expense_id": 42, "date": "2025-01-01", "category_name": "Meals", "description": "x", "amount": 1.0}]
    c.table.setModel(_ExpensesTableModel(rows))
    c.table.selectRow(0)

    # Keep track of reloads
    reloads = {"n": 0}
    orig_reload = c._reload
    def wrapped_reload():
        reloads["n"] += 1
        return orig_reload()
    monkeypatch.setattr(c, "_reload", wrapped_reload)

    c._on_delete()

    # Repo was called with selected id
    assert ("delete_expense", (42,), {}) in fake.calls
    # Reload invoked after delete
    assert reloads["n"] >= 1
