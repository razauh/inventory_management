from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_symbol(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, name)


SalePaymentsRepo = _load_symbol(
    PROJECT_ROOT / "database" / "repositories" / "sale_payments_repo.py",
    "SalePaymentsRepo",
)
SQL = _load_symbol(PROJECT_ROOT / "database" / "schema.py", "SQL")


def _create_sale_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(SQL)
        customer_id = con.execute(
            """
            INSERT INTO customers (name, contact_info, address)
            VALUES ('Overpayment Customer', 'test', 'test')
            """
        ).lastrowid
        con.execute(
            """
            INSERT INTO sales (
                sale_id, customer_id, date, total_amount, payment_status,
                paid_amount, advance_payment_applied, doc_type
            ) VALUES ('SALE-OVERPAY', ?, '2026-06-11', 100, 'unpaid', 0, 0, 'sale')
            """,
            (customer_id,),
        )


def _fetch_credit_state(db_path: Path, payment_id: int) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        payment = con.execute(
            """
            SELECT clearing_state, overpayment_converted, converted_to_credit
            FROM sale_payments
            WHERE payment_id = ?
            """,
            (payment_id,),
        ).fetchone()
        credits = con.execute(
            """
            SELECT amount, source_type, source_id
            FROM customer_advances
            ORDER BY tx_id
            """
        ).fetchall()
        return payment, credits


def test_cleared_overpayment_creates_credit_in_same_database(tmp_path: Path) -> None:
    db_path = tmp_path / "cleared-overpayment.sqlite"
    _create_sale_db(db_path)
    repo = SalePaymentsRepo(db_path)

    payment_id = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=120,
        method="Cash",
        date="2026-06-11",
        clearing_state="cleared",
    )

    payment, credits = _fetch_credit_state(db_path, payment_id)
    assert payment["overpayment_converted"] == 1
    assert float(payment["converted_to_credit"]) == 20.0
    assert len(credits) == 1
    assert float(credits[0]["amount"]) == 20.0
    assert credits[0]["source_type"] == "deposit"
    assert credits[0]["source_id"] == str(payment_id)


def test_pending_overpayment_creates_one_credit_when_cleared(tmp_path: Path) -> None:
    db_path = tmp_path / "pending-overpayment.sqlite"
    _create_sale_db(db_path)
    repo = SalePaymentsRepo(db_path)

    payment_id = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=120,
        method="Other",
        date="2026-06-11",
        clearing_state="pending",
    )

    payment, credits = _fetch_credit_state(db_path, payment_id)
    assert payment["overpayment_converted"] == 0
    assert credits == []

    repo.update_clearing_state(
        payment_id,
        clearing_state="cleared",
        cleared_date="2026-06-12",
    )
    repo.update_clearing_state(
        payment_id,
        clearing_state="cleared",
        cleared_date="2026-06-12",
    )

    payment, credits = _fetch_credit_state(db_path, payment_id)
    assert payment["overpayment_converted"] == 1
    assert float(payment["converted_to_credit"]) == 20.0
    assert len(credits) == 1
    assert float(credits[0]["amount"]) == 20.0
    assert credits[0]["source_id"] == str(payment_id)


def test_bouncing_payment_reverses_credit(tmp_path: Path) -> None:
    db_path = tmp_path / "bounce-overpayment.sqlite"
    _create_sale_db(db_path)
    repo = SalePaymentsRepo(db_path)

    payment_id = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=120,
        method="Cash",
        date="2026-06-11",
        clearing_state="cleared",
    )

    # Transition to bounced
    repo.update_clearing_state(payment_id, clearing_state="bounced")

    payment, credits = _fetch_credit_state(db_path, payment_id)
    # The payment itself should have its converted fields reset
    assert payment["overpayment_converted"] == 0
    assert float(payment["converted_to_credit"] or 0) == 0.0
    # There should be 2 entries in customer_advances (original 20 and reversal -20)
    assert len(credits) == 2
    assert float(credits[0]["amount"]) == 20.0
    assert float(credits[1]["amount"]) == -20.0


def test_bouncing_fails_if_credit_consumed(tmp_path: Path) -> None:
    db_path = tmp_path / "bounce-fail.sqlite"
    _create_sale_db(db_path)
    repo = SalePaymentsRepo(db_path)

    payment_id = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=120,
        method="Cash",
        date="2026-06-11",
        clearing_state="cleared",
    )

    # Consume the customer credit
    with sqlite3.connect(db_path) as con:
        cust_id = con.execute("SELECT customer_id FROM sales WHERE sale_id='SALE-OVERPAY'").fetchone()[0]
        # Insert a consumption row of -15 (leaving only 5 balance)
        con.execute(
            """
            INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id)
            VALUES (?, '2026-06-11', -15.0, 'applied_to_sale', 'SALE-OVERPAY')
            """,
            (cust_id,),
        )
        con.commit()

    # Bouncing should fail because only 5 credit balance remains, but we need 20 to reverse the overpayment
    with pytest.raises(ValueError, match="Cannot revert payment clearing.*already been consumed"):
        repo.update_clearing_state(payment_id, clearing_state="bounced")


def test_multiple_payments_grant_only_incremental_excess(tmp_path: Path) -> None:
    db_path = tmp_path / "multiple-overpayment.sqlite"
    _create_sale_db(db_path)
    repo = SalePaymentsRepo(db_path)

    # Owed: 100.
    # We record two pending payments of 80 each (total 160)
    p1 = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=80,
        method="Other",
        clearing_state="pending",
    )
    p2 = repo.record_payment(
        sale_id="SALE-OVERPAY",
        amount=80,
        method="Other",
        clearing_state="pending",
    )

    # Clear payment 1 (total cleared = 80, owed = 100, no excess)
    repo.update_clearing_state(p1, clearing_state="cleared")
    _, credits = _fetch_credit_state(db_path, p1)
    assert len(credits) == 0

    # Clear payment 2 (total cleared = 160, owed = 100, total excess = 60, incremental excess = 60)
    repo.update_clearing_state(p2, clearing_state="cleared")
    _, credits = _fetch_credit_state(db_path, p2)
    assert len(credits) == 1
    assert float(credits[0]["amount"]) == 60.0
    assert credits[0]["source_id"] == str(p2)

