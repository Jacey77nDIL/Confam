"""Confam-facing AI calls: system prompt composition + short payment replies."""

from __future__ import annotations

import json
import logging
from typing import Any

from ai.prompts import CONFAM_SYSTEM_PROMPT, LOCATION_CONTEXT_TEMPLATE, PAYMENT_FOLLOWUP_SYSTEM
from services import openrouter_service

logger = logging.getLogger(__name__)


def _location_suffix(latitude: float | None, longitude: float | None) -> str:
    if latitude is None or longitude is None:
        return ""
    try:
        return LOCATION_CONTEXT_TEMPLATE.format(lat=float(latitude), lon=float(longitude))
    except (TypeError, ValueError):
        return ""


def complete_text_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    extra_system_suffix: str | None = None,
) -> str:
    loc = _location_suffix(latitude, longitude)
    parts = [p for p in (loc, extra_system_suffix) if p]
    suffix = "\n".join(parts) if parts else None
    return openrouter_service.complete_text_chat(messages, model=model, system_suffix=suffix)


def complete_vision_chat(
    messages: list[dict[str, Any]],
    image: openrouter_service.VisionImageInput,
    *,
    caption: str | None = None,
    model: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    suffix = _location_suffix(latitude, longitude) or None
    return openrouter_service.complete_vision_chat(
        messages,
        image,
        caption=caption,
        model=model,
        system_suffix=suffix,
    )


def payment_followup_reply(
    *,
    user_text: str,
    bank: str | None,
    account_number: str | None,
    display_name: str | None,
    verified_name: str | None,
    suggested_amount: str | None,
) -> str | None:
    """Single short assistant message combining slip + user intent. Returns None if AI disabled."""
    if not openrouter_service.is_configured():
        return None
    facts = {
        "user_message": user_text.strip()[:1200],
        "bank": bank,
        "account_number": account_number,
        "display_account_name": display_name,
        "bank_verified_name": verified_name,
        "parsed_suggested_amount": suggested_amount,
    }
    user_block = (
        "Structured extraction from the screenshot (JSON):\n"
        + json.dumps(facts, ensure_ascii=False)
        + "\n\nWrite the reply to the user."
    )
    try:
        return openrouter_service.complete_text_chat(
            [{"role": "user", "content": user_block}],
            system_suffix="\n\n" + PAYMENT_FOLLOWUP_SYSTEM,
            model=None,
            temperature=0.35,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("payment_followup_reply failed: %s", exc)
        return None


def confam_system_base() -> str:
    return CONFAM_SYSTEM_PROMPT
