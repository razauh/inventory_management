# inventory_management/tests/expense.py
# pytest -q --maxfail=1 --disable-warnings

from __future__ import annotations

import csv
from typing import List, Dict

import pytest
from PySide6.QtCore import Qt, QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from inventory_management.database.repositories.expenses_repo import (
    ExpensesRepo,
    DomainError,
)
from inventory_management.modules.expense.form import ExpenseForm
from inventory_management.modules.expense.view import ExpenseView
from inventory_management.modules.expense.controller import ExpenseController
from inventory_management.modules.expense.model import ExpensesTableModel
from inventory_management.modules.expense.category_dialog import CategoryDialog


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _ensure_clean_tables(conn) -> None:
    try:
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM expense_categories")
        conn.commit()
    except Exception as e:
        raise RuntimeError(
            "Expected 'expenses' and 'expense_categories' to exist in data/myshop.db"
        ) from e


def _seed_categories(repo: ExpensesRepo, names: List[str]) -> List[int]:
    ids = []
    for n in names:
        cid = repo.create_category(n)
        ids.append(cid)
    return ids


def _seed_expenses(conn, rows: List[tuple]) -> None:
    cat_map = {r["name"]: r["category_id"] for r in conn.execute(
        "SELECT category_id, name FROM expense_categories"
    )}
    for d, a, dt_str, cname in rows:
        cid = cat_map.get(cname) if cname else None
        conn.execute(
            "INSERT INTO expenses(description, amount, date, category_id) VALUES (?,?,?,?)",
            (d, float(a), dt_str, cid),
        )
    conn.commit()


# ---------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------

def test_repo_category_crud_and_validation(conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)

    assert repo.list_categories() == []
    cid = repo.create_category(" Fuel ")
    cats = repo.list_categories()
    assert len(cats) == 1 and cats[0].name == "Fuel"

    repo.update_category(cid, "Diesel")
    cats = repo.list_categories()
    assert cats[0].name == "Diesel"

    with pytest.raises(DomainError):
        repo.create_category("  ")
    with pytest.raises(DomainError):
        repo.update_category(cid, "")

    repo.delete_category(cid)
    assert repo.list_categories() == []


