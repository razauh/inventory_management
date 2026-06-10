from __future__ import annotations
import sqlite3
from typing import Optional


# ----------------------------
# Domain errors (friendly)
# ----------------------------
class VendorAdvancesError(Exception):
    """Base class for vendor advances domain errors."""


class OverapplyVendorAdvanceError(VendorAdvancesError):
    """Attempted to apply more credit than a purchase's remaining due."""


class InsufficientVendorCreditError(VendorAdvancesError):
    """Attempted to apply more credit than the vendor has available."""


class InvalidPurchaseReferenceError(VendorAdvancesError):
    """Provided purchase_id does not exist (or is not usable)."""


class ConstraintViolationError(VendorAdvancesError):
    """Fallback for other constraint violations; wraps the original SQLite error."""
    def __init__(self, message: str, *, original: BaseException | None = None):
        super().__init__(message)
        self.original = original


class VendorAdvancesRepo:
    METHODS = {"Cash", "Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit", "Other"}
    ITYPES = {"online", "cheque", "cross_cheque", "cash_deposit", "pay_order", "other"}
    CLEARING_STATES = {"cleared"}

    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn
        # small epsilon to mirror SQL triggers' tolerance
        self._eps = 1e-9

    # ---------- Apply existing credit to a purchase (−amount) ----------
    def apply_credit_to_purchase(
        self,
        vendor_id: int,
        purchase_id: str,
        amount: float,
        *,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
    ) -> int:
        """
        Apply existing vendor credit to a purchase: stored as NEGATIVE amount
        with source_type='applied_to_purchase'. Triggers enforce no overdraw and
        roll up purchases.advance_payment_applied. No commit here.

        Raises:
            ValueError                        : if amount <= 0
            InvalidPurchaseReferenceError     : if purchase_id is unknown or belongs to another vendor
            InsufficientVendorCreditError     : if vendor credit < amount
            OverapplyVendorAdvanceError       : if amount > remaining due on purchase
            ConstraintViolationError          : other DB constraint violations
        """
        if amount <= 0:
            raise ValueError("amount must be positive when applying credit")

        # --- pre-validate against DB state (friendly errors) ---
        remaining_due = self._get_purchase_remaining_due(purchase_id, vendor_id)
        if remaining_due is None:
            raise InvalidPurchaseReferenceError(
                "Invalid purchase reference for vendor credit application"
            )

        # Current available vendor credit (from view)
        available_credit = self.get_balance(vendor_id)

        if available_credit + self._eps < float(amount):
            raise InsufficientVendorCreditError(
                f"Insufficient vendor credit: have {available_credit:.2f}, tried to apply {amount:.2f}"
            )

        if float(amount) - remaining_due > self._eps:
            raise OverapplyVendorAdvanceError(
                f"Cannot apply {amount:.2f} beyond remaining due {remaining_due:.2f} for purchase {purchase_id}"
            )

        # --- perform insert; map any trigger violations to domain errors ---
        applied = -abs(float(amount))
        try:
            cur = self.conn.execute(
                """
                INSERT INTO vendor_advances (
                    vendor_id, tx_date, amount, source_type, source_id, notes, created_by
                )
                VALUES (?, ?, ?, 'applied_to_purchase', ?, ?, ?)
                """,
                (vendor_id, date, applied, purchase_id, notes, created_by),
            )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            # Map well-known trigger messages
            self._raise_mapped_error(e)
        except sqlite3.OperationalError as e:
            # Some SQLite builds surface RAISE(ABORT, ...) here
            self._raise_mapped_error(e)

        # mypy: unreachable, _raise_mapped_error always raises
        raise AssertionError("unreachable")

    # ---------- Grant new credit (+amount) ----------
    def grant_credit(
        self,
        vendor_id: int,
        amount: float,
        *,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
        source_id: Optional[str] = None,
        # Default to manual credit (deposit); callers may pass 'return_credit' for returns.
        source_type: str = "deposit",
        method: Optional[str] = None,
        bank_account_id: Optional[int] = None,
        vendor_bank_account_id: Optional[int] = None,
        instrument_type: Optional[str] = None,
        instrument_no: Optional[str] = None,
        instrument_date: Optional[str] = None,
        deposited_date: Optional[str] = None,
        cleared_date: Optional[str] = None,
        clearing_state: Optional[str] = None,
        ref_no: Optional[str] = None,
        temp_vendor_bank_name: Optional[str] = None,
        temp_vendor_bank_number: Optional[str] = None,
        **_ignore,
    ) -> int:
        """
        Grant vendor credit (+amount).

        Default behavior (no source_type passed) records a manual credit/deposit:
            source_type = 'deposit'
        This represents a credit not tied to a stock return.

        For credits created by a purchase return flow, pass:
            source_type = 'return_credit'
        (Those are typically invoked by the returns orchestration.)

        Notes:
          - This method does not commit; caller controls the transaction.
          - 'applied_to_purchase' is handled by apply_credit_to_purchase(...).
        """
        if amount <= 0:
            raise ValueError("amount must be positive when granting credit")

        allowed_types = {"deposit", "return_credit"}
        st = (source_type or "deposit").lower()
        if st not in allowed_types:
            raise ValueError(f"source_type must be one of {allowed_types}, got {source_type!r}")
        self._validate_payment_metadata(
            vendor_id=vendor_id,
            method=method,
            bank_account_id=bank_account_id,
            vendor_bank_account_id=vendor_bank_account_id,
            instrument_type=instrument_type,
            clearing_state=clearing_state,
        )

        metadata_values = {
            "method": method,
            "bank_account_id": bank_account_id,
            "vendor_bank_account_id": vendor_bank_account_id,
            "instrument_type": instrument_type,
            "instrument_no": instrument_no,
            "instrument_date": instrument_date,
            "deposited_date": deposited_date,
            "cleared_date": cleared_date,
            "clearing_state": clearing_state,
            "ref_no": ref_no,
            "temp_vendor_bank_name": temp_vendor_bank_name,
            "temp_vendor_bank_number": temp_vendor_bank_number,
        }
        existing_cols = self._vendor_advances_columns()
        metadata_cols = [col for col, value in metadata_values.items() if value is not None]
        missing_cols = [col for col in metadata_cols if col not in existing_cols]
        if missing_cols:
            raise ValueError(
                "Vendor advance payment metadata columns are missing: "
                + ", ".join(sorted(missing_cols))
            )

        try:
            columns = ["vendor_id", "tx_date", "amount", "source_type", "source_id"]
            values: list[object] = [vendor_id, date, float(amount), st, source_id]
            for col, value in metadata_values.items():
                if col in existing_cols:
                    columns.append(col)
                    values.append(value)
            columns.extend(["notes", "created_by"])
            values.extend([notes, created_by])

            placeholders = ", ".join("?" for _ in columns)
            cur = self.conn.execute(
                f"""
                INSERT INTO vendor_advances (
                    {", ".join(columns)}
                )
                VALUES ({placeholders})
                """,
                values,
            )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            # Defensive: map any constraint violations
            self._raise_mapped_error(e)
        except sqlite3.OperationalError as e:
            self._raise_mapped_error(e)

        raise AssertionError("unreachable")

    # Convenience wrapper for clarity at call sites
    def grant_deposit(
        self,
        vendor_id: int,
        amount: float,
        *,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
        source_id: Optional[str] = None,
    ) -> int:
        """Shorthand for a manual credit/deposit (source_type='deposit')."""
        return self.grant_credit(
            vendor_id,
            amount,
            date=date,
            notes=notes,
            created_by=created_by,
            source_id=source_id,
            source_type="deposit",
        )

    # ---------- Balances ----------
    def get_balance(self, vendor_id: int) -> float:
        """
        Current credit balance from view v_vendor_advance_balance.
        +ve = you hold credit from the vendor; 0 = none.
        (Negative shouldn't occur under triggers.)
        """
        row = self.conn.execute(
            "SELECT balance FROM v_vendor_advance_balance WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchone()
        if not row:
            return 0.0
        return float(row["balance"] if isinstance(row, sqlite3.Row) else row[0])

    # Alias per spec
    def balance(self, vendor_id: int) -> float:
        return self.get_balance(vendor_id)

    def get_opening_balance(self, vendor_id: int, as_of: str) -> float:
        """
        Opening balance BEFORE a given date: SUM(amount) WHERE tx_date < DATE(as_of).
        Useful for statements with a date range.
        """
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0)
            FROM vendor_advances
            WHERE vendor_id = ? AND DATE(tx_date) < DATE(?)
            """,
            (vendor_id, as_of),
        ).fetchone()
        return float(row[0] if row else 0.0)

    # ---------- Ledger / statements ----------
    def list_ledger(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        Full ledger for a vendor, filtered by date range if provided.
        Ordered ASC by (tx_date, tx_id).

        Also accepts a tuple/list for date_from as (from, to) when date_to is None,
        for backward compatibility with callers that pass a single tuple.
        Return fields: tx_id, tx_date, amount, source_type, source_id, notes, created_by.
        Statement semantics:
          - source_type='return_credit'        → "Credit Note" (reduces payable)
          - source_type='applied_to_purchase'  → "Credit Applied" to source_id (reduces payable)
          - source_type='deposit'              → Manual credit/deposit (reduces payable)
        """
        # Back-compat: allow date_from to be a (from, to) tuple/list if date_to not provided
        if isinstance(date_from, (tuple, list)) and len(date_from) == 2 and date_to is None:
            df, dt = date_from
            date_from, date_to = df, dt

        sql = [
            """
            SELECT
              va.tx_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.method,
              va.bank_account_id,
              va.vendor_bank_account_id,
              va.instrument_type,
              va.instrument_no,
              va.instrument_date,
              va.deposited_date,
              va.cleared_date,
              va.clearing_state,
              va.ref_no,
              va.temp_vendor_bank_name,
              va.temp_vendor_bank_number,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.vendor_id = ?
            """
        ]
        params: list[object] = [vendor_id]

        if date_from:
            sql.append("AND DATE(va.tx_date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql.append("AND DATE(va.tx_date) <= DATE(?)")
            params.append(date_to)

        sql.append("ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC")
        return self.conn.execute("\n".join(sql), params).fetchall()

    def list_credit_applications_for_purchase(self, purchase_id: str) -> list[dict]:
        """
        All applications of vendor credit against a particular purchase.
        Rows from vendor_advances where source_type='applied_to_purchase' AND source_id=purchase_id.
        """
        return self.conn.execute(
            """
            SELECT
              va.tx_id,
              va.vendor_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.method,
              va.bank_account_id,
              va.vendor_bank_account_id,
              va.instrument_type,
              va.instrument_no,
              va.instrument_date,
              va.deposited_date,
              va.cleared_date,
              va.clearing_state,
              va.ref_no,
              va.temp_vendor_bank_name,
              va.temp_vendor_bank_number,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.source_type = 'applied_to_purchase'
              AND va.source_id = ?
            ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC
            """,
            (purchase_id,),
        ).fetchall()

    def list_credit_notes(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        All credit-note entries (source_type='return_credit') for a vendor, optional date range.
        (Manual deposits are not included here.)
        """
        sql = [
            """
            SELECT
              va.tx_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.method,
              va.bank_account_id,
              va.vendor_bank_account_id,
              va.instrument_type,
              va.instrument_no,
              va.instrument_date,
              va.deposited_date,
              va.cleared_date,
              va.clearing_state,
              va.ref_no,
              va.temp_vendor_bank_name,
              va.temp_vendor_bank_number,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.vendor_id = ?
              AND va.source_type = 'return_credit'
            """
        ]
        params: list[object] = [vendor_id]

        if date_from:
            sql.append("AND DATE(va.tx_date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql.append("AND DATE(va.tx_date) <= DATE(?)")
            params.append(date_to)

        sql.append("ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC")
        return self.conn.execute("\n".join(sql), params).fetchall()

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _validate_payment_metadata(
        self,
        *,
        vendor_id: int,
        method: Optional[str],
        bank_account_id: Optional[int],
        vendor_bank_account_id: Optional[int],
        instrument_type: Optional[str],
        clearing_state: Optional[str],
    ) -> None:
        if method is not None and method not in self.METHODS:
            raise ValueError(f"Invalid vendor advance payment method: {method}")
        if instrument_type is not None and instrument_type not in self.ITYPES:
            raise ValueError(f"Invalid vendor advance instrument type: {instrument_type}")
        if clearing_state is not None and clearing_state != "cleared":
            raise ValueError("Vendor outgoing payments must have clearing_state='cleared'")

        if bank_account_id is not None:
            row = self.conn.execute(
                "SELECT is_active FROM company_bank_accounts WHERE account_id = ?",
                (bank_account_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Company bank account not found: {bank_account_id}")
            if int(row["is_active"]) != 1:
                raise ValueError(
                    "Selected company bank account is inactive and cannot be used for new transactions."
                )

        if vendor_bank_account_id is not None:
            row = self.conn.execute(
                """
                SELECT vendor_id, is_active
                  FROM vendor_bank_accounts
                 WHERE vendor_bank_account_id = ?
                """,
                (vendor_bank_account_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Vendor bank account not found: {vendor_bank_account_id}")
            if int(row["vendor_id"]) != int(vendor_id):
                raise ValueError("Vendor bank account does not belong to the advance vendor")
            if int(row["is_active"]) != 1:
                raise ValueError(
                    "Selected vendor bank account is inactive and cannot be used for new transactions."
                )

    def _vendor_advances_columns(self) -> set[str]:
        rows = self.conn.execute("PRAGMA table_info(vendor_advances);").fetchall()
        return {str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) for row in rows}

    def _get_purchase_remaining_due(self, purchase_id: str, vendor_id: int) -> Optional[float]:
        """
        Returns remaining due for the purchase as:
            net_total_after_returns - paid_amount - advance_payment_applied
        or None if the purchase is missing or belongs to another vendor.
        """
        row = self.conn.execute(
            """
            SELECT
              CAST(COALESCE(pdt.calculated_total_amount, p.total_amount) AS REAL) AS total_amount,
              CAST(p.paid_amount AS REAL)             AS paid_amount,
              CAST(p.advance_payment_applied AS REAL) AS advance_applied
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ? AND p.vendor_id = ?
            """,
            (purchase_id, vendor_id),
        ).fetchone()
        if not row:
            return None
        total = float(row["total_amount"])
        paid = float(row["paid_amount"])
        adv  = float(row["advance_applied"])
        return max(0.0, total - paid - adv)

    def _raise_mapped_error(self, e: sqlite3.Error) -> None:
        """
        Translate known SQLite trigger messages to domain errors.
        Always raises; never returns.
        """
        msg = (e.args[0] if e.args else "") or ""
        normalized = msg.lower()

        # Match messages used in schema triggers
        if "insufficient vendor credit" in normalized:
            raise InsufficientVendorCreditError(msg) from e
        if "cannot apply credit beyond remaining due" in normalized:
            raise OverapplyVendorAdvanceError(msg) from e
        if "invalid purchase reference for vendor credit application" in normalized:
            raise InvalidPurchaseReferenceError(msg) from e

        # Fallback
        raise ConstraintViolationError(msg or "Constraint violation while saving vendor advance", original=e) from e
