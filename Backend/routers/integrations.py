from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from database.session import get_db
from middleware.auth import get_current_user
from models.connected_card import ConnectedCard
from models.user import User
from schemas.integrations import (
    CardVerificationFinalizeOut,
    CardVerificationInitiateIn,
    CardVerificationInitiateOut,
    ConnectedCardOut,
    PaymentExecuteIn,
    PaymentExecuteOut,
)
from services import payment_execution_service, squad_card_service, squad_webhook_service

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)


def _callback_ok(url: str) -> bool:
    try:
        u = urlparse(str(url))
    except Exception:  # noqa: BLE001
        return False
    if u.scheme not in {"http", "https"} or not u.netloc:
        return False
    allowed = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    allowed_hosts = {urlparse(a.strip()).netloc for a in allowed if a.strip()}
    return u.netloc in allowed_hosts


@router.post("/squad/card-verification/initiate", response_model=CardVerificationInitiateOut)
def initiate_card_verification(
    payload: CardVerificationInitiateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CardVerificationInitiateOut:
    cb = str(payload.return_url).strip()
    if not _callback_ok(cb):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="return_url must be an allowed frontend origin.",
        )
    out = squad_card_service.initiate_card_verification_checkout(
        user_id=current_user.id,
        email=current_user.email,
        customer_name=current_user.full_name,
        callback_url=cb,
    )
    if not out.get("success"):
        msg = str(out.get("user_message") or "Card linking is unavailable.")
        ps = out.get("http_status")
        code: int | None = None
        if isinstance(ps, int):
            code = ps
        elif isinstance(ps, str) and ps.isdigit():
            code = int(ps)
        if code == 400:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        if code in (401, 403):
            raise HTTPException(status_code=code, detail=msg)
        if code is not None and 400 < code < 500:
            raise HTTPException(status_code=code, detail=msg)
        if code is not None and 500 <= code < 600:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=msg)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=msg)
    tx_ref = str(out.get("transaction_ref") or "")
    db.execute(
        update(ConnectedCard)
        .where(
            ConnectedCard.user_id == current_user.id,
            ConnectedCard.status == "pending",
        )
        .values(status="abandoned"),
    )
    row = ConnectedCard(
        user_id=current_user.id,
        squad_customer_id=f"confam_user_{current_user.id}",
        status="pending",
        verification_transaction_ref=tx_ref,
        reusable_reference=tx_ref,
        meta={"callback_url": cb},
    )
    db.add(row)
    db.commit()
    base = os.getenv("BACKEND_PUBLIC_URL", "").strip().rstrip("/")
    logger.info(
        "Squad card verify initiate user_id=%s transaction_ref=%s webhook_url=%s/webhooks/squad",
        current_user.id,
        tx_ref,
        base or "(set BACKEND_PUBLIC_URL for logs)",
    )
    return CardVerificationInitiateOut(
        checkout_url=str(out["checkout_url"]),
        transaction_ref=tx_ref,
    )


@router.post("/squad/card-verification/finalize", response_model=CardVerificationFinalizeOut)
def finalize_card_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CardVerificationFinalizeOut:
    """Complete card link via Squad verify API when webhooks cannot reach this server."""
    result = squad_webhook_service.finalize_pending_cards_from_squad_verify(db, current_user.id)
    if result.get("error") == "tokenization_failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(result.get("message") or "Card verification succeeded but tokenization failed."),
        )
    ok = bool(result.get("success"))
    return CardVerificationFinalizeOut(
        success=ok,
        message=str(result.get("message") or ("Done." if ok else "Could not finalize card link.")),
    )


@router.get("/squad/connected-card", response_model=ConnectedCardOut | None)
def get_connected_card(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectedCardOut | None:
    row = payment_execution_service.active_connected_card(db, current_user.id)
    if not row:
        return None
    brand = (row.card_type or "Card").strip().title()
    return ConnectedCardOut(
        status=row.status,
        card_type=row.card_type,
        masked_pan=row.masked_pan,
        last4=row.last4,
        brand_label=f"{brand} •••• {row.last4}" if row.last4 else brand,
    )


@router.delete("/squad/connected-card")
def remove_connected_card(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    db.execute(delete(ConnectedCard).where(ConnectedCard.user_id == current_user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/squad/payments/execute", response_model=PaymentExecuteOut)
def execute_payment(
    payload: PaymentExecuteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentExecuteOut:
    result = payment_execution_service.execute_confirmed_send(
        db,
        current_user,
        amount_kobo=payload.amount_kobo,
        recipient_account_number=payload.recipient_account_number,
        recipient_bank_name=payload.recipient_bank_name,
        recipient_account_name=payload.recipient_account_name.strip(),
        idempotency_key=payload.idempotency_key,
        assistant_message_id=payload.assistant_message_id,
    )
    ok = bool(result.get("success"))
    return PaymentExecuteOut(
        success=ok,
        message=str(result.get("user_message") or ("Done." if ok else "Payment could not be completed.")),
        transaction_id=result.get("transaction_id"),
        duplicate=bool(result.get("duplicate")),
        payout_deferred=bool(result.get("payout_deferred")),
    )
