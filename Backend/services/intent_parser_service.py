"""Lightweight payment / transfer intent parsing (MVP, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TransferIntent:
    is_transfer: bool
    amount_naira: float | None
    recipient_query: str | None


_SEND_VERBS = re.compile(
    r"\b(send|transfer|pay|credit|zap|dash)\b",
    re.IGNORECASE,
)


def parse_amount_naira(text: str) -> float | None:
    """Extract a naira amount from informal Nigerian phrasing (5k, 10,000, ₦500)."""
    t = text.strip()
    if not t:
        return None
    # Informal "N500" / "n300" (ASCII naira shorthand)
    mn = re.search(r"\bN([\d,]+(?:\.\d+)?)\b", t, re.IGNORECASE)
    if mn:
        try:
            return float(mn.group(1).replace(",", ""))
        except ValueError:
            return None
    # ₦500 / NGN 2000
    m = re.search(r"(?:₦|NGN|naira)\s*([\d,]+(?:\.\d+)?)", t, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    m = re.search(r"\b([\d,]+(?:\.\d+)?)\s*(?:₦|NGN|naira)\b", t, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    # 5k / 2.5k
    mk = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", t, re.IGNORECASE)
    if mk:
        try:
            return float(mk.group(1)) * 1000.0
        except ValueError:
            return None
    # bare 5000 / 5,000 (avoid tiny numbers unless k context)
    m2 = re.search(r"\b(\d{3,}(?:,\d{3})*(?:\.\d+)?)\b", t)
    if m2:
        try:
            v = float(m2.group(1).replace(",", ""))
            return v if v >= 100 else None
        except ValueError:
            return None
    return None


def _recipient_fragment(text: str) -> str | None:
    """Rough substring after send/transfer/pay and optional amount — for fuzzy name match."""
    t = text.strip()
    if not t:
        return None
    # strip leading send verb
    t2 = _SEND_VERBS.sub("", t, count=1).strip()
    # strip currency amounts patterns (repeat lightly)
    t2 = re.sub(r"(?:₦|NGN|naira)\s*[\d,]+(?:\.\d+)?", " ", t2, flags=re.IGNORECASE)
    t2 = re.sub(r"\b[\d,]+(?:\.\d+)?\s*(?:₦|NGN|naira)\b", " ", t2, flags=re.IGNORECASE)
    t2 = re.sub(r"\b\d+(?:\.\d+)?\s*k\b", " ", t2, flags=re.IGNORECASE)
    t2 = re.sub(r"\b\d{3,}(?:,\d{3})*(?:\.\d+)?\b", " ", t2)
    t2 = re.sub(r"\b(to|for|with)\b", " ", t2, flags=re.IGNORECASE)
    t2 = re.sub(r"\s+", " ", t2).strip(" ,.-")
    if len(t2) < 2:
        return None
    return t2


def parse_transfer_intent(text: str) -> TransferIntent:
    raw = text.strip()
    if not raw:
        return TransferIntent(False, None, None)
    is_t = bool(_SEND_VERBS.search(raw))
    amt = parse_amount_naira(raw)
    frag = _recipient_fragment(raw) if is_t else None
    # “pay her 1500” — pronoun-only fragment is weak; still treat as transfer if verb+amount
    if is_t and not frag and amt is not None:
        frag = None
    if not is_t and amt is not None and re.search(r"\b(pay|send|transfer)\b", raw, re.I):
        is_t = True
    return TransferIntent(is_t, amt, frag)


_CONFIRM_RE = re.compile(
    r"\b(confirm(ed|ation)?|yes|yeah|yep|sure|ok(ay)?|go ahead|proceed|send it|do it|pay now|authorize|"
    r"charge it|charge my card|complete (the )?transfer)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(don'?t|do not|never|stop|cancel|abort)\b", re.IGNORECASE)


def looks_like_transfer_confirmation(text: str) -> bool:
    """
    True for short follow-ups that mean “go ahead” after a send request.
    Excludes obvious negations (“don’t send”).
    """
    t = (text or "").strip()
    if not t or len(t) > 160:
        return False
    if _NEGATION_RE.search(t):
        return False
    return bool(_CONFIRM_RE.search(t))


def is_bare_transfer_acknowledgement(text: str) -> bool:
    """
    True when the message is only an acknowledgement (e.g. "confirm the transfer", "yes")
    and does not restate a new payee or amount — so we should not treat it as a fresh transfer.
    """
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    if re.search(r"\d", t):
        return False
    if re.search(r"\bto\s+[a-z]", t, re.IGNORECASE):
        return False
    return bool(_CONFIRM_RE.search(t))
