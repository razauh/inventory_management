from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "myshop.db"
DEFAULT_CSV_PATH = ROOT_DIR / ".docs" / "productscsv.csv"
REQUIRED_HEADERS = ("name", "base_unit", "alt_unit", "Category", "Factor")
REQUIRED_COLUMNS = {
    "products": {"product_id", "name", "description", "category", "min_stock_level"},
    "uoms": {"uom_id", "unit_name"},
    "product_uoms": {
        "product_uom_id",
        "product_id",
        "uom_id",
        "is_base",
        "factor_to_base",
    },
}


class ImportValidationError(Exception):
    def __init__(self, message: str, failed_count: int = 0):
        super().__init__(message)
        self.failed_count = failed_count


@dataclass(frozen=True)
class ProductRow:
    line_number: int
    name: str
    base_unit: str
    alt_unit: str | None
    category: str | None
    factor_to_base: float | None


@dataclass(frozen=True)
class ImportResult:
    imported_count: int
    failed_count: int
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import products and UoM mappings from CSV atomically."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate the CSV, schema, and duplicate conflicts without inserting data.",
    )
    return parser.parse_args()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _load_product_rows(
    source_name: str,
    headers: list[str] | None,
    rows: list[dict[str, object]],
) -> list[ProductRow]:
    errors: list[str] = []
    failed_lines: set[int] = set()
    products: list[ProductRow] = []
    seen_names: dict[str, int] = {}
    seen_uoms: dict[str, str] = {}

    expected_headers = list(REQUIRED_HEADERS)
    normalized_headers = [(_cell_text(header).strip().casefold()) for header in (headers or [])]
    normalized_expected = [header.casefold() for header in expected_headers]
    if normalized_headers != normalized_expected:
        raise ImportValidationError(
            f"{source_name} headers must be {expected_headers}, got {headers}."
        )

    for line_number, row in enumerate(rows, start=2):
        row_by_header = {
            _cell_text(key).strip().casefold(): value
            for key, value in row.items()
        }

        name = _cell_text(row_by_header.get("name")).strip()
        base_unit = _cell_text(row_by_header.get("base_unit")).strip()
        alt_unit = _cell_text(row_by_header.get("alt_unit")).strip()
        category = _cell_text(row_by_header.get("category")).strip()
        factor_text = _cell_text(row_by_header.get("factor")).strip()

        if not name and not base_unit and not alt_unit and not category and not factor_text:
            continue

        if not name:
            errors.append(f"line {line_number}: name is required")
            failed_lines.add(line_number)
        if not base_unit:
            errors.append(f"line {line_number}: base_unit is required")
            failed_lines.add(line_number)

        name_key = name.casefold()
        if name and name_key in seen_names:
            errors.append(
                f"line {line_number}: duplicate product name {name!r}; "
                f"first seen on line {seen_names[name_key]}"
            )
            failed_lines.add(line_number)
        elif name:
            seen_names[name_key] = line_number

        for unit in (base_unit, alt_unit):
            if not unit:
                continue
            unit_key = unit.casefold()
            previous = seen_uoms.get(unit_key)
            if previous is not None and previous != unit:
                errors.append(
                    f"line {line_number}: UoM {unit!r} conflicts by case with {previous!r}"
                )
                failed_lines.add(line_number)
            else:
                seen_uoms[unit_key] = unit

        factor_to_base = None
        if alt_unit and not factor_text:
            errors.append(
                f"line {line_number}: Factor is required when alt_unit is set"
            )
            failed_lines.add(line_number)
        elif alt_unit and factor_text:
            if alt_unit.casefold() == base_unit.casefold():
                errors.append(
                    f"line {line_number}: alternate UoM must differ from base UoM"
                )
                failed_lines.add(line_number)
            try:
                units_per_base = float(factor_text)
            except ValueError:
                errors.append(f"line {line_number}: invalid Factor {factor_text!r}")
                failed_lines.add(line_number)
            else:
                if not math.isfinite(units_per_base) or units_per_base <= 0:
                    errors.append(
                        f"line {line_number}: Factor must be a finite number greater than zero"
                    )
                    failed_lines.add(line_number)
                else:
                    factor_to_base = 1.0 / units_per_base
                    if not math.isfinite(factor_to_base) or factor_to_base <= 0:
                        errors.append(
                            f"line {line_number}: Factor is too large to convert safely"
                        )
                        failed_lines.add(line_number)

        products.append(
            ProductRow(
                line_number=line_number,
                name=name,
                base_unit=base_unit,
                alt_unit=alt_unit or None,
                category=category or None,
                factor_to_base=factor_to_base,
            )
        )

    if not products:
        errors.append(f"{source_name} contains no product rows")
    if errors:
        failed_count = len(failed_lines) if failed_lines else len(products)
        raise ImportValidationError(
            f"{source_name} validation failed:\n- " + "\n- ".join(errors),
            failed_count=failed_count,
        )
    return products


