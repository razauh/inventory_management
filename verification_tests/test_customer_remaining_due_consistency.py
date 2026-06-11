from __future__ import annotations

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# database/__init__.py imports an optional seeder absent from this checkout.
# Use the package path directly so this focused test stays independent of app startup imports.
database_package = types.ModuleType("inventory_management.database")
database_package.__path__ = [str(PROJECT_ROOT / "database")]
sys.modules.setdefault("inventory_management.database", database_package)

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from inventory_management.database.repositories.customer_advances_repo import CustomerAdvancesRepo
from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.repositories.sale_payments_repo import SalePaymentsRepo
from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import init_schema
from inventory_management.modules.customer.controller import CustomerController
from inventory_management.modules.customer.history import CustomerHistoryService
from inventory_management.modules.customer.receipt_dialog import _CustomerMoneyDialog
from inventory_management.modules.reporting.customer_aging_reports import CustomerAgingReports


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def sale_db(tmp_path: Path) -> tuple[Path, int]:
    db_path = tmp_path / "remaining-due.sqlite"
    init_schema(db_path)
    with sqlite3.connect(db_path) as con:
        customer_id = con.execute(
            "INSERT INTO customers (name, contact_info, address) VALUES ('Customer', 'x', 'x')"
        ).lastrowid
        uom_id = con.execute("INSERT INTO uoms (unit_name) VALUES ('Each')").lastrowid
        product_id = con.execute(
            "INSERT INTO products (name, description, category) VALUES ('Item', '', '')"
        ).lastrowid
        con.execute(
            "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
            (product_id, uom_id),
        )
        con.execute(
            """
            INSERT INTO sales (
                sale_id, customer_id, date, total_amount, order_discount,
                payment_status, paid_amount, advance_payment_applied, doc_type
            ) VALUES ('SALE-1', ?, '2026-06-01', 70, 0, 'unpaid', 0, 0, 'sale')
            """,
            (customer_id,),
        )
        con.execute(
            """
            INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
            VALUES ('SALE-1', ?, 1, ?, 50, 0)
            """,
            (product_id, uom_id),
        )
    return db_path, int(customer_id)


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def test_all_read_paths_use_canonical_remaining_due(sale_db: tuple[Path, int]) -> None:
    db_path, customer_id = sale_db
    SalePaymentsRepo(db_path).record_payment(
        sale_id="SALE-1", amount=20, method="Cash", clearing_state="cleared"
    )
    advances = CustomerAdvancesRepo(db_path)
    advances.grant_credit(customer_id=customer_id, amount=30)
    advances.apply_credit_to_sale(customer_id=customer_id, sale_id="SALE-1", amount=10)

    with _connect(db_path) as con:
        canonical = con.execute(
            "SELECT canonical_total_amount, remaining_due FROM sale_receivable_totals WHERE sale_id='SALE-1'"
        ).fetchone()
        assert tuple(map(float, canonical)) == (50.0, 20.0)

        controller = CustomerController.__new__(CustomerController)
        controller.conn = con
        assert controller._details_enrichment(customer_id)["open_due_sum"] == 20.0

        reporting = ReportingRepo(con)
        header = reporting.customer_headers_as_of(customer_id, "2026-06-11")[0]
        assert float(header["total_amount"]) == 50.0
        assert float(header["total_amount"] - header["paid_amount"] - header["advance_payment_applied"]) == 20.0
        drilldown = reporting.drilldown_sales("2026-06-01", "2026-06-30", None, customer_id, None, None)[0]
        assert float(drilldown["remaining_due"]) == 20.0

        aging = CustomerAgingReports(con)
        assert aging.compute_aging_snapshot("2026-06-11", customer_id=customer_id)[0]["total_due"] == 20.0

    history = CustomerHistoryService(db_path).sales_with_items(customer_id)[0]
    assert history["calculated_total_amount"] == 50.0
    assert history["remaining_due"] == 20.0


def test_dialog_displays_and_validates_canonical_due(
    sale_db: tuple[Path, int], qapp: QApplication
) -> None:
    db_path, customer_id = sale_db
    SalePaymentsRepo(db_path).record_payment(
        sale_id="SALE-1", amount=20, method="Cash", clearing_state="cleared"
    )
    advances = CustomerAdvancesRepo(db_path)
    advances.grant_credit(customer_id=customer_id, amount=100)
    advances.apply_credit_to_sale(customer_id=customer_id, sale_id="SALE-1", amount=10)

    sale = {
        "sale_id": "SALE-1",
        "date": "2026-06-01",
        "total": 50.0,
        "paid": 20.0,
        "advance_payment_applied": 10.0,
        "remaining_due": 20.0,
    }
    dialog = _CustomerMoneyDialog(
        mode="apply_advance",
        customer_id=customer_id,
        sale_id=None,
        defaults={
            "sales": [sale],
            "list_sales_for_customer": lambda _customer_id: [sale],
            "get_available_advance": lambda _customer_id: 90.0,
            "get_sale_due": lambda _sale_id: 20.0,
        },
    )
    model = dialog.applySalesTable.model()
    index = model.index(0, 0)
    dialog.applySalesTable.selectionModel().select(
        index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
    )
    dialog.applySalesTable.setCurrentIndex(index)
    qapp.processEvents()

    assert dialog.applySaleRemainingLabel.text() == "20.00"
    dialog.applyAmountEdit.setValue(20.0)
    assert dialog._validate_apply() == (True, None)
    dialog.applyAmountEdit.setValue(20.01)
    assert dialog._validate_apply()[0] is False
    assert "Rem 20.00" in dialog.salePicker.itemText(0)
    dialog.close()


