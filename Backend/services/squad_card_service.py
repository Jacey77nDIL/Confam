"""Squad card verification (₦100 minimum) + refund + charge saved authorization."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from typing import Any
from urllib.parse import quote

from services import squad_client, squad_response, squad_service

logger = logging.getLogger(__name__)

# Squad rejects amounts below ₦100 ("Minimum amount is 100 Naira").
_CARD_VERIFY_AMOUNT_KOBO = 10_000  # ₦100
_REFUND_PATH = "/transaction/refund"
_CHARGE_CARD_PATH = "/transaction/charge_card"
_VERIFY_PATH_TMPL = "/transaction/verify/{transaction_ref}"


def _verify_transaction_get(
    transaction_ref: str,
) -> tuple[int, dict[str, Any] | None]:
    """GET /transaction/verify — shared by gateway extraction, refund helpers, and finalize."""
    if not squad_client.squad_is_configured():
        return 0, None
    ref = quote(transaction_ref.strip(), safe="")
    if not ref:
        return 0, None
    path = _VERIFY_PATH_TMPL.format(transaction_ref=ref)
    status, data = squad_client.squad_get(path)
    if status == 404:
        q = quote(transaction_ref.strip(), safe="")
        status, data = squad_client.squad_get(f"/transaction/verify?transaction_ref={q}")
    if not isinstance(data, dict):
        return status, None
    return status, data


def _squad_body_message(data: dict[str, Any]) -> str:
    return str(data.get("message") or data.get("Message") or "").strip()[:500]


def initiate_card_verification_checkout(
    *,
    user_id: int,
    email: str,
    customer_name: str,
    callback_url: str,
) -> dict[str, Any]:
    """
    Start Squad inline checkout for recurring/tokenized card (₦100 hold, refunded after verification).

    Auth: ``Authorization: Bearer <SQUAD_SECRET_KEY>`` only — no ``key`` in JSON.

    Returns keys include ``http_status`` (Squad HTTP status when known) for API mapping.
    """
    if not squad_client.squad_is_configured():
        return {
            "success": False,
            "checkout_url": None,
            "transaction_ref": None,
            "user_message": "Card linking is not available on this server yet.",
            "raw_status": None,
            "http_status": None,
        }

    tx_ref = f"CFM_CARD_{user_id}_{uuid.uuid4().hex[:20].upper()}"
    meta: dict[str, Any] = {
        "purpose": "card_verification",
        "user_id": str(user_id),
        "confam_version": "1",
    }
    body = squad_service.transaction_initiate_card_link_body(
        amount_kobo=_CARD_VERIFY_AMOUNT_KOBO,
        email=email,
        currency="NGN",
        transaction_ref=tx_ref,
        callback_url=callback_url,
        customer_name=customer_name or "Confam user",
        payment_channels=["card"],
        metadata=meta,
    )

    path = squad_service.TRANSACTION_INITIATE_PATH
    status, data = squad_client.squad_post(path, body)

    if not isinstance(data, dict):
        return {
            "success": False,
            "checkout_url": None,
            "transaction_ref": tx_ref,
            "user_message": squad_client.user_facing_error(status or 500, {}),
            "raw_status": status,
            "http_status": status,
        }

    msg = _squad_body_message(data) or squad_client.user_facing_error(status, data)

    if status in (401, 403):
        return {
            "success": False,
            "checkout_url": None,
            "transaction_ref": tx_ref,
            "user_message": msg
            or (
                "Squad rejected your API key. Use sandbox_sk_… with "
                "SQUAD_API_BASE=https://sandbox-api-d.squadco.com (or live keys with https://api-d.squadco.com)."
            ),
            "raw_status": status,
            "http_status": status,
        }

    if status != 200 or squad_response.squad_envelope_failed(data):
        return {
            "success": False,
            "checkout_url": None,
            "transaction_ref": tx_ref,
            "user_message": msg or "Could not start Squad checkout.",
            "raw_status": status,
            "http_status": status,
        }

    inner = data.get("data")
    checkout = None
    if isinstance(inner, dict):
        checkout = inner.get("checkout_url") or inner.get("checkoutUrl")
    if checkout and isinstance(checkout, str):
        return {
            "success": True,
            "checkout_url": checkout,
            "transaction_ref": tx_ref,
            "user_message": "ok",
            "raw_status": status,
            "http_status": status,
        }

    return {
        "success": False,
        "checkout_url": None,
        "transaction_ref": tx_ref,
        "user_message": msg or "Squad did not return a checkout URL.",
        "raw_status": status,
        "http_status": status,
    }


def fetch_gateway_transaction_ref(*, transaction_ref: str) -> str | None:
    """
    Squad GET /transaction/verify/{transaction_ref} — use when webhooks omit gateway_ref
    so refunds can be posted (dashboard shows refund against the gateway transaction).
    """
    status, data = _verify_transaction_get(transaction_ref)
    if not isinstance(data, dict) or squad_response.squad_envelope_failed(data):
        logger.warning(
            "Squad verify transaction failed for ref=%s http=%s",
            transaction_ref[:48],
            status,
        )
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else None
    inner_alt = data.get("Data") if isinstance(data.get("Data"), dict) else None
    blobs: list[dict[str, Any]] = []
    for blob in (inner, inner_alt, data):
        if isinstance(blob, dict):
            blobs.append(blob)
    for blob in blobs:
        for key in (
            "gateway_transaction_ref",
            "gateway_ref",
            "GatewayTransactionRef",
            "gatewayTransactionRef",
        ):
            val = blob.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def fetch_verify_transaction_merged(*, transaction_ref: str) -> dict[str, Any] | None:
    """
    Successful verify payload merged for reading payment_information / token_id
    (used when webhooks never reach this host, e.g. localhost).
    """
    _status, data, shards = verify_transaction_dict_shards(transaction_ref)
    if not data or squad_response.squad_envelope_failed(data) or not shards:
        logger.info(
            "Squad verify (merged) not OK for ref=%s message=%s",
            transaction_ref[:48],
            str(data.get("message") or data.get("Message") or "")[:200] if isinstance(data, dict) else "",
        )
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else None
    inner_alt = data.get("Data") if isinstance(data.get("Data"), dict) else None
    core = inner or inner_alt
    if isinstance(core, dict):
        merged: dict[str, Any] = {**data, **core}
        return merged
    return data


def verify_transaction_dict_shards(
    transaction_ref: str,
) -> tuple[int, dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Raw verify envelope plus dict fragments for token extraction (nested data / card_details).
    On API error or failed envelope, ``shards`` is empty; ``data`` may still hold the JSON body for logging.
    """
    status, data = _verify_transaction_get(transaction_ref)
    if not isinstance(data, dict):
        return status, None, []
    if squad_response.squad_envelope_failed(data):
        return status, data, []
    shards: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add(blob: dict[str, Any]) -> None:
        bid = id(blob)
        if bid in seen:
            return
        seen.add(bid)
        shards.append(blob)

    add(data)
    for key in ("data", "Data"):
        inner = data.get(key)
        if isinstance(inner, dict):
            add(inner)
            for subk in (
                "payment_information",
                "paymentInformation",
                "card_details",
                "cardDetails",
                "CardDetails",
            ):
                sub = inner.get(subk)
                if isinstance(sub, dict):
                    add(sub)
            nested = inner.get("data") or inner.get("Data")
            if isinstance(nested, dict):
                add(nested)
                for subk in ("payment_information", "paymentInformation", "card_details", "cardDetails"):
                    sub = nested.get(subk)
                    if isinstance(sub, dict):
                        add(sub)
    return status, data, shards


