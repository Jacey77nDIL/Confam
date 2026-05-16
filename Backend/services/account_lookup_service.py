"""Squad payout account name resolution (NIP lookup)."""

from __future__ import annotations

import logging
import re
from typing import Any

from services import squad_client, squad_response, squad_service
from utils.nip_banks import nip_candidates_for_bank_name

logger = logging.getLogger(__name__)

_LEGACY_LOOKUP_PATH = "/payout/account_lookup"


def _sanitize_account_number(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) != 10:
        return None
    return digits


def _try_lookup(account_number: str, bank_code: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "success": False,
        "configured": squad_client.squad_is_configured(),
        "verified_account_name": None,
        "bank_code": bank_code,
        "account_number": account_number,
        "message": None,
    }
    if not squad_client.squad_is_configured():
        out["message"] = "Account verification is not configured on this server."
        return out

    bc = str(bank_code).strip()
    acct = str(account_number).strip()

    body = squad_service.payout_account_lookup_body(bank_code=bc, account_number=acct)
    paths = (squad_service.PAYOUT_ACCOUNT_LOOKUP_PATH, _LEGACY_LOOKUP_PATH)

    for path in paths:
        status, raw = squad_client.squad_post(path, body)
        if status == 404 and path == paths[0]:
            logger.info("Squad account lookup 404 on %s; retrying %s", path, paths[1])
            continue
        if not isinstance(raw, dict):
            out["message"] = "Unexpected response from verification service."
            return out
        if status in (401, 403):
            out["message"] = (
                "Squad rejected the API key. Use a secret key that matches SQUAD_API_BASE "
                "(sandbox sk with sandbox URL, live sk with https://api-d.squadco.com)."
            )
            return out
        if status == 200 and not squad_response.squad_envelope_failed(raw):
            inner = raw.get("data")
            if isinstance(inner, dict):
                name = inner.get("account_name") or inner.get("accountName")
                if name:
                    out["success"] = True
                    out["verified_account_name"] = str(name).strip()
                    out["message"] = "ok"
                    return out
            out["message"] = "Could not read the account name for those details."
            return out
        out["message"] = squad_client.user_facing_error(status, raw)
        return out
    out["message"] = "Account lookup failed for this bank route. Confirm SQUAD_API_BASE and bank NIP code."
    return out


def lookup_stub_response(*, account_number: str | None = None) -> dict[str, Any]:
    """
    Placeholder while Squad ``/payout/account/lookup`` is disabled in callers.
    Same key shape as :func:`resolve_nigerian_bank_account` for chat/UI metadata.
    """
    return {
        "success": False,
        "configured": squad_client.squad_is_configured(),
        "verified_account_name": None,
        "bank_code": None,
        "account_number": account_number,
        "message": "Account lookup temporarily disabled.",
    }


def resolve_nigerian_bank_account(
    *,
    bank_name: str | None,
    account_number: str | None,
    bank_code: str | None = None,
) -> dict[str, Any]:
    """
    Squad account lookup. Tries multiple NIP bank codes when the bank name is ambiguous.

    Keys: success, configured, verified_account_name, bank_code, account_number, message
    """
    base: dict[str, Any] = {
        "success": False,
        "configured": squad_client.squad_is_configured(),
        "verified_account_name": None,
        "bank_code": None,
        "account_number": account_number,
        "message": None,
    }
    if not squad_client.squad_is_configured():
        base["message"] = "Account verification is not configured on this server."
        return base

    acct = _sanitize_account_number(account_number)
    if not acct:
        base["message"] = "Enter a valid 10-digit Nigerian account number."
        return base

    candidates: list[str] = []
    if bank_code and str(bank_code).strip().isdigit():
        bc = str(bank_code).strip()
        if bc not in candidates:
            candidates.append(bc)
    for c in nip_candidates_for_bank_name(bank_name):
        if c not in candidates:
            candidates.append(c)

    if not candidates:
        base["message"] = "Could not detect the bank from that name. Try a clearer bank name or screenshot."
        return base

    last = base
    for code in candidates[:15]:
        last = _try_lookup(acct, code)
        last["bank_code"] = code
        if last.get("success"):
            return last
        logger.info(
            "Squad account lookup failed bank_code=%s account=%s: %s",
            code,
            acct,
            last.get("message"),
        )
    return last


def is_configured() -> bool:
    return squad_client.squad_is_configured()