def load_csv(csv_path: Path) -> list[ProductRow]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows: list[dict[str, object]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ImportValidationError(
                    f"CSV validation failed:\n- line {line_number}: too many columns",
                    failed_count=1,
                )
            rows.append(dict(row))
    return _load_product_rows("CSV", reader.fieldnames, rows)


def load_xlsx(xlsx_path: Path) -> list[ProductRow]:
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
    data_rows = frame.to_dict(orient="records")
    return _load_product_rows("XLSX", headers, data_rows)


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


def validate_database_conflicts(
    conn: sqlite3.Connection, products: list[ProductRow]
) -> dict[str, int]:
    existing_products: dict[str, str] = {}
    for (name,) in conn.execute("SELECT name FROM products"):
        key = (name or "").strip().casefold()
        if key:
            existing_products[key] = name

    conflicts = [
        f"line {product.line_number}: product {product.name!r} conflicts with existing {existing_products[product.name.casefold()]!r}"
        for product in products
        if product.name.casefold() in existing_products
    ]
    if conflicts:
        raise ImportValidationError(
            "Import would create duplicate products:\n- " + "\n- ".join(conflicts),
            failed_count=len(conflicts),
        )

    uom_ids: dict[str, int] = {}
    existing_uoms: dict[str, tuple[str, int]] = {}
    for uom_id, unit_name in conn.execute("SELECT uom_id, unit_name FROM uoms"):
        key = unit_name.strip().casefold()
        if key in existing_uoms and existing_uoms[key][0] != unit_name:
            raise ImportValidationError(
                f"Database contains ambiguous UoMs {existing_uoms[key][0]!r} and {unit_name!r}."
            )
        existing_uoms[key] = (unit_name, int(uom_id))

    for product in products:
        for unit_name in (product.base_unit, product.alt_unit):
            if unit_name is None:
                continue
            existing = existing_uoms.get(unit_name.casefold())
            if existing is not None:
                uom_ids[unit_name] = existing[1]
    return uom_ids


def resolve_uom_id(
    conn: sqlite3.Connection, unit_name: str, known_uom_ids: dict[str, int]
) -> int:
    known_id = known_uom_ids.get(unit_name)
    if known_id is not None:
        return known_id
    cursor = conn.execute("INSERT INTO uoms (unit_name) VALUES (?)", (unit_name,))
    uom_id = int(cursor.lastrowid)
    known_uom_ids[unit_name] = uom_id
    return uom_id


def import_products(
    conn: sqlite3.Connection,
    products: list[ProductRow],
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        known_uom_ids = validate_database_conflicts(conn, products)
        for product in products:
            base_uom_id = resolve_uom_id(conn, product.base_unit, known_uom_ids)
            cursor = conn.execute(
                "INSERT INTO products (name, description, category, min_stock_level) "
                "VALUES (?, NULL, ?, 0)",
                (product.name, product.category),
            )
            product_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO product_uoms "
                "(product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
                (product_id, base_uom_id),
            )

            if product.alt_unit is not None and product.factor_to_base is not None:
                alt_uom_id = resolve_uom_id(conn, product.alt_unit, known_uom_ids)
                conn.execute(
                    "INSERT INTO product_uoms "
                    "(product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 0, ?)",
                    (product_id, alt_uom_id, product.factor_to_base),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def import_products_from_xlsx(conn: sqlite3.Connection, xlsx_path: Path) -> ImportResult:
    products = load_xlsx(xlsx_path)
    validate_schema(conn)
    import_products(conn, products)
    return ImportResult(
        imported_count=len(products),
        failed_count=0,
        message=f"Successfully imported {len(products)} products.",
    )


def main() -> int:
    args = parse_args()
    csv_path = args.csv.expanduser().resolve()
    db_path = args.db.expanduser().resolve()

    if not csv_path.is_file():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1
    if not db_path.is_file():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1

    try:
        products = load_csv(csv_path)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            validate_schema(conn)
            if args.check_only:
                validate_database_conflicts(conn, products)
                print(f"Validation passed for {len(products)} products; no data was inserted.")
                return 0
            import_products(conn, products)
        finally:
            conn.close()
    except (ImportValidationError, OSError, sqlite3.Error) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(f"Successfully imported {len(products)} products into {db_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
