"""Meta WhatsApp Cloud API webhooks (verification + inbound messages)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from services import whatsapp_processor

router = APIRouter(tags=["whatsapp"])

logger = logging.getLogger(__name__)

META_VERIFY_TOKEN = (os.getenv("META_VERIFY_TOKEN") or "").strip()
META_APP_SECRET = (os.getenv("META_APP_SECRET") or "").strip()
_SKIP_SIG = os.getenv("WHATSAPP_SKIP_SIGNATURE_VERIFY", "").strip().lower() in ("1", "true", "yes")


def _verify_signature(raw_body: bytes, sig_header: str | None) -> bool:
    if _SKIP_SIG:
        logger.warning("WHATSAPP_SKIP_SIGNATURE_VERIFY=1 — signature check disabled (dev only).")
        return True
    if not META_APP_SECRET:
        logger.warning("META_APP_SECRET unset — webhook signature verification skipped (dev only).")
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header[7:])


@router.get("/webhook/status")
def webhook_status() -> dict:
    """Diagnostics: is this process reachable and configured for Meta webhooks?"""
    public = (os.getenv("WEBHOOK_PUBLIC_URL") or os.getenv("BACKEND_PUBLIC_URL") or "").strip().rstrip("/")
    localhost = not public or "127.0.0.1" in public or "localhost" in public.lower()
    return {
        "ok": True,
        "callback_path": "/webhook",
        "meta_verify_token_set": bool(META_VERIFY_TOKEN),
        "meta_app_secret_set": bool(META_APP_SECRET),
        "meta_access_token_set": bool((os.getenv("META_ACCESS_TOKEN") or "").strip()),
        "meta_phone_number_id_set": bool((os.getenv("META_PHONE_NUMBER_ID") or "").strip()),
        "signature_verify_skipped": _SKIP_SIG or not META_APP_SECRET,
        "configured_public_url": public or None,
        "meta_can_use_localhost_url": localhost,
        "expected_meta_callback": "https://YOUR-NGROK-HOST/webhook (not 127.0.0.1)",
        "after_you_send_a_whatsapp_message_expect_log": "POST /webhook from confam.access",
    }


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta subscription verification (returns hub.challenge as plain text)."""
    if hub_mode == "subscribe" and hub_verify_token and META_VERIFY_TOKEN and hub_verify_token == META_VERIFY_TOKEN:
        logger.info("WEBHOOK VERIFY OK (hub.challenge returned)")
        return PlainTextResponse(content=str(hub_challenge or ""), status_code=200)
    logger.warning(
        "WEBHOOK GET /webhook without valid subscribe params mode=%s token_match=%s",
        hub_mode,
        hub_verify_token == META_VERIFY_TOKEN if hub_verify_token and META_VERIFY_TOKEN else False,
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Inbound WhatsApp events — acknowledge immediately, process in background."""
    logger.info("WEBHOOK HIT POST /webhook")
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_signature(raw, sig):
        logger.error(
            "WEBHOOK POST signature FAILED — Meta will not deliver messages until META_APP_SECRET "
            "matches Facebook App Settings → Basic → App secret (not the access token). "
            "header_present=%s body_bytes=%s",
            bool(sig),
            len(raw),
        )
        return Response(content="Forbidden", status_code=403)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("WEBHOOK: invalid JSON body bytes=%s", len(raw))
        return Response(content="Bad Request", status_code=400)
    if not isinstance(payload, dict):
        return Response(content="Bad Request", status_code=400)
    obj = payload.get("object")
    if obj and obj != "whatsapp_business_account":
        logger.info("WEBHOOK: ignored object=%s", obj)
        return Response(status_code=200)

    msg_count = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            msg_count += len((change.get("value") or {}).get("messages") or [])
    logger.info("WEBHOOK: parsed object=%s inbound_messages=%s", obj, msg_count)

    background_tasks.add_task(whatsapp_processor.process_whatsapp_payload, payload)
    logger.info("WEBHOOK: enqueued background processor")
    return Response(content="OK", status_code=200)
