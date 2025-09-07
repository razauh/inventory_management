from __future__ import annotations
from typing import Iterable, Optional

# ---------- Canonical set & order ----------
VALID_STATES: tuple[str, ...] = ("posted", "pending", "cleared", "bounced")
STATE_ORDER: dict[str, int] = {s: i for i, s in enumerate(VALID_STATES)}  # posted=0,...,bounced=3

# ---------- Human labels ----------
LABELS = {
    "posted":  "Posted",
    "pending": "Pending",
    "cleared": "Cleared",
    "bounced": "Bounced",
}

# ---------- Descriptions (UI copy / tooltips) ----------
DESCRIPTIONS = {
    "posted":  "Recorded in the ledger. Banking lifecycle not started.",
    "pending": "In transit / awaiting bank confirmation (e.g., cheque/transfer).",
    "cleared": "Funds confirmed and settled by the bank.",
    "bounced": "Instrument failed or reversed (e.g., returned cheque).",
}

# (Optional) style tokens the UI can map to colors/icons
STYLES = {
    "posted":  {"badge": "neutral", "fg": "#374151", "bg": "#F3F4F6"},
    "pending": {"badge": "warning", "fg": "#92400E", "bg": "#FEF3C7"},
    "cleared": {"badge": "success", "fg": "#065F46", "bg": "#D1FAE5"},
    "bounced": {"badge": "danger",  "fg": "#991B1B", "bg": "#FEE2E2"},
}

# ---------- API ----------

def normalize(state: Optional[str]) -> Optional[str]:
    """Lowercase & strip; return None if empty. Does NOT invent synonyms."""
    if state is None:
        return None
    s = str(state).strip().lower()
    return s or None


def is_valid(state: Optional[str]) -> bool:
    """Return True iff state is one of the canonical values."""
    s = normalize(state)
    return s in VALID_STATES if s is not None else False


def ensure_valid(state: str) -> str:
    """
    Return the normalized state if valid; raise ValueError if not.
    Keep error text aligned with repositories for consistent UX.
    """
    s = normalize(state)
    if s not in VALID_STATES:
        raise ValueError("clearing_state must be one of: posted, pending, cleared, bounced")
    return s  # type: ignore[return-value]


def label(state: str) -> str:
    """Human label ('Cleared'). If unknown, returns the original string title-cased."""
    s = normalize(state)
    if s in LABELS:
        return LABELS[s]  # type: ignore[index]
    return (state or "").strip().title()


def description(state: str) -> str:
    """Short human description for tooltips; empty string if unknown."""
    s = normalize(state)
    return DESCRIPTIONS.get(s, "")


def style_tokens(state: str) -> dict:
    """
    Return a small style dict: e.g., {'badge': 'success', 'fg': '#065F46', 'bg': '#D1FAE5'}.
    Views can choose to ignore, or map to Qt/CSS.
    Unknown states fall back to a neutral style.
    """
    s = normalize(state)
    return STYLES.get(s, STYLES["posted"])  # default neutral


def sort_key(state: str) -> int:
    """Stable sort key using STATE_ORDER; unknown states sort after known ones."""
    s = normalize(state)
    return STATE_ORDER.get(s, 999)


def sort_states(states: Iterable[str]) -> list[str]:
    """Return a new list sorted by canonical order."""
    return sorted(states, key=sort_key)
