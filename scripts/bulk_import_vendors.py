from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

try:
    from inventory_management.database.repositories.vendor_bank_accounts_repo import (
        VendorBankAccountsRepo,
    )
    from inventory_management.database.repositories.vendors_repo import VendorsRepo
except ModuleNotFoundError:
    from database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
    from database.repositories.vendors_repo import VendorsRepo


REQUIRED_HEADERS = (
    "Name",
    "Phone",
    "Address",
    "Bank1_Name",
    "Account1_Name",
    "Account1_Number",
    "Bank2_Name",
    "Account2_Name",
    "Account2_Number",
)
REQUIRED_COLUMNS = {
    "vendors": {"vendor_id", "name", "contact_info", "address"},
    "vendor_bank_accounts": {
        "vendor_bank_account_id",
        "vendor_id",
        "label",
        "bank_name",
        "account_no",
        "iban",
        "routing_no",
        "is_primary",
        "is_active",
    },
}


class ImportValidationError(Exception):
    def __init__(self, message: str, failed_count: int = 0):
        super().__init__(message)
        self.failed_count = failed_count


@dataclass(frozen=True)
class VendorBankAccountRow:
    label: str
    bank_name: str
    account_no: str


@dataclass(frozen=True)
class VendorRow:
    line_number: int
    name: str
    phone: str
    address: str | None
    accounts: tuple[VendorBankAccountRow, ...]


@dataclass(frozen=True)
class ImportResult:
    imported_count: int
    failed_count: int
    message: str


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value)


def _merged_bank_name(bank_name: str, account_name: str) -> str:
    bank = bank_name.strip()
    account = account_name.strip()
    if bank and account:
        return f"{bank}-{account}"
    return bank or account


def _load_vendor_rows(headers: list[str], rows: list[dict[str, object]]) -> list[VendorRow]:
    errors: list[str] = []
    failed_lines: set[int] = set()
    vendors: list[VendorRow] = []
    seen_names: dict[str, int] = {}

    if headers != list(REQUIRED_HEADERS):
        raise ImportValidationError(
            f"XLSX headers must be {list(REQUIRED_HEADERS)}, got {headers}."
        )

    for line_number, row in enumerate(rows, start=2):
        name = _cell_text(row.get("Name")).strip()
        phone = _cell_text(row.get("Phone")).strip()
        address = _cell_text(row.get("Address")).strip()

        if not any(_cell_text(row.get(header)).strip() for header in REQUIRED_HEADERS):
            continue

        if not name:
            errors.append(f"line {line_number}: Name is required")
            failed_lines.add(line_number)
        if not phone:
            errors.append(f"line {line_number}: Phone is required")
            failed_lines.add(line_number)

        name_key = name.casefold()
        if name and name_key in seen_names:
            errors.append(
                f"line {line_number}: duplicate vendor name {name!r}; "
                f"first seen on line {seen_names[name_key]}"
            )
            failed_lines.add(line_number)
        elif name:
            seen_names[name_key] = line_number

        accounts: list[VendorBankAccountRow] = []
        seen_account_labels: dict[str, int] = {}
        for account_index in (1, 2):
            bank = _cell_text(row.get(f"Bank{account_index}_Name")).strip()
            account_name = _cell_text(row.get(f"Account{account_index}_Name")).strip()
            account_no = _cell_text(row.get(f"Account{account_index}_Number")).strip()
            if not bank and not account_name and not account_no:
                continue
            if not bank:
                errors.append(
                    f"line {line_number}: Bank{account_index}_Name is required when account {account_index} is present"
                )
                failed_lines.add(line_number)
            if not account_no:
                errors.append(
                    f"line {line_number}: Account{account_index}_Number is required when account {account_index} is present"
                )
                failed_lines.add(line_number)
            label = _merged_bank_name(bank, account_name)
            label_key = label.casefold()
            if label and label_key in seen_account_labels:
                errors.append(
                    f"line {line_number}: duplicate bank account label {label!r}; "
                    f"first seen in account {seen_account_labels[label_key]}"
                )
                failed_lines.add(line_number)
            elif label:
                seen_account_labels[label_key] = account_index
            if bank and account_no:
                accounts.append(
                    VendorBankAccountRow(
                        label=label,
                        bank_name=label,
                        account_no=account_no,
                    )
                )

        vendors.append(
            VendorRow(
                line_number=line_number,
                name=name,
                phone=phone,
                address=address or None,
                accounts=tuple(accounts),
            )
        )

    if not vendors:
        errors.append("XLSX contains no vendor rows")
    if errors:
        failed_count = len(failed_lines) if failed_lines else len(vendors)
        raise ImportValidationError(
            "XLSX validation failed:\n- " + "\n- ".join(errors),
            failed_count=failed_count,
        )
    return vendors


