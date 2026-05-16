"""Orchestrate Squad card charge for chat sends; outbound wallet payout is disabled (collection-only)."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.chat_session import ChatSession
from models.connected_card import ConnectedCard
from models.message import Message
from models.payment_transaction import PaymentTransaction
from models.user import User
from services import recipient_service, squad_card_service
from utils.nip_banks import nip_candidates_for_bank_name

logger = logging.getLogger(__name__)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _payout_bank_code_from_context(bank_name: str | None) -> str | None:
    """Local NIP mapping (no Squad lookup). Accepts 3–6 digit bank codes or a bank name string."""
    raw = (bank_name or "").strip()
    if not raw:
        return None
    if raw.isdigit() and 3 <= len(raw) <= 6:
        return raw
    cands = nip_candidates_for_bank_name(raw)
    return cands[0] if cands else None


def active_connected_card(db: Session, user_id: int) -> ConnectedCard | None:
    return db.scalar(
        select(ConnectedCard)
        .where(
            ConnectedCard.user_id == user_id,
            ConnectedCard.status == "active",
            ConnectedCard.authorization_token.isnot(None),
        )
        .order_by(ConnectedCard.id.desc()),
    )


def execute_confirmed_send(
    db: Session,
    user: User,
    *,
    amount_kobo: int,
    recipient_account_number: str,
    recipient_bank_name: str | None,
    recipient_account_name: str,
    idempotency_key: str,
    assistant_message_id: int | None = None,
) -> dict[str, Any]:
    """
    Charge saved card; record FUNDS_COLLECTED and manual disbursement note (no auto payout).
    Idempotent via idempotency_key.
    """
    key = (idempotency_key or "").strip()[:128]
    if not key:
        return {"success": False, "user_message": "Missing idempotency key. Please try again."}

    existing = db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.user_id == user.id,
            PaymentTransaction.idempotency_key == key,
        ),
    )
    if existing:
        if existing.status in ("success", PaymentTransaction.STATUS_FUNDS_COLLECTED):
            return {
                "success": True,
                "user_message": "This payment was already completed.",
                "transaction_id": existing.id,
                "duplicate": True,
                "payout_deferred": existing.status == PaymentTransaction.STATUS_FUNDS_COLLECTED,
            }
        return {
            "success": False,
            "user_message": "A previous attempt for this confirmation is still being processed.",
            "transaction_id": existing.id,
        }

    acct = _digits(recipient_account_number)
    if len(acct) != 10:
        return {"success": False, "user_message": "Recipient account number must be 10 digits."}

    if amount_kobo < 100:
        return {"success": False, "user_message": "Amount is too small to send."}

    card = active_connected_card(db, user.id)
    if not card or not card.authorization_token:
        return {"success": False, "user_message": "Connect a card in Confam before sending from chat."}

    if assistant_message_id is not None:
        msg = db.get(Message, assistant_message_id)
        if (
            not msg
            or msg.role != "assistant"
            or msg.session_id is None
        ):
            return {"success": False, "user_message": "That confirmation is no longer valid. Refresh chat."}
        chat = db.get(ChatSession, msg.session_id)
        if not chat or chat.user_id != user.id:
            return {"success": False, "user_message": "You cannot confirm a payment for another account."}
        meta = msg.payment_metadata or {}
        meta_acct = _digits(str(meta.get("account_number") or ""))
        if meta_acct and meta_acct != acct:
            return {"success": False, "user_message": "Recipient details do not match the assistant message."}
        if not recipient_bank_name and meta.get("bank_name"):
            recipient_bank_name = str(meta.get("bank_name"))

    # --- Squad account / name lookup (NIP resolve) — temporarily disabled; restore later.
    # lookup = account_lookup_service.resolve_nigerian_bank_account(
    #     bank_name=recipient_bank_name,
    #     account_number=acct,
    # )
    # if not lookup.get("success"):
    #     return {
    #         "success": False,
    #         "user_message": lookup.get("message")
    #         or "Could not verify that bank account before sending.",
    #     }
    # verified_name = str(lookup.get("verified_account_name") or "").strip()
    # bank_code = str(lookup.get("bank_code") or "").strip()
    # if not verified_name or not bank_code:
    #     return {"success": False, "user_message": "Could not verify that bank account before sending."}

    bank_code = _payout_bank_code_from_context(recipient_bank_name)
    if not bank_code:
        return {
            "success": False,
            "user_message": (
                "Could not determine bank code from the bank name. "
                "Use a clearer bank name, or enter a 3–6 digit bank code if your client sends one."
            ),
        }
    verified_name = (recipient_account_name or "").strip()
    if not verified_name:
        return {"success": False, "user_message": "Recipient account name is required to send."}

    row = PaymentTransaction(
        user_id=user.id,
        recipient_name=verified_name[:255],
        recipient_account=acct,
        recipient_bank=(recipient_bank_name or bank_code or "Bank")[:255],
        amount_kobo=int(amount_kobo),
        status="processing",
        squad_reference=None,
        authorization_reference=None,
        idempotency_key=key,
        meta={"assistant_message_id": assistant_message_id},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    charge = squad_card_service.charge_saved_card(
        amount_kobo=int(amount_kobo),
        token_id=card.authorization_token,
    )
    if not charge.get("success"):
        row.status = "failed"
        row.meta = {**(row.meta or {}), "charge_error": charge.get("user_message")}
        db.add(row)
        db.commit()
        return {"success": False, "user_message": str(charge.get("user_message")), "transaction_id": row.id}

    charge_ref = charge.get("transaction_ref")
    cdata = charge.get("data")
    if isinstance(cdata, dict):
        charge_ref = cdata.get("transaction_ref") or cdata.get("transactionRef") or charge_ref
    charge_ref_str = str(charge_ref) if charge_ref else None
    row.authorization_reference = (charge_ref_str[:255] if charge_ref_str else None)

    disburse_note = (
        f"Funds held in Confam balance. Manual disbursement required for Ref: {charge_ref_str or 'unknown'} "
        f"to Account: {acct}."
    )
    row.status = PaymentTransaction.STATUS_FUNDS_COLLECTED
    row.meta = {
        **(row.meta or {}),
        "collection_only": True,
        "manual_disbursement_note": disburse_note,
        "recipient_bank_code": bank_code,
        "charge_reference": charge_ref_str,
    }
    # Outbound Squad wallet payout disabled (e.g. merchant not profiled for transfers).
    # xfer = squad_payout_service.initiate_transfer(
    #     amount_kobo=int(amount_kobo),
    #     bank_code=bank_code,
    #     account_number=acct,
    #     account_name=verified_name,
    #     unique_suffix=suffix,
    #     remark="Confam chat send",
    # )
    # if not xfer.get("success"):
    #     row.status = "failed"
    #     ...
    logger.info("payment_execution: %s", disburse_note)
    db.add(row)
    db.commit()

    recipient_service.record_recipient(
        db,
        user.id,
        display_name=verified_name,
        account_number=acct,
        bank_name=recipient_bank_name,
        extra_alias=recipient_account_name.strip()[:120] if recipient_account_name else None,
        tx_ref=charge_ref_str or f"payment-tx-{row.id}",
        account_name=(verified_name or "").strip() or None,
    )
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        logger.warning(
            "payment_execution: commit after record_recipient failed user_id=%s payment_transactions.id=%s",
            user.id,
            row.id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("payment_execution rollback after recipient commit failure", exc_info=True)
    return {
        "success": True,
        "user_message": (
            "Payment complete. Your card was charged successfully. "
            "Your recipient will receive the transfer after Confam completes manual disbursement."
        ),
        "transaction_id": row.id,
        "payout_deferred": True,
    }
