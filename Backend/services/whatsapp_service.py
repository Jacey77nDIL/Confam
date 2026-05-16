"""Outbound WhatsApp Cloud API calls (Graph) with retries and WABA webhook subscription."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_BUSINESS_ID,
    WHATSAPP_GRAPH_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)

META_ACCESS_TOKEN = WHATSAPP_ACCESS_TOKEN
META_PHONE_NUMBER_ID = WHATSAPP_PHONE_NUMBER_ID
META_GRAPH_VERSION = WHATSAPP_GRAPH_API_VERSION

_MAX_RETRIES = 3
_RETRY_SLEEP = 0.75


def _graph_base() -> str:
    return f"https://graph.facebook.com/{META_GRAPH_VERSION}"


def is_configured() -> bool:
    return bool(META_ACCESS_TOKEN and META_PHONE_NUMBER_ID)


def _meta_error_summary(data: dict[str, Any] | None, status: int) -> str:
    if not data or not isinstance(data, dict):
        return f"HTTP {status}"
    err = data.get("error")
    if isinstance(err, dict):
        code = err.get("code", "?")
        sub = err.get("error_subcode", "")
        msg = err.get("message", "")
        return f"HTTP {status} code={code} subcode={sub} message={msg}"
    return f"HTTP {status} {data!r}"[:400]


async def subscribe_app_to_waba() -> bool:
    """
    Subscribe this Meta app to the WhatsApp Business Account so message webhooks are delivered.

    POST https://graph.facebook.com/{version}/{WHATSAPP_BUSINESS_ID}/subscribed_apps
    """
    if not WHATSAPP_BUSINESS_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.warning(
            "WhatsApp Webhook Subscription: SKIPPED — set WHATSAPP_BUSINESS_ID and "
            "WHATSAPP_ACCESS_TOKEN (or META_BUSINESS_ACCOUNT_ID / META_ACCESS_TOKEN) in .env",
        )
        return False

    url = f"{_graph_base()}/{WHATSAPP_BUSINESS_ID}/subscribed_apps"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        logger.error("WhatsApp Webhook Subscription: FAILED — request error: %s", exc)
        return False

    body: dict[str, Any] | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:  # noqa: BLE001
        body = None

    if response.status_code == 200:
        success_flag = body.get("success") if body else True
        if success_flag is True or success_flag is None:
            logger.info(
                "WhatsApp Webhook Subscription: SUCCESS (WABA=%s graph=%s)",
                WHATSAPP_BUSINESS_ID,
                META_GRAPH_VERSION,
            )
            return True
        logger.error(
            "WhatsApp Webhook Subscription: FAILED — %s",
            _meta_error_summary(body, response.status_code),
        )
        return False

    logger.error(
        "WhatsApp Webhook Subscription: FAILED — %s response=%s",
        _meta_error_summary(body, response.status_code),
        (response.text or "")[:500],
    )
    return False


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def recipient_digits(wa_from: str) -> str:
    """Use Meta webhook ``from`` as-is (digits only) — do not re-normalize country codes."""
    return "".join(c for c in str(wa_from or "") if c.isdigit())


def send_text(to_wa_id: str, body: str) -> bool:
    """
    Send a WhatsApp text message.

    ``to_wa_id`` must be the recipient wa_id from the webhook ``from`` field (digits only).
    """
    if not is_configured():
        logger.error(
            "SENDING WHATSAPP REPLY skipped: META_ACCESS_TOKEN or META_PHONE_NUMBER_ID unset "
            "(token_set=%s phone_id_set=%s)",
            bool(META_ACCESS_TOKEN),
            bool(META_PHONE_NUMBER_ID),
        )
        return False
    text = (body or "").strip()
    if not text:
        text = "Confam received your message."
    if len(text) > 4090:
        text = text[:4087] + "…"
    to = recipient_digits(to_wa_id)
    if not to:
        logger.error("SENDING WHATSAPP REPLY skipped: empty recipient from %r", to_wa_id)
        return False
    url = f"{_graph_base()}/{META_PHONE_NUMBER_ID}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    logger.info("SENDING WHATSAPP REPLY to=%s chars=%s", to, len(text))
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=45.0) as client:
                r = client.post(url, headers=_headers(), json=payload)
                if r.status_code >= 500:
                    last_err = RuntimeError(f"HTTP {r.status_code}: {(r.text or '')[:300]}")
                    time.sleep(_RETRY_SLEEP * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    logger.error(
                        "SENDING WHATSAPP REPLY failed HTTP %s body=%s",
                        r.status_code,
                        (r.text or "")[:800],
                    )
                    return False
                logger.info(
                    "REPLY SENT SUCCESSFULLY to=%s status=%s body=%s",
                    to,
                    r.status_code,
                    (r.text or "")[:400],
                )
                return True
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("WhatsApp send attempt %s failed: %s", attempt + 1, exc)
            time.sleep(_RETRY_SLEEP * (attempt + 1))
    logger.error("WhatsApp send failed after retries: %s", last_err)
    return False


def fetch_media_url(media_id: str) -> str | None:
    """Resolve Graph media id to a short-lived download URL."""
    if not is_configured() or not media_id:
        return None
    url = f"{_graph_base()}/{media_id}"
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=45.0) as client:
                r = client.get(url, headers=_headers())
                if r.status_code >= 400:
                    logger.warning("WhatsApp media URL HTTP %s", r.status_code)
                    return None
                data = r.json()
                u = data.get("url")
                return str(u) if isinstance(u, str) and u.startswith("http") else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("WhatsApp fetch_media_url attempt %s: %s", attempt + 1, exc)
            time.sleep(_RETRY_SLEEP * (attempt + 1))
    return None


def download_media_bytes(media_id: str) -> tuple[bytes, str] | None:
    """Download binary from Graph (metadata URL then binary GET). Returns (bytes, mime_type)."""
    dl = fetch_media_url(media_id)
    if not dl:
        return None
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.get(dl, headers=_headers())
                if r.status_code >= 400:
                    logger.warning("WhatsApp media download HTTP %s", r.status_code)
                    return None
                mime = r.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
                return r.content, mime or "application/octet-stream"
        except Exception as exc:  # noqa: BLE001
            logger.warning("WhatsApp download_media_bytes attempt %s: %s", attempt + 1, exc)
            time.sleep(_RETRY_SLEEP * (attempt + 1))
    return None
