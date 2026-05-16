"""Orchestrate payment screenshot extraction + Squad account verification."""

from __future__ import annotations

from typing import Any

from services import account_lookup_service, openrouter_service, payment_extraction_service


def extract_and_resolve(image: openrouter_service.VisionImageInput, user_hint: str | None = None) -> dict[str, Any]:
    """
    Returns keys: fields (extraction dict), account_lookup (dict), stored_account_name, verified_name.
    """
    fields = payment_extraction_service.extract_payment_from_image(image, user_hint=user_hint)
    bank = fields.get("bank_name")
    acct = fields.get("account_number")
    ai_raw = fields.get("account_name")
    ai_name = (str(ai_raw).strip() if ai_raw is not None else "") or None

    # lk = account_lookup_service.resolve_nigerian_bank_account(bank_name=bank, account_number=acct)
    lk = account_lookup_service.lookup_stub_response(account_number=acct)

    verified: str | None = None
    if lk.get("success") and lk.get("verified_account_name"):
        verified = str(lk.get("verified_account_name")).strip() or None

    stored_account_name = ai_name or verified

    parsed_out: dict[str, Any] | None = None
    pj = fields.get("parsed_json")
    if isinstance(pj, dict):
        parsed_out = {**pj, "account_name": stored_account_name or pj.get("account_name")}
    else:
        parsed_out = fields.get("parsed_json")

    return {
        "fields": fields,
        "account_lookup": lk,
        "verified_name": verified,
        "stored_account_name": stored_account_name,
        "parsed_out": parsed_out,
        "bank": bank,
        "account_number": acct,
        "ai_name": ai_name,
    }
