"""Payment screenshot extraction via OpenRouter vision (structured JSON)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from services import openrouter_service

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You extract structured payment details from bank transfer and payment screenshots. "
    "Return a single JSON object only. Use double quotes for keys and string values. "
    "Never wrap the JSON in markdown fences."
)

_USER_PROMPT = """Extract from this Nigerian bank transfer or payment screenshot:

* bank_name
* account_number
* account_name

Rules:

* Return ONLY one JSON object, no markdown, no commentary.
* If a field is missing, use null.
* account_number must be digits only inside the JSON string (10 digits for a typical Nigerian NUBAN).
* account_name must be the person or business name only (no labels like "Beneficiary:").

Example:
{"bank_name":"GTBank","account_number":"0123456789","account_name":"John Doe"}"""


def _empty_slots() -> dict[str, Any]:
    return {"bank_name": None, "account_number": None, "account_name": None}


def _strip_json_fences(raw: str) -> str:
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def _repair_jsonish(s: str) -> str:
    """Light repairs for common model mistakes."""
    t = s.strip()
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return t


def _parse_json_object(raw: str) -> dict[str, Any]:
    s = _repair_jsonish(_strip_json_fences(raw))
    try:
        out = json.loads(s)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        chunk = _repair_jsonish(s[i : j + 1])
        try:
            out = json.loads(chunk)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    raise ValueError("Model did not return parseable JSON")


def _regex_extract_fields(blob: str) -> dict[str, str | None]:
    """Last-resort: pull quoted values for known keys from messy output."""
    out: dict[str, str | None] = {"bank_name": None, "account_number": None, "account_name": None}
    for key in ("bank_name", "account_number", "account_name"):
        m = re.search(
            rf'["\']?{re.escape(key)}["\']?\s*:\s*"([^"]*)"',
            blob,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = m.group(1).strip()
            out[key] = val or None
            continue
        m2 = re.search(
            rf'["\']?{re.escape(key)}["\']?\s*:\s*\'([^\']*)\'',
            blob,
            re.IGNORECASE | re.DOTALL,
        )
        if m2:
            val = m2.group(1).strip()
            out[key] = val or None
    return out


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        return t or None
    if isinstance(v, (int, float)):
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v).strip() or None
    return None


def _clean_name(raw: str | None) -> str | None:
    t = _clean_str(raw)
    if not t:
        return None
    t = t.replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(
        r"(?i)^(account\s*name|beneficiary|receiver|name|acct\.?\s*name)\s*[:\-]\s*",
        "",
        t,
    )
    t = re.sub(r"^[:\-\s,.;]+|[:\-\s,.;]+$", "", t)
    if len(t) > 255:
        t = t[:252].rstrip() + "..."
    return t or None


def _validate_account_number(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return digits
    m = re.search(r"\d{10}", raw.replace(" ", "").replace("-", ""))
    if m:
        return m.group(0)
    logger.info("Account number not 10 digits after sanitization; returning null")
    return None


def extract_payment_from_image(image: openrouter_service.VisionImageInput, user_hint: str | None = None) -> dict[str, Any]:
    """
    Vision model extraction + validation.

    Returns dict suitable for Message.ocr_payload and PaymentExtraction persistence.
    ``parsed_json`` is always a dict (never None) so JSONB columns stay structured.
    """
    if not openrouter_service.is_configured():
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    user_text = _USER_PROMPT
    if user_hint and user_hint.strip():
        user_text = (
            _USER_PROMPT
            + "\n\nUser message alongside the screenshot (may mention amount or intent; "
            "do not invent bank fields from text alone):\n"
            + user_hint.strip()[:2000]
        )

    raw_response = openrouter_service.complete_vision_custom(
        image,
        system_prompt=_SYSTEM,
        user_text=user_text,
        model=openrouter_service.payment_vision_model(),
        temperature=0.1,
    )

    parsed: dict[str, Any] | None = None
    parse_err: str | None = None
    try:
        parsed = _parse_json_object(raw_response)
    except ValueError as exc:
        parse_err = str(exc)
        logger.warning("Payment extraction JSON parse failed: %s", exc)

    slots = _empty_slots()
    if parsed:
        slots["bank_name"] = _clean_str(parsed.get("bank_name"))
        slots["account_name"] = _clean_name(_clean_str(parsed.get("account_name")))
        slots["account_number"] = _validate_account_number(_clean_str(parsed.get("account_number")))

    if not any(slots.values()) and raw_response:
        fb = _regex_extract_fields(raw_response)
        if any(fb.values()):
            slots["bank_name"] = slots["bank_name"] or _clean_str(fb.get("bank_name"))
            slots["account_name"] = slots["account_name"] or _clean_name(_clean_str(fb.get("account_name")))
            slots["account_number"] = slots["account_number"] or _validate_account_number(
                _clean_str(fb.get("account_number")),
            )
            if parse_err:
                parse_err = parse_err + " (partial fields recovered from text)"

    out: dict[str, Any] = {
        "bank_name": slots["bank_name"],
        "account_number": slots["account_number"],
        "account_name": slots["account_name"],
        "raw_ai_response": raw_response,
        "parsed_json": {
            "bank_name": slots["bank_name"],
            "account_number": slots["account_number"],
            "account_name": slots["account_name"],
        },
    }
    if parse_err and not any(slots.values()):
        out["extraction_error"] = parse_err
    return out
