from __future__ import annotations

import re


SALE_PRICE_RULE_MESSAGE = "Sale price must be greater than purchase price."

_STRICT_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def parse_strict_float(value: str | None) -> float:
    text = "" if value is None else str(value).strip()
    if not text or not _STRICT_NUMBER_RE.fullmatch(text):
        raise ValueError("Invalid numeric value")
    return float(text)


def ensure_purchase_item_prices(purchase_price: float, sale_price: float) -> None:
    if purchase_price < 0:
        raise ValueError("Purchase price cannot be negative.")
    if sale_price < 0:
        raise ValueError("Sale price cannot be negative.")
    if sale_price <= purchase_price:
        raise ValueError(SALE_PRICE_RULE_MESSAGE)
