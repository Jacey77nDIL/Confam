"""Shared helpers for Money Sending Mode (smart caption + payment_metadata)."""

from __future__ import annotations

import re
from typing import Any

from services import intent_parser_service


def suggested_amount_from_caption(caption: str | None) -> str | None:
    if not caption:
        return None
    t = caption.strip()
    parsed = intent_parser_service.parse_amount_naira(t)
    if parsed is not None:
        if parsed == int(parsed):
            return str(int(parsed))
        return f"{parsed:.2f}".rstrip("0").rstrip(".")
    m = re.search(r"(?:₦|NGN|naira)\s*([\d,]+(?:\.\d{1,2})?)", t, re.IGNORECASE)
    if not m:
        m = re.search(r"\b([\d,]+(?:\.\d{1,2})?)\s*(?:₦|NGN|naira)\b", t, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", "")
    m2 = re.search(r"\b(\d{3,}(?:,\d{3})*(?:\.\d{1,2})?)\b", t)
    if m2:
        return m2.group(1).replace(",", "")
    return None


def payment_intent_from_extraction(extracted: dict[str, Any]) -> bool:
    """True if vision/payment extraction found enough to treat as send-money context."""
    if extracted.get("extraction_error") and not any(
        [extracted.get("bank_name"), extracted.get("account_number"), extracted.get("account_name")],
    ):
        return False
    acct = extracted.get("account_number")
    if acct and isinstance(acct, str) and len(acct) == 10 and acct.isdigit():
        return True
    bank = (extracted.get("bank_name") or "").strip()
    _an_raw = extracted.get("account_name")
    name = (str(_an_raw).strip() if _an_raw is not None else "")
    return bool(bank and name)


def names_differ_fuzzy(ai: str | None, verified: str | None) -> bool:
    if not ai or not verified:
        return False
    a = re.sub(r"\s+", " ", str(ai).strip().lower())
    b = re.sub(r"\s+", " ", str(verified).strip().lower())
    return a != b


def smart_caption_line(account_display: str, suggested_amount: str | None) -> str:
    amt = suggested_amount if suggested_amount else "?"
    return f"Confirm payment to {account_display}: [AMOUNT_INPUT: {amt}]"


def build_payment_metadata(
    *,
    mode: str,
    uploaded_file_id: int | None,
    user_message_id: int | None,
    bank_name: str | None,
    account_number: str | None,
    ai_account_name: str | None,
    account_lookup: dict[str, Any],
    suggested_amount: str | None,
    smart_caption: str,
) -> dict[str, Any]:
    verified = account_lookup.get("verified_account_name") if account_lookup.get("success") else None
    ai_norm = (str(ai_account_name).strip() if ai_account_name is not None else "") or None
    highlight = "bank_verify" if verified and names_differ_fuzzy(ai_norm, verified) else None
    display = verified or ai_norm or "—"
    return {
        "is_payment_intent": True,
        "mode": mode,
        "smart_caption": smart_caption,
        "uploaded_file_id": uploaded_file_id,
        "user_message_id": user_message_id,
        "bank_name": bank_name,
        "account_number": account_number,
        "ai_account_name": ai_norm,
        "verified_account_name": verified,
        "name_verification_highlight": highlight,
        "suggested_amount": suggested_amount,
        "account_lookup": {
            "configured": account_lookup.get("configured", False),
            "resolved": account_lookup.get("success", False),
            "message": account_lookup.get("message"),
            "bank_code": account_lookup.get("bank_code"),
        },
        "display_account_name": display,
    }
