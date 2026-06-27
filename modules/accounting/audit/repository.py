from __future__ import annotations

import csv
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from modules.reporting.csv_export import safe_csv_row

from .dto import AuditEventDraft, AuditEventRow, AuditReviewRow
from .rules import get_rule
from .serialization import from_json_text, to_json_text

REVIEW_STATUSES = {
    "unreviewed",
    "accepted",
    "data_entry_error",
    "unclear",
    "needs_rule_change",
    "manager_decision",
    "resolved",
}


class AccountingAuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_event(self, draft: AuditEventDraft) -> int:
        rule = get_rule(draft.rule_id)
        cur = self.conn.execute(
            """
            INSERT INTO accounting_rule_audit_events (
              rule_id, rule_name, rule_area, rule_version,
              event_type, source_type, source_id, source_label,
              party_type, party_id, party_name, amount, currency,
              business_date, input_snapshot_json, output_snapshot_json,
              side_effects_json, human_summary, technical_summary,
              source_module, source_function
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_DATE),
                    ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.rule_id,
                rule.name,
                rule.area,
                rule.version,
                draft.event_type,
                draft.source_type,
                None if draft.source_id is None else str(draft.source_id),
                draft.source_label,
                draft.party_type,
                draft.party_id,
                draft.party_name,
                None if draft.amount is None else str(draft.amount),
                draft.currency or "PKR",
                draft.business_date,
                to_json_text(draft.input_snapshot),
                to_json_text(draft.output_snapshot),
                to_json_text(draft.side_effects),
                draft.human_summary,
                draft.technical_summary,
                draft.source_module,
                draft.source_function,
            ),
        )
        return int(cur.lastrowid)

    def get_event(self, audit_event_id: int) -> AuditEventRow | None:
        row = self.conn.execute(
            """
            SELECT e.*, r.status AS review_status, r.notes AS review_notes,
                   r.expected_behavior, r.linked_issue
            FROM accounting_rule_audit_events e
            LEFT JOIN accounting_rule_audit_reviews r
              ON r.audit_event_id = e.audit_event_id
             AND r.review_id = (
                SELECT MAX(r2.review_id)
                FROM accounting_rule_audit_reviews r2
                WHERE r2.audit_event_id = e.audit_event_id
             )
            WHERE e.audit_event_id = ?
            """,
            (audit_event_id,),
        ).fetchone()
        return self._event_row(row) if row else None

    def list_events(self, filters: dict[str, Any] | None = None) -> tuple[AuditEventRow, ...]:
        filters = filters or {}
        where: list[str] = []
        params: list[Any] = []
        mapping = {
            "date_from": ("DATE(e.business_date) >= DATE(?)", filters.get("date_from")),
            "date_to": ("DATE(e.business_date) <= DATE(?)", filters.get("date_to")),
            "rule_area": ("e.rule_area = ?", filters.get("rule_area")),
            "event_type": ("e.event_type = ?", filters.get("event_type")),
            "source_type": ("e.source_type = ?", filters.get("source_type")),
            "party_type": ("e.party_type = ?", filters.get("party_type")),
            "party_id": ("e.party_id = ?", filters.get("party_id")),
            "amount_min": ("CAST(e.amount AS REAL) >= ?", filters.get("amount_min")),
            "amount_max": ("CAST(e.amount AS REAL) <= ?", filters.get("amount_max")),
        }
        for clause, value in mapping.values():
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        rule_query = (filters.get("rule_query") or "").strip()
        if rule_query:
            where.append("(e.rule_id LIKE ? OR e.rule_name LIKE ?)")
            like = f"%{rule_query}%"
            params.extend([like, like])
        party_query = (filters.get("party_query") or "").strip()
        if party_query:
            where.append("(e.party_name LIKE ? OR CAST(e.party_id AS TEXT) LIKE ?)")
            like = f"%{party_query}%"
            params.extend([like, like])
        status = filters.get("status")
        if status:
            where.append("COALESCE(r.status, 'unreviewed') = ?")
            params.append(status)
        sql = [
            """
            SELECT e.*, COALESCE(r.status, 'unreviewed') AS review_status,
                   r.notes AS review_notes, r.expected_behavior, r.linked_issue
            FROM accounting_rule_audit_events e
            LEFT JOIN accounting_rule_audit_reviews r
              ON r.audit_event_id = e.audit_event_id
             AND r.review_id = (
                SELECT MAX(r2.review_id)
                FROM accounting_rule_audit_reviews r2
                WHERE r2.audit_event_id = e.audit_event_id
             )
            """,
        ]
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY e.created_at DESC, e.audit_event_id DESC LIMIT ?")
        params.append(int(filters.get("limit") or 500))
        return tuple(self._event_row(row) for row in self.conn.execute("\n".join(sql), params).fetchall())

    def upsert_review(
        self,
        audit_event_id: int,
        *,
        status: str,
        notes: str | None = None,
        expected_behavior: str | None = None,
        linked_issue: str | None = None,
        reviewed_by: int | None = None,
    ) -> AuditReviewRow:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Invalid review status: {status}")
        self.conn.execute(
            """
            INSERT INTO accounting_rule_audit_reviews (
              audit_event_id, status, notes, expected_behavior, linked_issue, reviewed_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (audit_event_id, status, notes, expected_behavior, linked_issue, reviewed_by),
        )
        row = self.conn.execute(
            "SELECT * FROM accounting_rule_audit_reviews WHERE review_id = last_insert_rowid()"
        ).fetchone()
        return self._review_row(row)

    def export_csv(self, path: str | Path, filters: dict[str, Any] | None = None) -> None:
        rows = self.list_events(filters)
        with Path(path).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                safe_csv_row([
                    "created_at", "business_date", "rule_id", "rule_name",
                    "event_type", "source", "party", "amount", "summary", "status",
                ])
            )
            for row in rows:
                writer.writerow(
                    safe_csv_row([
                        row.created_at,
                        row.business_date,
                        row.rule_id,
                        row.rule_name,
                        row.event_type,
                        f"{row.source_type}:{row.source_id or ''}",
                        f"{row.party_type or ''}:{row.party_name or row.party_id or ''}",
                        row.amount,
                        row.human_summary,
                        row.review_status,
                    ])
                )

    def _event_row(self, row: sqlite3.Row) -> AuditEventRow:
        amount = row["amount"]
        return AuditEventRow(
            audit_event_id=int(row["audit_event_id"]),
            created_at=str(row["created_at"]),
            rule_id=str(row["rule_id"]),
            rule_name=str(row["rule_name"]),
            rule_area=str(row["rule_area"]),
            rule_version=str(row["rule_version"]),
            event_type=str(row["event_type"]),
            source_type=str(row["source_type"]),
            source_id=row["source_id"],
            source_label=row["source_label"],
            party_type=row["party_type"],
            party_id=row["party_id"],
            party_name=row["party_name"],
            amount=None if amount is None else Decimal(str(amount)),
            currency=str(row["currency"]),
            business_date=str(row["business_date"]),
            input_snapshot=from_json_text(row["input_snapshot_json"]),
            output_snapshot=from_json_text(row["output_snapshot_json"]),
            side_effects=from_json_text(row["side_effects_json"]),
            human_summary=str(row["human_summary"] or ""),
            technical_summary=str(row["technical_summary"] or ""),
            source_module=str(row["source_module"] or ""),
            source_function=str(row["source_function"] or ""),
            review_status=str(row["review_status"] or "unreviewed"),
            review_notes=row["review_notes"],
            expected_behavior=row["expected_behavior"],
            linked_issue=row["linked_issue"],
        )

    def _review_row(self, row: sqlite3.Row) -> AuditReviewRow:
        return AuditReviewRow(
            review_id=int(row["review_id"]),
            audit_event_id=int(row["audit_event_id"]),
            status=str(row["status"]),
            notes=row["notes"],
            expected_behavior=row["expected_behavior"],
            linked_issue=row["linked_issue"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=str(row["reviewed_at"]),
        )