def test_repo_expense_crud_search_totals(conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    (fuel_id, stat_id) = _seed_categories(repo, ["Fuel", "Stationery"])

    eid = repo.create_expense("Petrol", 50.0, "2024-01-02", fuel_id)
    row = repo.get_expense(eid)
    assert row and row["description"] == "Petrol" and row["amount"] == 50.0

    repo.update_expense(eid, "Petrol 95", 60.5, "2024-01-03", fuel_id)
    row2 = repo.get_expense(eid)
    assert row2["amount"] == 60.5 and row2["date"] == "2024-01-03"

    with pytest.raises(DomainError):
        repo.create_expense("", 10, "2024-01-01", None)
    with pytest.raises(DomainError):
        repo.create_expense("X", -1, "2024-01-01", None)

    _seed_expenses(conn, [
        ("Diesel", 60, "2024-01-02", "Fuel"),
        ("Pens",    5, "2024-01-02", "Stationery"),
        ("Paper",  15, "2024-01-03", "Stationery"),
    ])

    rows = repo.search_expenses(query="Pe", date="2024-01-03", category_id=fuel_id)
    names = [r["description"] for r in rows]
    assert names == ["Petrol 95"]

    rows2 = repo.search_expenses_adv(
        query="e",
        date_from="2024-01-02",
        date_to="2024-01-03",
        category_id=None,
        amount_min=10,
        amount_max=60,
    )
    names2 = [r["description"] for r in rows2]
    assert names2 == ["Paper", "Diesel"]

    totals = repo.total_by_category()
    got_names = {t["category_name"] for t in totals}
    assert {"Fuel", "Stationery"}.issubset(got_names)


# ---------------------------------------------------------------------
# Form tests
# ---------------------------------------------------------------------

def test_form_defaults_and_validation(qtbot, conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    cids = _seed_categories(repo, ["Fuel", "Stationery"])
    cats = [(cids[0], "Fuel"), (cids[1], "Stationery")]

    dlg = ExpenseForm(None, categories=cats, initial=None)
    qtbot.addWidget(dlg)

    assert dlg.date_edit.date().toString("yyyy-MM-dd") != ""

    dlg.spin_amount.setValue(10.0)
    dlg.accept()
    assert dlg.payload() is None

    dlg.edt_description.setText("Test expense")
    dlg.spin_amount.setValue(0.0)
    dlg.accept()
    assert dlg.payload() is None

    dlg.spin_amount.setValue(12.34)
    dlg.accept()
    p = dlg.payload()
    assert p and p["description"] == "Test expense" and p["amount"] == 12.34
    assert p["category_id"] is None


def test_form_prefill(qtbot, conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    cid_f, = _seed_categories(repo, ["Fuel"])

    initial = {
        "expense_id": 99,
        "description": "Prefilled",
        "amount": 77.7,
        "date": "2024-02-10",
        "category_id": cid_f,
    }
    dlg = ExpenseForm(None, categories=[(cid_f, "Fuel")], initial=initial)
    qtbot.addWidget(dlg)

    assert dlg.expense_id() == 99
    assert dlg.edt_description.text() == "Prefilled"
    assert abs(dlg.spin_amount.value() - 77.7) < 1e-6
    assert dlg.date_edit.date().toString("yyyy-MM-dd") == "2024-02-10"
    assert dlg.cmb_category.currentData() == cid_f


# ---------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------

def test_view_single_date_defaults_and_clear(qtbot):
    v = ExpenseView()
    qtbot.addWidget(v)

    assert v.selected_date is not None  # defaults to today
    v.btn_clear_date.click()
    assert v.selected_date is None


def test_view_advanced_filters_defaults(qtbot):
    v = ExpenseView()
    qtbot.addWidget(v)
    assert v.date_from_str is None
    assert v.date_to_str is None
    assert v.amount_min_val is None
    assert v.amount_max_val is None


# ---------------------------------------------------------------------
# Controller tests
# ---------------------------------------------------------------------

def test_controller_reload_and_model(qtbot, conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    cid_f, = _seed_categories(repo, ["Fuel"])
    _seed_expenses(conn, [("Petrol", 50, "2024-01-01", "Fuel")])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # IMPORTANT: clear the single-date filter (it defaults to today)
    c.view.btn_clear_date.click()

    model = c.view.tbl_expenses.model()
    assert isinstance(model, ExpensesTableModel)
    assert model.rowCount() >= 1


def test_controller_advanced_filters_and_totals(qtbot, conn, monkeypatch):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    _seed_categories(repo, ["Fuel", "Stationery"])
    _seed_expenses(conn, [
        ("Petrol", 50, "2024-01-01", "Fuel"),
        ("Diesel", 60, "2024-01-02", "Fuel"),
        ("Paper",  15, "2024-01-03", "Stationery"),
    ])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # date filter defaults to "today" -> clear before testing ranges
    c.view.btn_clear_date.click()

    # Advanced filters: date_to earlier than any row -> empty table
    c.view.date_to.setDate(QDate(2023, 12, 31))
    c._reload()
    assert c.view.tbl_expenses.model().rowCount() == 0

    # Clear advanced filters AND keep single-date cleared -> rows visible
    c.view.date_to.setDate(c.view.date_to.minimumDate())
    c._reload()
    assert c.view.tbl_expenses.model().rowCount() >= 3

    # Totals populated
    assert c.view.tbl_totals.model().rowCount() >= 2


def test_controller_export_csv(qtbot, conn, monkeypatch, tmp_path):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    _seed_categories(repo, ["Fuel"])
    _seed_expenses(conn, [("Petrol", 50, "2024-01-01", "Fuel")])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # Clear single-date filter so the row is visible
    c.view.btn_clear_date.click()

    out = tmp_path / "expenses.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(out), "CSV Files (*.csv)")
    )
    c._on_export_csv()
    assert out.exists()
    txt = out.read_text(encoding="utf-8")
    assert "Petrol" in txt


def test_controller_shortcuts_trigger_handlers(qtbot, conn, monkeypatch):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    _seed_categories(repo, ["Fuel"])

    # Start with one row so Edit/Delete make sense
    _seed_expenses(conn, [("Seed", 10, "2024-01-01", "Fuel")])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # Clear date to see seeded row; select first row
    c.view.btn_clear_date.click()
    tv = c.view.tbl_expenses
    tv.selectRow(0)
    tv.setFocus()

    # When Add/Edit are invoked by shortcuts, avoid opening a modal form:
    # stub _open_form to return synthetic payloads.
    monkeypatch.setattr(c, "_open_form", lambda initial=None: (
        {
            "expense_id": (initial or {}).get("expense_id"),
            "description": (initial and (initial["description"] + " (edited)")) or "Added via Ctrl+N",
            "amount": 11.0 if initial else 22.0,
            "date": "2024-01-02",
            "category_id": c.repo.list_categories()[0].category_id
        }
    ))

    # --- Ctrl+N -> add new row ---
    before = tv.model().rowCount()
    # send the key to the VIEW (shortcuts are parented to view)
    QTest.keyClick(c.view, Qt.Key_N, Qt.ControlModifier)
    # wait until row count increases (avoid race)
    qtbot.waitUntil(lambda: tv.model().rowCount() == before + 1, timeout=500)

    # --- Return/Enter -> edit selected row (the selection remains on row 0) ---
    old_desc = tv.model().index(0, 3).data()  # Description is column 3
    QTest.keyClick(c.view, Qt.Key_Return)
    qtbot.wait(50)
    new_desc = tv.model().index(0, 3).data()
    assert new_desc != old_desc and "(edited)" in new_desc

    # --- Delete -> delete selected row ---
    before_del = tv.model().rowCount()
    QTest.keyClick(c.view, Qt.Key_Delete)
    qtbot.waitUntil(lambda: tv.model().rowCount() == before_del - 1, timeout=500)


def test_controller_add_edit_delete_flow(qtbot, conn, monkeypatch):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    cid, = _seed_categories(repo, ["Fuel"])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # Clear single-date filter so added row is visible regardless of date
    c.view.btn_clear_date.click()

    # Add (stub form)
    monkeypatch.setattr(c, "_open_form", lambda initial=None: {
        "expense_id": None, "description": "Diesel", "amount": 75.0,
        "date": "2024-03-01", "category_id": cid
    })
    c._on_add()
    assert c.view.tbl_expenses.model().rowCount() == 1

    # Select & edit (stub form)
    exp_id = c.view.tbl_expenses.model().index(0, 0).data()
    monkeypatch.setattr(c, "_selected_expense_id", lambda: int(exp_id))
    monkeypatch.setattr(c, "_open_form", lambda initial=None: {
        "expense_id": exp_id, "description": "Diesel Euro5", "amount": 80.0,
        "date": "2024-03-02", "category_id": cid
    })
    c._on_edit()
    # Description is column 3
    assert "Euro" in c.view.tbl_expenses.model().index(0, 3).data()

    # Delete (conftest answers Yes)
    c._on_delete()
    assert c.view.tbl_expenses.model().rowCount() == 0


# ---------------------------------------------------------------------
# Category dialog tests
# ---------------------------------------------------------------------

def test_category_dialog_crud(qtbot, conn):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    _seed_categories(repo, ["Fuel", "Stationery"])

    dlg = CategoryDialog(None, repo)
    qtbot.addWidget(dlg)

    # Add
    dlg.edt_name.setText("Utilities")
    dlg._add()
    names = [dlg.tbl.item(r, 1).text() for r in range(dlg.tbl.rowCount())]
    assert "Utilities" in names

    # Rename first row
    dlg.tbl.selectRow(0)
    dlg.edt_name.setText("Fuel-Road")
    dlg._rename()
    assert dlg.tbl.item(0, 1).text() == "Fuel-Road"

    # Delete selected
    before = dlg.tbl.rowCount()
    dlg._delete()
    assert dlg.tbl.rowCount() == before - 1


# ---------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------

def test_expense_e2e_crud_filters_totals_export(qtbot, conn, monkeypatch, tmp_path):
    _ensure_clean_tables(conn)
    repo = ExpensesRepo(conn)
    cid, = _seed_categories(repo, ["Fuel"])

    c = ExpenseController(conn)
    qtbot.addWidget(c.get_widget())

    # Clear single-date filter for visibility
    c.view.btn_clear_date.click()

    # Add via form stub
    monkeypatch.setattr(c, "_open_form", lambda initial=None: {
        "expense_id": None, "description": "Gas", "amount": 100.0,
        "date": "2024-05-10", "category_id": cid
    })
    c._on_add()
    assert c.view.tbl_expenses.model().rowCount() == 1

    # Advanced filter that hides the row
    c.view.date_to.setDate(QDate(2024, 5, 1))
    c._reload()
    assert c.view.tbl_expenses.model().rowCount() == 0

    # Clear advanced and keep single-date cleared -> row visible
    c.view.date_to.setDate(c.view.date_to.minimumDate())
    c._reload()
    assert c.view.tbl_totals.model().rowCount() >= 1

    # Export
    out = tmp_path / "out.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(out), "CSV Files (*.csv)")
    )
    c._on_export_csv()
    assert out.exists()
    with out.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert any("Gas" in ",".join(r) for r in rows)
