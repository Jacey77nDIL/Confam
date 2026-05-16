"""Squad API base URL and request helpers (no secrets in JSON bodies)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Squad docs: POST {base}/transaction/initiate — path segment must be lowercase.
TRANSACTION_INITIATE_PATH = "/transaction/initiate"

# Account name inquiry (NIP resolve) — body must be only bank_code + account_number (Bearer auth only).
PAYOUT_ACCOUNT_LOOKUP_PATH = "/payout/account/lookup"

# Squad sandbox: use the `sandbox-api-d` host (per Squad docs / verified dev subdomain).
SQUAD_SANDBOX_API_BASE = "https://sandbox-api-d.squadco.com"

# Older docs/samples used this host without `-d`; normalize to SQUAD_SANDBOX_API_BASE.
_LEGACY_SANDBOX_NO_D = frozenset(
    {
        "https://sandbox-api.squadco.com",
        "http://sandbox-api.squadco.com",
    },
)


def resolve_squad_api_base() -> str:
    """
    Effective base URL for Squad REST calls (no trailing slash).

    If `SQUAD_API_BASE` is unset, defaults to ``SQUAD_SANDBOX_API_BASE``.
    If it points at the legacy non-`-d` sandbox host, it is rewritten to ``SQUAD_SANDBOX_API_BASE``.
    """
    raw = (os.getenv("SQUAD_API_BASE") or SQUAD_SANDBOX_API_BASE).strip().rstrip("/")
    if raw in _LEGACY_SANDBOX_NO_D:
        logger.info(
            "SQUAD_API_BASE %s normalized to %s (legacy sandbox host → development subdomain).",
            raw,
            SQUAD_SANDBOX_API_BASE,
        )
        return SQUAD_SANDBOX_API_BASE
    return raw


def payout_account_lookup_body(*, bank_code: str, account_number: str) -> dict[str, Any]:
    """
    JSON body for ``POST {base}/payout/account/lookup``.

    Must match Squad exactly: only ``bank_code`` and ``account_number`` (strings).
    Do **not** add ``key``, ``secret_key``, or any credential field — use
    ``Authorization: Bearer <SQUAD_SECRET_KEY>`` on the request (see ``squad_client.squad_headers``).
    """
    bc = str(bank_code).strip()
    acct = re.sub(r"\D", "", str(account_number).strip())
    return {"bank_code": bc, "account_number": acct}


def transaction_initiate_body(
    *,
    amount_kobo: int,
    email: str,
    currency: str,
    transaction_ref: str,
    callback_url: str,
    customer_name: str,
    payment_channels: list[str],
    is_recurring: bool,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    JSON body for ``POST /transaction/initiate``.

    Per Squad: authenticate with ``Authorization: Bearer <secret_key>`` only.
    Do **not** put ``key``, ``secret_key``, or any API key in this dict (Squad returns 400
    ``"key" is not allowed`` if disallowed fields are present).
    """
    return {
        "amount": str(int(amount_kobo)),
        "email": email.strip(),
        "currency": currency,
        "initiate_type": "inline",
        "transaction_ref": transaction_ref.strip(),
        "callback_url": callback_url.strip(),
        "customer_name": (customer_name or "Customer").strip()[:120],
        "payment_channels": list(payment_channels),
        "is_recurring": bool(is_recurring),
        "metadata": dict(metadata),
    }


def transaction_initiate_card_link_body(
    *,
    amount_kobo: int,
    email: str,
    currency: str,
    transaction_ref: str,
    callback_url: str,
    customer_name: str,
    payment_channels: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Body for ``POST /transaction/initiate`` when the goal is to **save/tokenize** a card.

    Squad expects ``is_recurring: true`` for reusable card token flows (token is delivered on
    charge_successful / payment_information, not always on verify). Amount is in **kobo** (₦1 = 100).
    """
    body = transaction_initiate_body(
        amount_kobo=amount_kobo,
        email=email,
        currency=currency,
        transaction_ref=transaction_ref,
        callback_url=callback_url,
        customer_name=customer_name,
        payment_channels=payment_channels,
        is_recurring=True,
        metadata=metadata,
    )
    if body.get("is_recurring") is not True:
        logger.error("card link initiate: is_recurring was not true — tokenization may fail")
    return body
