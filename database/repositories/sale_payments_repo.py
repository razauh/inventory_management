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
        "Cash": "posted",
        "Bank Transfer": "posted",
        "Card": "posted",
        "Other": "posted",
        "Cheque": "pending",        # typically pending until cleared
        "Cash Deposit": "pending",  # typically pending until cleared
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

        elif method == "Cheque":
            # Incoming-only
            if amount <= 0:
                raise ValueError("Cheque must be a positive (incoming) amount.")
            if bank_account_id is None:
                raise ValueError("Cheque requires a company bank account.")
            if not instrument_no:
                raise ValueError("Cheque requires a cheque number.")
            if instrument_type != "cross_cheque":
                raise ValueError("Cheque must use instrument_type='cross_cheque'.")

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
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO sale_payments (
                    sale_id, date, amount, method,
                    bank_account_id, instrument_type, instrument_no,
                    instrument_date, deposited_date, cleared_date,
                    clearing_state, ref_no, notes, created_by
                ) VALUES (
                    :sale_id, COALESCE(:date, CURRENT_DATE), :amount, :method,
                    :bank_account_id, :instrument_type, :instrument_no,
                    :instrument_date, :deposited_date, :cleared_date,
                    :clearing_state, :ref_no, :notes, :created_by
                );
                """,
                {
                    "sale_id": sale_id,
                    "date": date,
                    "amount": amount,
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
            return int(cur.lastrowid)

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
        (Sales rollup does not depend on clearing state, but we keep lifecycle semantics.)
        """
        if clearing_state not in {"posted", "pending", "cleared", "bounced"}:
            raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")

        with self._connect() as con:
            con.execute(
                """
                UPDATE sale_payments
                   SET clearing_state = :clearing_state,
                       cleared_date   = :cleared_date,
                       deposited_date = :deposited_date,
                       instrument_date= :instrument_date,
                       notes          = COALESCE(:notes, notes),
                       ref_no         = COALESCE(:ref_no, ref_no)
                 WHERE payment_id = :payment_id;
                """,
                {
                    "clearing_state": clearing_state,
                    "cleared_date": cleared_date,
                    "deposited_date": deposited_date,
                    "instrument_date": instrument_date,
                    "notes": notes,
                    "ref_no": ref_no,
                    "payment_id": payment_id,
                },
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
