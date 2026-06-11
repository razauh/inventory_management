from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

class SalePaymentsRepo:
    """
    Repository for customer receipts/refunds (rows in sale_payments).

    Rules enforced here (mirrors DB-side policy):
      • No payments against quotations (DB trigger enforces).
      • Bank methods (Bank Transfer / Cheque / Cash Deposit) are INCOMING-ONLY (amount > 0),
        require a company bank account, and require a specific instrument_type + instrument_no.
      • Card / Other are also INCOMING-ONLY (amount > 0); no bank account required.
      • Cash may be incoming (amount > 0) or a refund (amount < 0). Cash must NOT reference a bank,
        must use instrument_type='other', and instrument_no is optional.

    Lifecycle:
      • Use record_payment(...) to insert receipts/refunds.
      • Use update_clearing_state(...) to update pending/cleared/bounced status.
      • list_by_sale(...) and list_by_customer(...) fetch history for UI.
    """

    METHODS: set[str] = {
        "Cash",
        "Bank Transfer",
        "Card",
        "Cheque",
        "Cross Cheque",
        "Cash Deposit",
        "Other",
    }

    # Instrument types allowed by CHECK constraint on sale_payments.instrument_type:
    ITYPES: set[str] = {"online", "cross_cheque", "cash_deposit", "pay_order", "other"}

    # Map method -> default instrument_type expected by validations
    DEFAULT_ITYPE_BY_METHOD: dict[str, str] = {
        "Cash": "other",
        "Bank Transfer": "online",
        "Cheque": "cross_cheque",
        "Cash Deposit": "cash_deposit",
        # Card/Other don't require a specific type, but CHECK disallows NULL → use 'other'
        "Card": "other",
        "Other": "other",
    }

    # Sensible default clearing states per method
    DEFAULT_CLEARING_STATE_BY_METHOD: dict[str, str] = {
        "Cash": "cleared",          # cash is immediately available
        "Bank Transfer": "pending", # bank transfer pending verification
        "Card": "pending",          # card payment pending verification
        "Other": "pending",         # other payment pending verification
        "Cheque": "pending",        # cheque pending clearing
        "Cross Cheque": "pending",  # cross cheque pending clearing
        "Cash Deposit": "pending",  # cash deposit pending verification
    }

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    # --- connection helper -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    @staticmethod
    def _grant_customer_credit(
        con: sqlite3.Connection,
        *,
        customer_id: int,
        amount: float,
        date: Optional[str],
        notes: str,
        created_by: Optional[int],
        source_id: Optional[str] = None,
    ) -> int:
        cur = con.execute(
            """
            INSERT INTO customer_advances
                (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
            VALUES
                (:customer_id, COALESCE(:tx_date, CURRENT_DATE), :amount,
                 'deposit', :source_id, :notes, :created_by)
            """,
            {
                "customer_id": customer_id,
                "tx_date": date,
                "amount": float(amount),
                "source_id": source_id,
                "notes": notes,
                "created_by": created_by,
            },
        )
        return int(cur.lastrowid)

    # --- soft validations mirroring DB rules -------------------------------

    def _normalize_and_validate(
        self,
        *,
        method: str,
        amount: float,
        bank_account_id: Optional[int],
        instrument_type: Optional[str],
        instrument_no: Optional[str],
    ) -> tuple[str, float, Optional[int], str, Optional[str]]:
        """
        Returns normalized (method, amount, bank_account_id, instrument_type, instrument_no)
        or raises ValueError with a user-facing message.
        """

        # Method known?
        if method not in self.METHODS:
            raise ValueError(f"Unsupported payment method: {method}")

        # Normalize amount & type
        if amount is None:
            raise ValueError("Amount is required.")
        amount = float(amount)

        # Instrument type defaults (avoid NULL which would fail CHECK)
        if not instrument_type:
            instrument_type = self.DEFAULT_ITYPE_BY_METHOD.get(method, "other")

        # Validate instrument_type is one of allowed set
        if instrument_type not in self.ITYPES:
            raise ValueError(
                f"Invalid instrument type '{instrument_type}'. "
                f"Allowed: {', '.join(sorted(self.ITYPES))}"
            )

        # Method-specific constraints
        if method == "Cash":
            # Cash may be positive (receipt) or negative (refund)
            if amount == 0:
                raise ValueError("Cash amount cannot be zero.")
            if bank_account_id is not None:
                raise ValueError("Cash should not reference a company bank account.")
            if instrument_type != "other":
                raise ValueError("Cash must use instrument_type='other'.")
            # instrument_no optional → leave as-is

        elif method == "Bank Transfer":
            # Incoming-only
            if amount <= 0:
                raise ValueError("Bank Transfer must be a positive (incoming) amount.")
            if bank_account_id is None:
                raise ValueError("Bank Transfer requires a company bank account.")
            if not instrument_no:
                raise ValueError("Bank Transfer requires a transaction/reference number.")
            if instrument_type != "online":
                raise ValueError("Bank Transfer must use instrument_type='online'.")

        elif method in ("Cheque", "Cross Cheque"):
            # Cheque-like methods (Cheque and Cross Cheque) share the same rules
            if amount <= 0:
                raise ValueError(f"{method} must be a positive (incoming) amount.")
            if bank_account_id is None:
                raise ValueError(f"{method} requires a company bank account.")
            if not instrument_no:
                raise ValueError(f"{method} requires a cheque number.")
            if instrument_type != "cross_cheque":
                raise ValueError(f"{method} must use instrument_type='cross_cheque'.")

        elif method == "Cash Deposit":
            # Incoming-only
            if amount <= 0:
                raise ValueError("Cash Deposit must be a positive (incoming) amount.")
            if bank_account_id is None:
                raise ValueError("Cash Deposit requires a company bank account.")
            if not instrument_no:
                raise ValueError("Cash Deposit requires a deposit slip number.")
            if instrument_type != "cash_deposit":
                raise ValueError("Cash Deposit must use instrument_type='cash_deposit'.")

        else:
            # Card / Other — incoming-only; no bank requirement
            if amount <= 0:
                raise ValueError(f"{method} must be a positive (incoming) amount.")
            if not instrument_type:
                instrument_type = "other"
            # bank_account_id may be provided for internal mapping, but not required; allow None.

        return method, amount, bank_account_id, instrument_type, instrument_no

    # --- API ---------------------------------------------------------------

    def record_payment_with_conn(
        self,
        con: sqlite3.Connection,
        *,
        sale_id: str,
        amount: float,
        method: str,
        date: Optional[str] = None,
        bank_account_id: Optional[int] = None,
        instrument_type: Optional[str] = None,
        instrument_no: Optional[str] = None,
        instrument_date: Optional[str] = None,
        deposited_date: Optional[str] = None,
        cleared_date: Optional[str] = None,
        clearing_state: Optional[str] = None,
        ref_no: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """
        Record a payment using an existing connection/transaction.
        """
        # Normalize & validate fields
        method, amount, bank_account_id, instrument_type, instrument_no = self._normalize_and_validate(
            method=method,
            amount=amount,
            bank_account_id=bank_account_id,
            instrument_type=instrument_type,
            instrument_no=instrument_no,
        )

        # Default clearing_state if not supplied
        if not clearing_state:
            clearing_state = self.DEFAULT_CLEARING_STATE_BY_METHOD.get(method, "posted")

        if clearing_state not in {"posted", "pending", "cleared", "bounced"}:
            raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")

        # Check if this is an overpayment and convert excess to customer credit
        # Get sale information to determine what's due
        sale_info = con.execute(
            """
            SELECT
                srt.canonical_total_amount,
                srt.advance_payment_applied,
                c.customer_id
            FROM sales s
            JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
            JOIN customers c ON c.customer_id = s.customer_id
            WHERE s.sale_id = ?
            """,
            (sale_id,),
        ).fetchone()

        if not sale_info:
            raise ValueError(f"Sale not found: {sale_id}")

        customer_id = int(sale_info["customer_id"])

        # Record the original full payment amount in the database
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO sale_payments (
                sale_id, date, amount, method,
                bank_account_id, instrument_type, instrument_no,
                instrument_date, deposited_date, cleared_date,
                clearing_state, ref_no, notes, created_by, overpayment_converted, converted_to_credit
            ) VALUES (
                :sale_id, COALESCE(:date, CURRENT_DATE), :original_amount, :method,
                :bank_account_id, :instrument_type, :instrument_no,
                :instrument_date, :deposited_date, :cleared_date,
                :clearing_state, :ref_no, :notes, :created_by, 0, 0
            );
            """,
            {
                "sale_id": sale_id,
                "date": date,
                "original_amount": amount,  # Always record the original payment amount
                "method": method,
                "bank_account_id": bank_account_id,
                "instrument_type": instrument_type,
                "instrument_no": instrument_no,
                "instrument_date": instrument_date,
                "deposited_date": deposited_date,
                "cleared_date": cleared_date,
                "clearing_state": clearing_state,
                "ref_no": ref_no,
                "notes": notes,
                "created_by": created_by,
            },
        )
        payment_id_of_new_record = int(cur.lastrowid)

        # Only grant customer credit if the payment is cleared
        if clearing_state == "cleared":
            total_amount = float(sale_info["canonical_total_amount"])
            current_advance = float(sale_info["advance_payment_applied"]) if sale_info["advance_payment_applied"] else 0.0
            total_amount_owed = total_amount - current_advance

            total_paid_cleared = con.execute(
                "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS total FROM sale_payments WHERE sale_id = ? AND clearing_state = 'cleared'",
                (sale_id,)
            ).fetchone()["total"]

            already_converted = con.execute(
                "SELECT COALESCE(SUM(CAST(converted_to_credit AS REAL)), 0.0) AS total FROM sale_payments WHERE sale_id = ? AND payment_id != ?",
                (sale_id, payment_id_of_new_record)
            ).fetchone()["total"]

            total_excess = max(0.0, total_paid_cleared - total_amount_owed)
            excess_amount = max(0.0, total_excess - already_converted)

            if excess_amount > 1e-9:
                self._grant_customer_credit(
                    con,
                    customer_id=customer_id,
                    amount=excess_amount,
                    date=date or None,
                    notes=f"Excess payment converted to credit on {sale_id}",
                    created_by=created_by,
                    source_id=str(payment_id_of_new_record),
                )
                # Mark that overpayment has been converted
                con.execute(
                    "UPDATE sale_payments SET overpayment_converted = 1, converted_to_credit = ? WHERE payment_id = ?",
                    (excess_amount, payment_id_of_new_record)
                )

        return payment_id_of_new_record

    def record_payment(
        self,
        *,
        sale_id: str,
        amount: float,
        method: str,
        date: Optional[str] = None,                # 'YYYY-MM-DD' (defaults to CURRENT_DATE in DB if None)
        bank_account_id: Optional[int] = None,     # required for bank methods; must be None for Cash
        instrument_type: Optional[str] = None,     # normalized to required value per method
        instrument_no: Optional[str] = None,       # required for bank methods
        instrument_date: Optional[str] = None,     # optional
        deposited_date: Optional[str] = None,      # optional; typically for Cash Deposit/Cheque
        cleared_date: Optional[str] = None,        # optional
        clearing_state: Optional[str] = None,      # posted/pending/cleared/bounced
        ref_no: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """
        Inserts a row into sale_payments and returns payment_id.

        Notes:
          • Negative 'amount' is allowed ONLY for method='Cash' (cash refunds).
          • DB triggers roll up paid_amount/payment_status on the sales header.
          • If amount exceeds the due amount, the excess is converted to customer credit.
        """
        with self._connect() as con:
            return self.record_payment_with_conn(
                con,
                sale_id=sale_id,
                amount=amount,
                method=method,
                date=date,
                bank_account_id=bank_account_id,
                instrument_type=instrument_type,
                instrument_no=instrument_no,
                instrument_date=instrument_date,
                deposited_date=deposited_date,
                cleared_date=cleared_date,
                clearing_state=clearing_state,
                ref_no=ref_no,
                notes=notes,
                created_by=created_by,
            )

    def update_clearing_state(
        self,
        payment_id: int,
        *,
        clearing_state: str,
        cleared_date: Optional[str] = None,     # 'YYYY-MM-DD'
        deposited_date: Optional[str] = None,   # optional
        instrument_date: Optional[str] = None,  # optional
        notes: Optional[str] = None,
        ref_no: Optional[str] = None,
    ) -> int:
        """
        Update the clearing_state (posted/pending/cleared/bounced) and optional dates.
        When changing to 'cleared', this will also process any overpayment as customer credit.
        """
        if clearing_state not in {"posted", "pending", "cleared", "bounced"}:
            raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")

        with self._connect() as con:
            # Get original values before update - this is atomic and will be part of our transaction
            original_values = con.execute(
                "SELECT sale_id, amount, method, clearing_state, converted_to_credit FROM sale_payments WHERE payment_id = ?;",
                (payment_id,),
            ).fetchone()

            if not original_values:
                raise ValueError(f"Payment not found: {payment_id}")

            old_clearing_state = original_values["clearing_state"]
            if old_clearing_state == clearing_state:
                return 1

            if old_clearing_state == "bounced":
                raise ValueError("Cannot change state of a bounced payment")

            # Check reversal if transitioning from cleared to non-cleared
            if old_clearing_state == "cleared" and clearing_state != "cleared":
                converted_amount = float(original_values["converted_to_credit"] or 0.0)
                if converted_amount > 1e-9:
                    sale_row = con.execute(
                        "SELECT customer_id FROM sales WHERE sale_id = ?",
                        (original_values["sale_id"],)
                    ).fetchone()
                    customer_id = int(sale_row["customer_id"])

                    current_balance = con.execute(
                        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS bal FROM customer_advances WHERE customer_id = ?",
                        (customer_id,)
                    ).fetchone()["bal"]

                    if current_balance < converted_amount - 1e-9:
                        raise ValueError(
                            f"Cannot revert payment clearing: customer credit of {converted_amount:g} has already been consumed. "
                            f"Current credit balance: {current_balance:g}."
                        )

                    # Deduct the credit by inserting a negative row in customer_advances
                    con.execute(
                        """
                        INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
                        VALUES (?, CURRENT_DATE, ?, 'deposit', ?, ?, ?)
                        """,
                        (customer_id, -converted_amount, str(payment_id), f"Reversal of excess credit from reverted payment #{payment_id}", None)
                    )

                    # Reset converted_to_credit and overpayment_converted on the payment row BEFORE updating clearing_state
                    con.execute(
                        "UPDATE sale_payments SET overpayment_converted = 0, converted_to_credit = 0 WHERE payment_id = ?",
                        (payment_id,)
                    )

            # Only update if the state is actually different (atomic check prevents race condition)
            update_query = """
                UPDATE sale_payments
                   SET clearing_state = :clearing_state,
                       cleared_date   = :cleared_date,
                       deposited_date = :deposited_date,
                       instrument_date= :instrument_date,
                       notes          = COALESCE(:notes, notes),
                       ref_no         = COALESCE(:ref_no, ref_no)
                  WHERE payment_id = :payment_id
                    AND clearing_state = :old_clearing_state;  -- Ensure the old state matches what we expect, preventing TOCTOU
                """

            cur = con.cursor()
            cur.execute(update_query, {
                "clearing_state": clearing_state,
                "cleared_date": cleared_date,
                "deposited_date": deposited_date,
                "instrument_date": instrument_date,
                "notes": notes,
                "ref_no": ref_no,
                "payment_id": payment_id,
                "old_clearing_state": old_clearing_state,  # This ensures atomicity against concurrent updates
            })

            # Check how many rows were affected to ensure the update happened
            rows_affected = cur.rowcount

            if rows_affected == 0:
                # Another thread may have already updated this payment between our select and update
                current_state = con.execute(
                    "SELECT clearing_state FROM sale_payments WHERE payment_id = ?;",
                    (payment_id,),
                ).fetchone()

                if not current_state:
                    raise ValueError(f"Payment not found: {payment_id}")

                if current_state["clearing_state"] == clearing_state:
                    return 1
                else:
                    raise ValueError(f"Another operation changed payment {payment_id} state concurrently")

            # If we're changing the state TO 'cleared' from another state, check for overpayment
            if clearing_state == 'cleared' and old_clearing_state != 'cleared':
                sale_id = original_values["sale_id"]
                sale_info = con.execute(
                    """
                    SELECT
                        srt.canonical_total_amount,
                        srt.advance_payment_applied,
                        c.customer_id
                    FROM sales s
                    JOIN sale_receivable_totals srt ON srt.sale_id = s.sale_id
                    JOIN customers c ON c.customer_id = s.customer_id
                    WHERE s.sale_id = ?
                    """,
                    (sale_id,),
                ).fetchone()

                if sale_info:
                    total_amount = float(sale_info["canonical_total_amount"])
                    current_advance = float(sale_info["advance_payment_applied"]) if sale_info["advance_payment_applied"] else 0.0
                    customer_id = int(sale_info["customer_id"])

                    total_amount_owed = total_amount - current_advance

                    total_paid_cleared = con.execute(
                        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS total FROM sale_payments WHERE sale_id = ? AND clearing_state = 'cleared'",
                        (sale_id,)
                    ).fetchone()["total"]

                    already_converted = con.execute(
                        "SELECT COALESCE(SUM(CAST(converted_to_credit AS REAL)), 0.0) AS total FROM sale_payments WHERE sale_id = ? AND payment_id != ?",
                        (sale_id, payment_id)
                    ).fetchone()["total"]

                    total_excess = max(0.0, total_paid_cleared - total_amount_owed)
                    excess_amount = max(0.0, total_excess - already_converted)

                    if excess_amount > 1e-9:
                        self._grant_customer_credit(
                            con,
                            customer_id=customer_id,
                            amount=excess_amount,
                            date=cleared_date or None,
                            notes=f"Excess from cleared payment #{payment_id} on {sale_id}",
                            created_by=None,
                            source_id=str(payment_id),
                        )
                        con.execute(
                            "UPDATE sale_payments SET overpayment_converted = 1, converted_to_credit = ? WHERE payment_id = ?",
                            (excess_amount, payment_id)
                        )

            return rows_affected


    def list_by_sale(self, sale_id: str) -> list[sqlite3.Row]:
        """
        Return all payments for a given sale_id (chronological).
        """
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT *
                  FROM sale_payments
                 WHERE sale_id = ?
                 ORDER BY date ASC, payment_id ASC;
                """,
                (sale_id,),
            )
            return cur.fetchall()

    def get_latest_payment_for_sale(self, sale_id: str) -> sqlite3.Row | None:
        """
        Return the latest payment for a given sale_id (by date and payment_id).
        """
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT *
                  FROM sale_payments
                 WHERE sale_id = ?
                 ORDER BY date DESC, payment_id DESC
                 LIMIT 1;
                """,
                (sale_id,),
            )
            return cur.fetchone()

    def list_by_customer(self, customer_id: int) -> list[sqlite3.Row]:
        """
        Return all payments for all SALES belonging to a given customer.
        (Payments against quotations are disallowed by DB triggers, so this yields sales only.)
        """
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT sp.*
                  FROM sale_payments sp
                  JOIN sales s ON s.sale_id = sp.sale_id
                 WHERE s.customer_id = ?
                 ORDER BY sp.date ASC, sp.payment_id ASC;
                """,
                (customer_id,),
            )
            return cur.fetchall()

    def get(self, payment_id: int) -> Optional[sqlite3.Row]:
        """
        Fetch a single payment by id.
        """
        with self._connect() as con:
            cur = con.execute(
                "SELECT * FROM sale_payments WHERE payment_id = ?;",
                (payment_id,),
            )
            return cur.fetchone()


# Optional: convenience factory
def get_sale_payments_repo(db_path: str | Path) -> SalePaymentsRepo:
    return SalePaymentsRepo(db_path)
