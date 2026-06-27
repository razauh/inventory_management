from __future__ import annotations

import re
from pathlib import Path

from .dto import RuleDefinition

RULE_VERSION = "current"
RULE_INDEX_PATH = Path(__file__).resolve().parents[1] / "docs" / "accounting_rule_index.md"
_ROW_RE = re.compile(
    r"^\|\s*(ACC-RULE-\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|$"
)


def _area_from_file(source_file: str) -> str:
    if "/validators.py" in source_file:
        return "validation"
    if "/bank_rules.py" in source_file:
        return "bank"
    if "/purchase_rules.py" in source_file:
        return "purchase"
    if "/sales_rules.py" in source_file:
        return "sales"
    if "/customer_rules.py" in source_file:
        return "customer"
    if "/vendor_rules.py" in source_file:
        return "vendor"
    if "/inventory_rules.py" in source_file:
        return "inventory"
    if "/expense_rules.py" in source_file:
        return "expense"
    if "/reports/" in source_file:
        return "reporting"
    return "accounting"


def load_rule_registry(path: Path = RULE_INDEX_PATH) -> dict[str, RuleDefinition]:
    registry: dict[str, RuleDefinition] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        rule_id, name, source_file, source_line = match.groups()
        if rule_id in registry:
            continue
        registry[rule_id] = RuleDefinition(
            rule_id=rule_id,
            name=name.strip(),
            area=_area_from_file(source_file.strip()),
            version=RULE_VERSION,
            source_file=source_file.strip(),
            source_line=int(source_line),
        )
    return registry


RULE_REGISTRY = load_rule_registry()


def get_rule(rule_id: str) -> RuleDefinition:
    try:
        return RULE_REGISTRY[rule_id]
    except KeyError as exc:
        raise ValueError(f"Unknown accounting rule id: {rule_id}") from exc
