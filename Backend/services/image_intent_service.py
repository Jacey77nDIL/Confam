"""
Classify a WhatsApp image as shopping (pricing) vs payment (bank slip / transfer UI).

Uses caption heuristics first, then a single vision classification via ``openrouter_service``
when configured. Does not perform full payment extraction — routing only.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from services import openrouter_service

logger = logging.getLogger(__name__)

ImageIntent = Literal["shopping", "payment"]

_PAYMENT_HINTS = re.compile(
    r"\b(send|transfer|pay|payment|bank|account|ussd|opay|kuda|gtbank|access|zenith|first\s*bank|"
    r"screenshot|slip|receipt|credit|debit|naira|₦|ngn)\b",
    re.IGNORECASE,
)


def classify_from_caption(caption: str | None) -> ImageIntent | None:
    t = (caption or "").strip()
    if not t:
        return None
    if _PAYMENT_HINTS.search(t):
        return "payment"
    if re.search(r"\b(how\s+much|price|cost|market|buy|sell|fair|negotiat)\b", t, re.I):
        return "shopping"
    return None


def classify_image_intent(
    image: tuple[bytes, str],
    *,
    caption: str | None = None,
) -> ImageIntent:
    """
    Return ``shopping`` or ``payment`` for downstream routing
    (``handle_image_turn`` vs ``handle_payment_turn``).
    """
    hinted = classify_from_caption(caption)
    if hinted == "payment":
        return "payment"
    if hinted == "shopping":
        return "shopping"
    if not openrouter_service.is_configured():
        return "shopping"
    try:
        raw = openrouter_service.complete_vision_custom(
            image,
            system_prompt=(
                "You classify a single WhatsApp image for a Nigerian fintech assistant.\n"
                "Reply with exactly one uppercase word:\n"
                "- PAYMENT if the image shows a bank app, transfer screen, USSD slip, deposit receipt, "
                "account number prominently, or payment confirmation.\n"
                "- SHOPPING for market goods, food, electronics product photos, price tags in a shop "
                "without banking UI.\n"
                "No punctuation, no explanation."
            ),
            user_text="Classify this image.",
            model=None,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001
        logger.exception("image_intent_service: vision classification failed")
        return "shopping"
    token = (raw or "").strip().upper().split()
    first = token[0] if token else ""
    if "PAYMENT" in first or first.startswith("PAY"):
        return "payment"
    return "shopping"
