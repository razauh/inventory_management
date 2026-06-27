from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    name: str
    area: str
    version: str
    source_file: str
    source_line: int | None = None


@dataclass(frozen=True)
class AuditEventDraft:
    rule_id: str
    event_type: str
    source_type: str
    source_id: str | int | None
    source_label: str | None = None
    party_type: str | None = None
    party_id: int | None = None
    party_name: str | None = None
    amount: Decimal | float | int | str | None = None
    currency: str = "PKR"
    business_date: str | None = None
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    output_snapshot: dict[str, Any] = field(default_factory=dict)
    side_effects: dict[str, Any] = field(default_factory=dict)
    human_summary: str = ""
    technical_summary: str = ""
    source_module: str = ""
    source_function: str = ""


@dataclass(frozen=True)
class AuditEventRow:
    audit_event_id: int
    created_at: str
    rule_id: str
    rule_name: str
    rule_area: str
    rule_version: str
    event_type: str
    source_type: str
    source_id: str | None
    source_label: str | None
    party_type: str | None
    party_id: int | None
    party_name: str | None
    amount: Decimal | None
    currency: str
    business_date: str
    input_snapshot: dict[str, Any]
    output_snapshot: dict[str, Any]
    side_effects: dict[str, Any]
    human_summary: str
    technical_summary: str
    source_module: str
    source_function: str
    review_status: str
    review_notes: str | None
    expected_behavior: str | None
    linked_issue: str | None


@dataclass(frozen=True)
class AuditReviewRow:
    review_id: int
    audit_event_id: int
    status: str
    notes: str | None
    expected_behavior: str | None
    linked_issue: str | None
    reviewed_by: int | None
    reviewed_at: str