def refund_full_transaction(
    *,
    gateway_transaction_ref: str,
    transaction_ref: str,
    reason: str = "Confam card verification hold",
) -> dict[str, Any]:
    """Refund a captured card verification charge (₦100 in sandbox when using Squad minimum)."""
    if not squad_client.squad_is_configured():
        return {"success": False, "user_message": "Refund skipped: provider not configured."}
    payloads: list[dict[str, Any]] = [
        {
            "gateway_transaction_ref": gateway_transaction_ref.strip(),
            "transaction_ref": transaction_ref.strip(),
            "refund_type": "Full",
            "reason_for_refund": reason[:200],
        },
        {
            "gatewayTransactionRef": gateway_transaction_ref.strip(),
            "transactionRef": transaction_ref.strip(),
            "refundType": "Full",
            "reasonForRefund": reason[:200],
        },
    ]
    last: dict[str, Any] = {"success": False, "user_message": "Refund could not be started."}
    logger.info(
        "Squad refund POST /transaction/refund starting transaction_ref=%r gateway_transaction_ref=%r",
        transaction_ref[:96],
        gateway_transaction_ref[:96],
    )
    for body in payloads:
        status, data = squad_client.squad_post(_REFUND_PATH, body)
        if not isinstance(data, dict):
            last = {"success": False, "user_message": squad_client.user_facing_error(status or 500, {})}
            continue
        ok = status == 200 and not squad_response.squad_envelope_failed(data)
        if ok:
            inner = data.get("data") if isinstance(data.get("data"), dict) else {}
            logger.info(
                "Squad refund API accepted transaction_ref=%s gateway_refund_status=%s",
                transaction_ref[:64],
                inner.get("gateway_refund_status") if isinstance(inner, dict) else None,
            )
            return {"success": True, "user_message": "ok", "data": data.get("data")}
        last = {"success": False, "user_message": squad_client.user_facing_error(status, data)}
        logger.warning(
            "Squad refund HTTP %s for transaction_ref=%s message=%s",
            status,
            transaction_ref[:64],
            str(data.get("message") or data.get("Message") or "")[:400],
        )
    return last


