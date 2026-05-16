"""Route user input to payment vs market vs other pipelines (heuristics, no LLM)."""

from __future__ import annotations

import re
from typing import Literal

from services import intent_parser_service

RouteKind = Literal["payment", "market", "other"]

_PAYMENT_RE = re.compile(
    r"\b(send|transfer|pay\s+\d|payment|bank\s+account|account\s+number|ussd|opay|kuda|gtbank|"
    r"access\s+bank|zenith|first\s+bank|screenshot|slip|receipt|credit\s+my|debit)\b",
    re.IGNORECASE,
)

_MARKET_RE = re.compile(
    r"\b(how\s+much|price|cost|market|garri|rice|yam|tomato|tomatoes|onion|onions|pepper|beans|"
    r"mile\s*12|yaba|wuse|oyingbo|bodija|mudu|basket|kg|bought|buy|paid|saw|expensive|cheap|"
    r"submit|report|today|per\s+)\b",
    re.IGNORECASE,
)


def classify_text(text: str) -> RouteKind:
    t = (text or "").strip()
    if not t:
        return "other"
    if intent_parser_service.looks_like_transfer_confirmation(t):
        return "payment"
    if _PAYMENT_RE.search(t) and not _MARKET_RE.search(t):
        return "payment"
    if _MARKET_RE.search(t) or intent_parser_service.parse_amount_naira(t) is not None:
        return "market"
    if _PAYMENT_RE.search(t):
        return "payment"
    return "market"


def classify_image_caption(caption: str | None) -> RouteKind:
    """Payment screenshots vs market product photos (caption hints)."""
    t = (caption or "").strip()
    if not t:
        return "market"
    if _PAYMENT_RE.search(t) and not _MARKET_RE.search(t):
        return "payment"
    if _MARKET_RE.search(t):
        return "market"
    return "market"