def load_xlsx(xlsx_path: Path) -> list[VendorRow]:
    if xlsx_path.suffix.lower() != ".xlsx":
        raise ImportValidationError("Import file must be an .xlsx workbook.")
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportValidationError(
            "Missing Excel import dependency. Install pandas and openpyxl."
        ) from exc

    try:
        frame = pd.read_excel(
            xlsx_path,
            engine="openpyxl",
            dtype=object,
            keep_default_na=False,
            na_filter=False,
        )
    except ImportError as exc:
        raise ImportValidationError(
            "Missing Excel import dependency. Install pandas and openpyxl."
        ) from exc
    except Exception as exc:
        raise ImportValidationError(f"Could not read XLSX file: {exc}") from exc

    headers = [_cell_text(column).strip() for column in list(frame.columns)]
    return _load_vendor_rows(headers, frame.to_dict(orient="records"))


def validate_schema(conn: sqlite3.Connection) -> None:
    errors = []
    for table, required_columns in REQUIRED_COLUMNS.items():
        table_row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if table_row is None:
            errors.append(f"missing table {table!r}")
            continue
        actual_columns = {
            row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            errors.append(f"table {table!r} is missing columns {missing_columns}")
    if errors:
        raise ImportValidationError("Database schema is incompatible:\n- " + "\n- ".join(errors))


def validate_database_conflicts(conn: sqlite3.Connection, vendors: list[VendorRow]) -> None:
    existing_vendors: dict[str, str] = {}
    for (name,) in conn.execute("SELECT name FROM vendors"):
        key = (name or "").strip().casefold()
        if key:
            existing_vendors[key] = name

    conflicts = [
        f"line {vendor.line_number}: vendor {vendor.name!r} conflicts with existing {existing_vendors[vendor.name.casefold()]!r}"
        for vendor in vendors
        if vendor.name.casefold() in existing_vendors
    ]
    if conflicts:
        raise ImportValidationError(
            "Import would create duplicate vendors:\n- " + "\n- ".join(conflicts),
            failed_count=len(conflicts),
        )


def import_vendors(conn: sqlite3.Connection, vendors: list[VendorRow]) -> None:
    validate_database_conflicts(conn, vendors)
    vendor_repo = VendorsRepo(conn)
    bank_repo = VendorBankAccountsRepo(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        for vendor in vendors:
            vendor_id = vendor_repo.create(
                name=vendor.name,
                contact_info=vendor.phone,
                address=vendor.address,
            )
            for index, account in enumerate(vendor.accounts):
                bank_repo.create(
                    vendor_id,
                    {
                        "label": account.label,
                        "bank_name": account.bank_name,
                        "account_no": account.account_no,
                        "is_primary": 1 if index == 0 else 0,
                        "is_active": 1,
                    },
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def import_vendors_from_xlsx(conn: sqlite3.Connection, xlsx_path: Path) -> ImportResult:
    vendors = load_xlsx(xlsx_path)
    validate_schema(conn)
    import_vendors(conn, vendors)
    return ImportResult(
        imported_count=len(vendors),
        failed_count=0,
        message=f"Successfully imported {len(vendors)} vendors.",
    )
