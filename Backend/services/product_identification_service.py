"""Vision-only product identification for market photos (no pricing via LLM)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from services import openrouter_service

logger = logging.getLogger(__name__)

_PRODUCT_JSON_RE = re.compile(r"\{[^{}]*\"product\"\s*:\s*[^}]+\}", re.DOTALL)


def is_configured() -> bool:
    return openrouter_service.is_configured()


def identify_product(
    image: tuple[bytes, str],
    *,
    caption: str | None = None,
) -> str | None:
    """
    Return a lowercase product noun (e.g. ``yam``) or ``None`` if vision is disabled or unclear.
    """
    if not is_configured():
        return _product_from_caption(caption)

    cap = (caption or "").strip()
    user_text = "Identify the main market product in this photo."
    if cap:
        user_text += f' User caption: "{cap[:400]}"'

    try:
        raw = openrouter_service.complete_vision_custom(
            image,
            system_prompt=(
                "You identify Nigerian market produce in a product photo.\n"
                'Reply with ONLY valid JSON: {"product": "single lowercase English noun"}.\n'
                'If unclear, use {"product": null}.\n'
                "Do NOT include prices, locations, units, or explanations."
            ),
            user_text=user_text,
            model=None,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001
        logger.exception("product_identification: vision failed")
        return _product_from_caption(caption)

    return _parse_product_json(raw) or _product_from_caption(caption)


def build_market_query(product: str, caption: str | None) -> str:
    """Combine vision product + caption into one ML-friendly message."""
    p = (product or "").strip().lower()
    cap = (caption or "").strip()
    if not p:
        return cap
    if not cap:
        return f"how much is {p}"
    low = cap.lower()
    if p in low:
        return cap
    return f"{p} {cap}"


def _product_from_caption(caption: str | None) -> str | None:
    cap = (caption or "").strip().lower()
    if not cap:
        return None
    m = re.search(
        r"\b(garri|rice|yam|tomato(?:es)?|onion(?:s)?|pepper|beans|plantain|oil|fish|"
        r"chicken|beef|egg(?:s)?|bread|sugar|salt|flour|maize|corn)\b",
        cap,
        re.I,
    )
    return m.group(1).lower() if m else None


def _parse_product_json(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    candidates: list[str] = [text]
    m = _PRODUCT_JSON_RE.search(text)
    if m:
        candidates.insert(0, m.group(0))
    for chunk in candidates:
        try:
            data: Any = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            prod = data.get("product")
            if prod is None:
                return None
            s = str(prod).strip().lower()
            return s or None
    return None