def charge_saved_card(
    *,
    amount_kobo: int,
    token_id: str,
    transaction_ref: str | None = None,
) -> dict[str, Any]:
    """Charge a tokenized card (customer-initiated send flow)."""
    if not squad_client.squad_is_configured():
        return {"success": False, "user_message": "Payments are not configured.", "data": None}
    if amount_kobo < 100:
        return {"success": False, "user_message": "Amount is too small to process.", "data": None}
    tx = transaction_ref or f"CFM_CHG_{secrets.token_hex(12).upper()}"
    body: dict[str, Any] = {
        "amount": int(amount_kobo),
        "token_id": token_id.strip(),
        "transaction_ref": tx,
    }
    status, data = squad_client.squad_post(_CHARGE_CARD_PATH, body)
    if not isinstance(data, dict):
        return {"success": False, "user_message": squad_client.user_facing_error(status or 500, {}), "data": None}
    ok = status == 200 and not squad_response.squad_envelope_failed(data)
    if not ok:
        return {
            "success": False,
            "user_message": squad_client.user_facing_error(status, data),
            "data": data.get("data"),
        }
    return {"success": True, "user_message": "ok", "data": data.get("data"), "transaction_ref": tx}


def parse_masked_pan(pan_field: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Squad may return e.g. '509983******3911|1027' (PAN|expiry MMYY).
    Returns: masked_pan, last4, expiry_month, expiry_year
    """
    if not pan_field or not isinstance(pan_field, str):
        return None, None, None, None
    raw = pan_field.strip()
    parts = raw.split("|")
    pan = parts[0].strip() if parts else raw
    last4 = None
    digits = re.sub(r"\D", "", pan)
    if len(digits) >= 4:
        last4 = digits[-4:]
    exp_m = exp_y = None
    if len(parts) > 1:
        exp = re.sub(r"\D", "", parts[1])
        if len(exp) >= 4:
            exp_m, exp_y = exp[:2], exp[2:4]
            exp_y = f"20{exp_y}" if len(exp_y) == 2 else exp_y
    return pan or None, last4, exp_m, exp_y
