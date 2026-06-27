from __future__ import annotations

import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .dto import AuditEventDraft
from .repository import AccountingAuditRepository


class AccountingAuditService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = AccountingAuditRepository(conn)

    def log(self, draft: AuditEventDraft) -> int:
        return self.repo.insert_event(draft)

    def log_business_event(
        self,
        *,
        rule_id: str,
        event_type: str,
        source_type: str,
        source_id: str | int | None,
        source_label: str | None = None,
        party_type: str | None = None,
        party_id: int | None = None,
        party_name: str | None = None,
        amount: Any = None,
        business_date: str | None = None,
        payload: Any = None,
        result: Any = None,
        side_effects: dict[str, Any] | None = None,
        human_summary: str = "",
        source_function: str = "",
    ) -> int:
        return self.log(
            AuditEventDraft(
                rule_id=rule_id,
                event_type=event_type,
                source_type=source_type,
                source_id=source_id,
                source_label=source_label,
                party_type=party_type,
                party_id=party_id,
                party_name=party_name,
                amount=amount,
                business_date=business_date or date.today().isoformat(),
                input_snapshot=_snapshot(payload),
                output_snapshot=_snapshot(result),
                side_effects=side_effects or {},
                human_summary=human_summary,
                technical_summary=f"AccountingService.{source_function}",
                source_module="modules.accounting.service",
                source_function=source_function,
            )
        )

    def party_name(self, party_type: str | None, party_id: int | None) -> str | None:
        if not party_type or party_id is None:
            return None
        table = {"vendor": "vendors", "customer": "customers"}.get(party_type)
        id_col = {"vendor": "vendor_id", "customer": "customer_id"}.get(party_type)
        if not table or not id_col:
            return None
        row = self.conn.execute(
            f"SELECT name FROM {table} WHERE {id_col} = ?",
            (party_id,),
        ).fetchone()
        return None if row is None else str(row["name"] if hasattr(row, "keys") else row[0])

    def vendor_for_purchase(self, purchase_id: str | int | None) -> tuple[int | None, str | None]:
        if purchase_id is None:
            return None, None
        row = self.conn.execute(
            """
            SELECT v.vendor_id, v.name
            FROM purchases p
            JOIN vendors v ON v.vendor_id = p.vendor_id
            WHERE p.purchase_id = ?
            """,
            (str(purchase_id),),
        ).fetchone()
        if row is None:
            return None, None
        return int(row["vendor_id"]), str(row["name"])

    def customer_for_sale(self, sale_id: str | int | None) -> tuple[int | None, str | None]:
        if sale_id is None:
            return None, None
        row = self.conn.execute(
            """
            SELECT c.customer_id, c.name
            FROM sales s
            JOIN customers c ON c.customer_id = s.customer_id
            WHERE s.sale_id = ?
            """,
            (str(sale_id),),
        ).fetchone()
        if row is None:
            return None, None
        return int(row["customer_id"]), str(row["name"])


def _snapshot(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return {"items": list(value)}
    if isinstance(value, Decimal):
        return {"value": str(value)}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"value": value}
