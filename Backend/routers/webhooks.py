from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response

from services import squad_webhook_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _process_squad_webhook_payload(data: dict[str, Any]) -> None:
    """
    Background entrypoint for accepted Squad webhooks.

    ``squad_webhook_service.process_webhook_json`` updates payments (``FUNDS_COLLECTED``),
    card links, and may upsert ``saved_recipients`` when bank + account details are present.
    """
    try:
        squad_webhook_service.process_webhook_json(data)
    except Exception:  # noqa: BLE001
        logger.exception("Squad webhook background processing failed after HTTP 200")


@router.post("/squad")
async def squad_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Squad payment webhooks. ``squad_webhook_service.process_webhook_json`` applies outcomes:
    card verification tokenization, and for chat sends sets ``FUNDS_COLLECTED`` when the charge is confirmed.
    """
    raw = await request.body()
    sig = request.headers.get("x-squad-encrypted-body") or request.headers.get("X-Squad-Encrypted-Body")
    ok, reason = squad_webhook_service.verify_signature_detailed(raw, sig)
    if not ok:
        logger.warning(
            "Squad webhook REJECTED: signature failed reason=%s raw_bytes=%s header_present=%s",
            reason,
            len(raw),
            bool(sig and str(sig).strip()),
        )
        return Response(content="invalid signature", status_code=401)
    logger.info(
        "Squad webhook ACCEPTED signature=%s raw_bytes=%s — queuing handler",
        reason,
        len(raw),
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Squad webhook: invalid JSON body bytes=%s", len(raw))
        return Response(content="invalid json", status_code=400)
    if not isinstance(data, dict):
        return Response(content="invalid payload", status_code=400)
    background_tasks.add_task(_process_squad_webhook_payload, data)
    return Response(content="ok", status_code=200)
