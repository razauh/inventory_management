from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .customer_advances_repo import CustomerAdvancesRepo


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

        with self._connect() as con:
            # Check if this is an overpayment and convert excess to customer credit
            # CRITICAL FIX: Only grant customer credit for payments that are already cleared
            # For pending payments, we calculate overpayment but don't convert to credit yet
            # Get sale information to determine what's due
            sale_info = con.execute(
                """
                SELECT
                    s.total_amount,
                    s.paid_amount,
                    s.advance_payment_applied,
                    c.customer_id
                FROM sales s
                JOIN customers c ON c.customer_id = s.customer_id
                WHERE s.sale_id = ?
                """,
                (sale_id,),
            ).fetchone()

            if not sale_info:
                raise ValueError(f"Sale not found: {sale_id}")

            total_amount = float(sale_info["total_amount"])
            current_paid = float(sale_info["paid_amount"])
            current_advance = float(sale_info["advance_payment_applied"]) if sale_info["advance_payment_applied"] else 0.0
            customer_id = int(sale_info["customer_id"])

            # Calculate excess amount immediately before INSERT using original amount
            amount_due = total_amount - current_paid - current_advance
            excess_amount = max(0, amount - amount_due)  # Using original unmodified amount

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
                    :clearing_state, :ref_no, :notes, :created_by, 0, :converted_to_credit
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
                    "converted_to_credit": excess_amount if excess_amount > 1e-9 else 0,  # Use epsilon for precision
                },
            )
            payment_id_of_new_record = int(cur.lastrowid)

            # Only grant customer credit and mark overpayment_converted if the payment is cleared
            # For pending payments, do not grant credit and do not mark overpayment_converted
            if excess_amount > 1e-9 and clearing_state == "cleared":  # Only if there's a meaningful excess and payment is cleared
                cadv = CustomerAdvancesRepo(con)
                cadv.grant_credit(
                    customer_id=customer_id,
                    amount=excess_amount,
                    date=date or None,
                    notes=f"Excess payment converted to credit on {sale_id}",
                    created_by=created_by,
                )
                # Mark that overpayment has been converted to prevent duplicate credits
                con.execute(
                    "UPDATE sale_payments SET overpayment_converted = 1 WHERE payment_id = ?",
                    (payment_id_of_new_record,)
                )

            return payment_id_of_new_record

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
    ) -> None:
        """
        Update the clearing_state (posted/pending/cleared/bounced) and optional dates.
        When changing to 'cleared', this will also process any overpayment as customer credit.
        """
        if clearing_state not in {"posted", "pending", "cleared", "bounced"}:
            raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")

        with self._connect() as con:
            # Get original values before update - this is atomic and will be part of our transaction
            original_values = con.execute(
                "SELECT sale_id, amount, method, clearing_state FROM sale_payments WHERE payment_id = ?;",
                (payment_id,),
            ).fetchone()

            if not original_values:
                raise ValueError(f"Payment not found: {payment_id}")

            old_clearing_state = original_values["clearing_state"]

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
                # Check if the current state is what we wanted
                current_state = con.execute(
                    "SELECT clearing_state FROM sale_payments WHERE payment_id = ?;",
                    (payment_id,),
                ).fetchone()

                if not current_state:
                    raise ValueError(f"Payment not found: {payment_id}")

                if current_state["clearing_state"] == clearing_state:
                    # State is already what we wanted, so return silently
                    return
                else:
                    # Another thread changed to a different state, operation failed
                    raise ValueError(f"Another operation changed payment {payment_id} state concurrently")

            # If we're changing the state TO 'cleared' from another state, check for overpayment
            if clearing_state == 'cleared' and old_clearing_state != 'cleared':
                # Check if this payment causes overpayment and convert excess to customer credit
                sale_id = original_values["sale_id"]
                payment_amount = float(original_values["amount"])

                # Get sale information to determine what's due
                sale_info = con.execute(
                    """
                    SELECT
                        s.total_amount,
                        s.paid_amount,  -- This may already include the payment if trigger ran
                        s.advance_payment_applied,
                        c.customer_id
                    FROM sales s
                    JOIN customers c ON c.customer_id = s.customer_id
                    WHERE s.sale_id = ?
                    """,
                    (sale_id,),
                ).fetchone()

                if sale_info:
                    total_amount = float(sale_info["total_amount"])
                    current_paid = float(sale_info["paid_amount"])  # This may include the payment we're clearing
                    current_advance = float(sale_info["advance_payment_applied"]) if sale_info["advance_payment_applied"] else 0.0
                    customer_id = int(sale_info["customer_id"])

                    # The trigger may have already updated paid_amount to include our payment_amount
                    # Initialize effective_current_paid to the current value in the database
                    # If transitioning from a non-cleared state to cleared, the DB trigger already updated
                    # sales.paid_amount to include this payment, so we need to subtract it to get the pre-payment value
                    effective_current_paid = current_paid
                    if old_clearing_state != 'cleared' and clearing_state == 'cleared':
                        # Since we just changed to cleared, the trigger would have included this payment in the current_paid
                        effective_current_paid = current_paid - payment_amount

                    # Calculate excess amount - the amount beyond what needs to be paid (total - advance)
                    total_amount_owed = total_amount - current_advance
                    total_paid_if_we_include_this = effective_current_paid + payment_amount
                    excess_amount = max(0.0, total_paid_if_we_include_this - total_amount_owed)

                    # Only grant as customer credit if there's actual excess and hasn't been converted before
                    if excess_amount > 1e-9:  # Only if there's a meaningful excess
                        # Check if this payment has already had its overpayment converted to credit
                        already_converted = con.execute(
                            "SELECT overpayment_converted FROM sale_payments WHERE payment_id = ?",
                            (payment_id,)
                        ).fetchone()["overpayment_converted"]

                        if not already_converted:
                            # Convert the excess to customer credit
                            cadv = CustomerAdvancesRepo(con)
                            cadv.grant_credit(
                                customer_id=customer_id,
                                amount=excess_amount,
                                date=cleared_date or None,
                                notes=f"Excess from cleared payment #{payment_id} on {sale_id}",
                                created_by=None,  # Use existing created_by or None
                            )
                            # Mark that overpayment has been converted to prevent duplicate credits
                            # and update the converted_to_credit amount
                            con.execute(
                                "UPDATE sale_payments SET overpayment_converted = 1, converted_to_credit = ? WHERE payment_id = ?",
                                (excess_amount, payment_id)
                            )


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
