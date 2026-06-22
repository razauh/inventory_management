from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Optional

from modules.accounting import AccountingService, CustomerPaymentPayload


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
        "Cross Cheque": "cross_cheque",
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

    NORMAL_CLEARING_TRANSITIONS: set[tuple[str, str]] = {
        ("posted", "pending"),
        ("pending", "cleared"),
        ("pending", "bounced"),
    }

    def __init__(self, db_path: str | Path | sqlite3.Connection):
        if isinstance(db_path, sqlite3.Connection):
            self.conn = db_path
            self.db_path = None
        else:
            self.db_path = str(db_path)
            self.conn = None

    # --- connection helper -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self.conn is not None:
            class ConnectionWrapper:
                def __init__(self, conn):
                    self.conn = conn
                def __enter__(self):
                    return self.conn
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            return ConnectionWrapper(self.conn)
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
        method, amount, bank_account_id, instrument_type, instrument_no = self._normalize_and_validate(
            method=method, amount=amount, bank_account_id=bank_account_id,
            instrument_type=instrument_type, instrument_no=instrument_no,
        )
        if not clearing_state:
            clearing_state = self.DEFAULT_CLEARING_STATE_BY_METHOD.get(method, "posted")
        result = AccountingService(con).record_customer_payment_event(
            CustomerPaymentPayload(
                sale_id=sale_id,
                customer_id=0,
                amount=Decimal(str(amount)),
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
        )
        return result.payment_id

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
        cleared_date: Optional[str] = None,
        deposited_date: Optional[str] = None,
        instrument_date: Optional[str] = None,
        notes: Optional[str] = None,
        ref_no: Optional[str] = None,
    ) -> int:
        with self._connect() as con:
            svc = AccountingService(con)
            return svc.update_customer_payment_state(
                payment_id, clearing_state=clearing_state,
                cleared_date=cleared_date, notes=notes,
            )

    def reopen_clearing_state(
        self,
        payment_id: int,
        *,
        admin_user_id: int,
        reason: str,
    ) -> int:
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("A reversal reason is required")

        with self._connect() as con:
            admin = con.execute(
                "SELECT role, is_active FROM users WHERE user_id = ?",
                (admin_user_id,),
            ).fetchone()
            if not admin or str(admin["role"]).lower() != "admin" or int(admin["is_active"] or 0) != 1:
                raise ValueError("Payment state reversal requires an active admin user")

            svc = AccountingService(con)
            result = svc.reopen_customer_payment_state(payment_id, reason=reason)

            # Audit trail in repo scope
            con.execute(
                "INSERT INTO sale_payment_state_reversals (payment_id, old_state, new_state, admin_user_id, reason) "
                "VALUES (?, (SELECT clearing_state FROM sale_payments WHERE payment_id = ?), 'pending', ?, ?)",
                (payment_id, payment_id, admin_user_id, reason),
            )
            return result


    def list_by_sale(self, sale_id: str) -> list[sqlite3.Row]:
        with self._connect() as con:
            svc = AccountingService(con)
            return [dict(
                payment_id=r.payment_id,
                sale_id=r.sale_id,
                date=r.date,
                amount=float(r.amount),
                method=r.method,
                bank_account_id=r.bank_account_id,
                instrument_type=r.instrument_type,
                instrument_no=r.instrument_no,
                instrument_date=r.instrument_date,
                deposited_date=r.deposited_date,
                cleared_date=r.cleared_date,
                clearing_state=r.clearing_state,
                ref_no=r.ref_no,
                notes=r.notes,
                created_by=r.created_by,
                bank_account_label=r.bank_account_label,
            ) for r in svc.get_sale_payment_history(sale_id)]

    def get_latest_payment_for_sale(self, sale_id: str) -> sqlite3.Row | None:
        with self._connect() as con:
            svc = AccountingService(con)
            r = svc.get_latest_sale_payment(sale_id)
            if r is None:
                return None
            return dict(
                payment_id=r.payment_id,
                sale_id=r.sale_id,
                date=r.date,
                amount=float(r.amount),
                method=r.method,
                bank_account_id=r.bank_account_id,
                instrument_type=r.instrument_type,
                instrument_no=r.instrument_no,
                instrument_date=r.instrument_date,
                deposited_date=r.deposited_date,
                cleared_date=r.cleared_date,
                clearing_state=r.clearing_state,
                ref_no=r.ref_no,
                notes=r.notes,
                created_by=r.created_by,
                bank_account_label=r.bank_account_label,
            )

    def list_by_customer(self, customer_id: int) -> list[sqlite3.Row]:
        with self._connect() as con:
            svc = AccountingService(con)
            return [dict(
                payment_id=r.payment_id,
                sale_id=r.sale_id,
                date=r.date,
                amount=float(r.amount),
                method=r.method,
                bank_account_id=r.bank_account_id,
                instrument_type=r.instrument_type,
                instrument_no=r.instrument_no,
                instrument_date=r.instrument_date,
                deposited_date=r.deposited_date,
                cleared_date=r.cleared_date,
                clearing_state=r.clearing_state,
                ref_no=r.ref_no,
                notes=r.notes,
                created_by=r.created_by,
                bank_account_label=r.bank_account_label,
            ) for r in svc.get_customer_payment_history(customer_id)]

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
