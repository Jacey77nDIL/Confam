"""Squad wallet payout to a Nigerian bank account (after funding)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from services import squad_client

logger = logging.getLogger(__name__)

_TRANSFER_PATH = "/payout/transfer"


def _merchant_prefix() -> str:
    raw = os.getenv("SQUAD_MERCHANT_ID", "").strip()
    if not raw:
        raise squad_client.SquadConfigurationError(
            "SQUAD_MERCHANT_ID is required for outbound transfers.",
        )
    return re.sub(r"[^A-Za-z0-9_]", "", raw)


def initiate_transfer(
    *,
    amount_kobo: int,
    bank_code: str,
    account_number: str,
    account_name: str | None = None,
    unique_suffix: str,
    remark: str = "Confam transfer",
) -> dict[str, Any]:
    """
    Move funds from Squad merchant wallet to a looked-up account.
    transaction_reference must include merchant id prefix (Squad requirement).

    When the merchant is collection-only (outbound payout disabled), this is not called from
    ``payment_execution_service``; funds stay in the Squad balance until manual disbursement.
    """
    if not squad_client.squad_is_configured():
        return {"success": False, "user_message": "Transfers are not configured.", "data": None}
    prefix = _merchant_prefix()
    tx_ref = f"{prefix}_{unique_suffix}"[:120]
    nm = (str(account_name).strip() if account_name is not None else "")[:120]
    body: dict[str, Any] = {
        "transaction_reference": tx_ref,
        "amount": str(int(amount_kobo)),
        "bank_code": str(bank_code).strip(),
        "account_number": str(account_number).strip(),
        "account_name": nm or "Recipient",
        "currency_id": "NGN",
        "remark": remark[:80],
    }
    status, data = squad_client.squad_post(_TRANSFER_PATH, body)
    if not isinstance(data, dict):
        return {"success": False, "user_message": squad_client.user_facing_error(status or 500, {}), "data": None}
    ok = status == 200 and bool(data.get("success") or data.get("status") in (200, "200"))
    if not ok:
        logger.warning("Squad transfer failed status=%s body=%s", status, data)
        return {
            "success": False,
            "user_message": squad_client.user_facing_error(status, data),
            "data": data.get("data"),
        }
    return {"success": True, "user_message": "ok", "data": data.get("data"), "transaction_reference": tx_ref}
