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
    pass


@dataclass(frozen=True)
class ProductRow:
    line_number: int
    name: str
    base_unit: str
    alt_unit: str | None
    category: str | None
    factor_to_base: float | None


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


def load_csv(csv_path: Path) -> list[ProductRow]:
    errors: list[str] = []
    products: list[ProductRow] = []
    seen_names: dict[str, int] = {}
    seen_uoms: dict[str, str] = {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != list(REQUIRED_HEADERS):
            raise ImportValidationError(
                f"CSV headers must be {list(REQUIRED_HEADERS)}, got {reader.fieldnames}."
            )

        for line_number, row in enumerate(reader, start=2):
            if None in row:
                errors.append(f"line {line_number}: too many columns")
                continue

            name = (row["name"] or "").strip()
            base_unit = (row["base_unit"] or "").strip()
            alt_unit = (row["alt_unit"] or "").strip()
            category = (row["Category"] or "").strip()
            factor_text = (row["Factor"] or "").strip()

            if not name:
                errors.append(f"line {line_number}: name is required")
            if not base_unit:
                errors.append(f"line {line_number}: base_unit is required")

            name_key = name.casefold()
            if name and name_key in seen_names:
                errors.append(
                    f"line {line_number}: duplicate product name {name!r}; "
                    f"first seen on line {seen_names[name_key]}"
                )
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
                else:
                    seen_uoms[unit_key] = unit

            factor_to_base = None
            if bool(alt_unit) != bool(factor_text):
                errors.append(
                    f"line {line_number}: alt_unit and Factor must either both be set or both be empty"
                )
            elif alt_unit and factor_text:
                if alt_unit.casefold() == base_unit.casefold():
                    errors.append(
                        f"line {line_number}: alternate UoM must differ from base UoM"
                    )
                try:
                    units_per_base = float(factor_text)
                except ValueError:
                    errors.append(f"line {line_number}: invalid Factor {factor_text!r}")
                else:
                    if not math.isfinite(units_per_base) or units_per_base <= 0:
                        errors.append(
                            f"line {line_number}: Factor must be a finite number greater than zero"
                        )
                    else:
                        factor_to_base = 1.0 / units_per_base
                        if not math.isfinite(factor_to_base) or factor_to_base <= 0:
                            errors.append(
                                f"line {line_number}: Factor is too large to convert safely"
                            )

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
        errors.append("CSV contains no product rows")
    if errors:
        raise ImportValidationError("CSV validation failed:\n- " + "\n- ".join(errors))
    return products


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
            "Import would create duplicate products:\n- " + "\n- ".join(conflicts)
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