def test_exact_advance_succeeds_and_overapplication_fails(sale_db: tuple[Path, int]) -> None:
    db_path, customer_id = sale_db
    repo = CustomerAdvancesRepo(db_path)
    repo.grant_credit(customer_id=customer_id, amount=60)
    repo.apply_credit_to_sale(customer_id=customer_id, sale_id="SALE-1", amount=50)

    with _connect(db_path) as con:
        row = con.execute(
            "SELECT advance_payment_applied, payment_status FROM sales WHERE sale_id='SALE-1'"
        ).fetchone()
        assert float(row["advance_payment_applied"]) == 50.0
        assert row["payment_status"] == "paid"

    with pytest.raises(ValueError, match="remaining due on sale is 0.00"):
        repo.apply_credit_to_sale(customer_id=customer_id, sale_id="SALE-1", amount=1)

    with _connect(db_path) as con, pytest.raises(sqlite3.IntegrityError, match="beyond remaining due"):
        con.execute(
            """
            INSERT INTO customer_advances (customer_id, amount, source_type, source_id)
            VALUES (?, -1, 'applied_to_sale', 'SALE-1')
            """,
            (customer_id,),
        )


def test_overpayment_credit_uses_line_total(sale_db: tuple[Path, int]) -> None:
    db_path, customer_id = sale_db
    SalePaymentsRepo(db_path).record_payment(
        sale_id="SALE-1", amount=60, method="Cash", clearing_state="cleared"
    )
    with _connect(db_path) as con:
        credit = con.execute(
            "SELECT amount FROM customer_advances WHERE customer_id=? AND source_type='deposit'",
            (customer_id,),
        ).fetchone()
        sale = con.execute(
            "SELECT paid_amount, payment_status FROM sales WHERE sale_id='SALE-1'"
        ).fetchone()
        assert float(credit["amount"]) == 10.0
        assert float(sale["paid_amount"]) == 60.0
        assert sale["payment_status"] == "paid"


def test_sale_edit_preserves_applied_advance(sale_db: tuple[Path, int]) -> None:
    db_path, customer_id = sale_db
    SalePaymentsRepo(db_path).record_payment(
        sale_id="SALE-1", amount=20, method="Cash", clearing_state="cleared"
    )
    advances = CustomerAdvancesRepo(db_path)
    advances.grant_credit(customer_id=customer_id, amount=10)
    advances.apply_credit_to_sale(customer_id=customer_id, sale_id="SALE-1", amount=10)

    with _connect(db_path) as con:
        item = con.execute(
            "SELECT product_id, uom_id FROM sale_items WHERE sale_id='SALE-1'"
        ).fetchone()
        SalesRepo(con).update_sale(
            SaleHeader(
                sale_id="SALE-1",
                customer_id=customer_id,
                date="2026-06-01",
                total_amount=999,
                order_discount=0,
                payment_status="unpaid",
                paid_amount=0,
                advance_payment_applied=0,
                notes=None,
                created_by=None,
            ),
            [
                SaleItem(
                    None, "SALE-1", int(item["product_id"]), 1, int(item["uom_id"]), 80, 0
                )
            ],
        )
        row = con.execute(
            """
            SELECT s.paid_amount, s.advance_payment_applied, s.payment_status,
                   srt.canonical_total_amount, srt.remaining_due
            FROM sales s
            JOIN sale_receivable_totals srt ON srt.sale_id=s.sale_id
            WHERE s.sale_id='SALE-1'
            """
        ).fetchone()
        assert tuple(map(float, row[:2])) == (20.0, 10.0)
        assert row["payment_status"] == "partial"
        assert float(row["canonical_total_amount"]) == 80.0
        assert float(row["remaining_due"]) == 50.0


def test_matching_and_negative_line_totals_are_stable(sale_db: tuple[Path, int]) -> None:
    db_path, _customer_id = sale_db
    with _connect(db_path) as con:
        con.execute("UPDATE sales SET total_amount=50 WHERE sale_id='SALE-1'")
        matching = con.execute(
            "SELECT canonical_total_amount, remaining_due FROM sale_receivable_totals WHERE sale_id='SALE-1'"
        ).fetchone()
        assert tuple(map(float, matching)) == (50.0, 50.0)

        con.execute("UPDATE sale_items SET item_discount=60 WHERE sale_id='SALE-1'")
        clamped = con.execute(
            "SELECT canonical_total_amount, remaining_due FROM sale_receivable_totals WHERE sale_id='SALE-1'"
        ).fetchone()
        assert tuple(map(float, clamped)) == (0.0, 0.0)


def test_startup_schema_refreshes_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "startup.sqlite"
    init_schema(db_path)
    init_schema(db_path)
    with _connect(db_path) as con:
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name='sale_receivable_totals'"
        ).fetchone()
