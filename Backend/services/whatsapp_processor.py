"""Bridge WhatsApp Cloud webhooks into the existing Confam chat pipeline."""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.session import SessionLocal
from models.chat_session import ChatSession
from models.message import Message
from models.uploaded_file import UploadedFile
from models.user import User
from models.whatsapp_session import WhatsappInboundDedupe, WhatsappSession
from services import (
    chat_service,
    file_service,
    image_intent_service,
    intent_parser_service,
    payment_execution_service,
    whatsapp_auth_service,
    whatsapp_service,
)
from services.storage_service import FileKind

logger = logging.getLogger(__name__)

_FRIENDLY = "Confam is having trouble right now. Please try again."
_ECHO_FALLBACK = "Confam received your message."
_WA_ECHO_ONLY = os.getenv("WHATSAPP_ECHO_ONLY", "").strip().lower() in ("1", "true", "yes")


def wa_digits(phone_e164: str) -> str:
    return re.sub(r"\D", "", phone_e164 or "")


def _reply(to_wa_id: str, body: str) -> bool:
    ok = whatsapp_service.send_text(to_wa_id, body)
    if not ok:
        logger.error("WhatsApp reply not delivered to=%s", to_wa_id)
    return ok


def normalize_wa_sender(wa_from: str) -> str:
    """WhatsApp ``from`` to E.164 ``+234...`` style."""
    digits = re.sub(r"\D", "", wa_from or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = "234" + digits[1:]
    if len(digits) == 10:
        digits = "234" + digits
    return "+" + digits if digits else ""


def try_claim_wa_message_id(db: Session, wa_message_id: str) -> bool:
    """Return True if this message id was newly claimed (should process)."""
    if not wa_message_id:
        return True
    row = WhatsappInboundDedupe(wa_message_id=wa_message_id)
    db.add(row)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp dedupe insert failed — processing anyway")
        db.rollback()
        return True


def get_or_create_wa_context(db: Session, phone_e164: str) -> tuple[WhatsappSession, User]:
    row = db.scalar(select(WhatsappSession).where(WhatsappSession.user_phone == phone_e164))
    if row:
        row.last_active = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        u = db.get(User, row.user_id)
        if not u:
            raise RuntimeError("WhatsApp session missing user")
        return row, u

    user_obj = whatsapp_auth_service.synthetic_wa_user(db, phone_e164)

    chat = ChatSession(user_id=user_obj.id, title="WhatsApp")
    db.add(chat)
    db.flush()
    ws = WhatsappSession(
        user_phone=phone_e164,
        user_id=user_obj.id,
        chat_session_id=chat.id,
        linked_user_id=None,
        auth_pending_email=None,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws, user_obj


def _poll_assistant_message(db: Session, assistant_message_id: int, *, timeout_sec: float = 120.0) -> Message | None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        db.expire_all()
        m = db.get(Message, assistant_message_id)
        if m and (m.content or "").strip() and (m.content or "").strip() != chat_service.PROCESSING_PLACEHOLDER:
            return m
        time.sleep(0.35)
    return db.get(Message, assistant_message_id)


def _upload_bytes_to_db(
    db: Session,
    *,
    user_id: int,
    kind: FileKind,
    data: bytes,
    content_type: str,
    original_name: str,
) -> UploadedFile:
    path, bucket, pub = file_service.upload_bytes(
        user_id=user_id,
        kind=kind,
        data=data,
        content_type=content_type,
        original_name=original_name,
    )
    row = UploadedFile(
        user_id=user_id,
        storage_path=path,
        bucket_name=bucket,
        public_url=pub,
        file_type=kind,
        original_name=original_name,
        mime_type=content_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _try_execute_card_from_confirmation(db: Session, user: User, session_id: int, text: str) -> str | None:
    """
    If the user is confirming a pending payment card flow, charge the linked card (same as app execute).
    Returns a user-facing string to send on WhatsApp, or None to fall through to normal chat.
    """
    if not intent_parser_service.looks_like_transfer_confirmation(text.strip()):
        return None
    last_asst = db.scalar(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "assistant")
        .order_by(Message.id.desc()),
    )
    if not last_asst or not last_asst.payment_metadata:
        return None
    meta = last_asst.payment_metadata
    if not meta.get("is_payment_intent"):
        return None
    acct = re.sub(r"\D", "", str(meta.get("account_number") or ""))
    if len(acct) != 10:
        return None
    suggested = meta.get("suggested_amount")
    if suggested is None or str(suggested).strip() in ("", "?"):
        return (
            "I need the amount in naira before charging your linked card. "
            "Reply with a number (for example 5000), then say YES again."
        )
    try:
        naira = float(str(suggested).replace(",", ""))
        kobo = int(round(naira * 100))
    except ValueError:
        return "Could not read that amount. Reply with digits only (for example 5000)."
    if kobo < 100:
        return "That amount is too small to send."

    name = (
        str(meta.get("verified_account_name") or "").strip()
        or str(meta.get("display_account_name") or "").strip()
        or str(meta.get("ai_account_name") or "").strip()
    )
    if not name:
        return "Missing account name on file. Open Confam in the app to confirm this payment."

    bank = str(meta.get("bank_name") or "").strip() or None
    idem = f"wa_confirm_{last_asst.id}_{user.id}_{kobo}"
    out = payment_execution_service.execute_confirmed_send(
        db,
        user,
        amount_kobo=kobo,
        recipient_account_number=acct,
        recipient_bank_name=bank,
        recipient_account_name=name,
        idempotency_key=idem,
        assistant_message_id=last_asst.id,
    )
    ok = bool(out.get("success"))
    return str(out.get("user_message") or ("Payment completed." if ok else "Payment could not be completed."))


def _run_text(db: Session, user: User, session_id: int, text: str, to_wa_id: str) -> None:
    exec_reply = _try_execute_card_from_confirmation(db, user, session_id, text)
    if exec_reply:
        _reply(to_wa_id, exec_reply)
        return
    try:
        logger.info("AI CALLED: handle_text_turn session_id=%s", session_id)
        _, assistant = chat_service.handle_text_turn(db, user, session_id, text)
        reply = (assistant.content or "").strip() or _ECHO_FALLBACK
        logger.info("AI RESPONSE RECEIVED chars=%s", len(reply))
        _reply(to_wa_id, reply)
    except HTTPException:
        logger.warning("WhatsApp text turn rejected", exc_info=True)
        _reply(to_wa_id, _FRIENDLY)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp text turn failed")
        _reply(to_wa_id, _ECHO_FALLBACK)


def _run_voice(db: Session, user: User, session_id: int, uf: UploadedFile, to_wa_id: str) -> None:
    try:
        logger.info("AI CALLED: handle_voice_turn file_id=%s", uf.id)
        _, assistant = chat_service.handle_voice_turn(db, user, session_id, file_id=uf.id)
        _reply(to_wa_id, (assistant.content or "OK").strip() or "OK")
    except HTTPException:
        logger.warning("WhatsApp voice turn rejected", exc_info=True)
        _reply(to_wa_id, _FRIENDLY)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp voice turn failed")
        _reply(to_wa_id, _FRIENDLY)


def _run_image_shopping_deferred(
    db: Session,
    user: User,
    session_id: int,
    file_id: int,
    caption: str | None,
    to_wa_id: str,
) -> None:
    """Reuse deferred image job (payment slip detection + pricing) like the mobile client."""

    def _enqueue(fn: Callable[..., None], /, **kwargs: Any) -> None:
        fn(**kwargs)

    try:
        logger.info("AI CALLED: handle_image_turn_deferred file_id=%s", file_id)
        _, assistant = chat_service.handle_image_turn_deferred(
            db,
            user,
            session_id,
            file_id=file_id,
            caption=caption,
            enqueue=_enqueue,
        )
        final = _poll_assistant_message(db, assistant.id)
        body = (final.content if final else "") or _FRIENDLY
        if body.strip() == chat_service.PROCESSING_PLACEHOLDER:
            body = _FRIENDLY
        logger.info("AI RESPONSE RECEIVED (image) chars=%s", len(body))
        _reply(to_wa_id, body.strip() or _FRIENDLY)
    except HTTPException:
        logger.warning("WhatsApp image deferred turn rejected", exc_info=True)
        _reply(to_wa_id, _FRIENDLY)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp image deferred turn failed")
        _reply(to_wa_id, _FRIENDLY)


def _run_image_payment(db: Session, user: User, session_id: int, file_id: int, caption: str | None, to_wa_id: str) -> None:
    try:
        logger.info("AI CALLED: handle_payment_turn file_id=%s", file_id)
        _, assistant = chat_service.handle_payment_turn(
            db,
            user,
            session_id,
            file_id=file_id,
            accompanying_text=caption,
        )
        _reply(to_wa_id, (assistant.content or "OK").strip() or "OK")
    except HTTPException:
        logger.warning("WhatsApp payment image turn rejected", exc_info=True)
        _reply(to_wa_id, _FRIENDLY)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp payment image turn failed")
        _reply(to_wa_id, _FRIENDLY)


def process_whatsapp_payload(payload: dict[str, Any]) -> None:
    """Entry point from FastAPI BackgroundTasks (own DB session)."""
    logger.info("MESSAGE RECEIVED (background): object=%s", payload.get("object"))
    db = SessionLocal()
    try:
        found = False
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                messages = value.get("messages") or []
                if not messages and value.get("statuses"):
                    logger.debug("WEBHOOK: status-only notification (no user message)")
                for msg in messages:
                    found = True
                    _process_one_inbound(db, value, msg)
        if not found:
            logger.info("WEBHOOK: no messages[] in payload (statuses-only or empty)")
    except Exception:  # noqa: BLE001
        logger.exception("WEBHOOK BACKGROUND: unhandled error in process_whatsapp_payload")
    finally:
        db.close()


def _process_one_inbound(db: Session, value: dict[str, Any], msg: dict[str, Any]) -> None:
    phone_raw = str(msg.get("from") or "")
    to_wa_id = whatsapp_service.recipient_digits(phone_raw)
    wa_mid = str(msg.get("id") or "")
    mtype = str(msg.get("type") or "")

    logger.info(
        "MESSAGE PARSED id=%s from=%s type=%s",
        wa_mid or "(none)",
        phone_raw,
        mtype,
    )

    if not to_wa_id:
        logger.warning("WhatsApp inbound missing sender")
        return

    if _WA_ECHO_ONLY:
        logger.info("WHATSAPP_ECHO_ONLY: sending immediate ack")
        _reply(to_wa_id, _ECHO_FALLBACK)
        return

    try:
        if not try_claim_wa_message_id(db, wa_mid):
            logger.info("WEBHOOK: duplicate message id=%s skipped", wa_mid)
            return

        phone_e164 = normalize_wa_sender(phone_raw)
        if not phone_e164:
            logger.warning("WhatsApp inbound could not normalize phone from=%s", phone_raw)
            _reply(to_wa_id, _FRIENDLY)
            return

        try:
            ws, user = get_or_create_wa_context(db, phone_e164)
            session_id = ws.chat_session_id
            if whatsapp_auth_service.is_authenticated(ws):
                user = db.get(User, ws.linked_user_id) or user
        except Exception:  # noqa: BLE001
            logger.exception("WhatsApp get_or_create context failed")
            _reply(to_wa_id, _FRIENDLY)
            return

        if mtype == "text":
            body = str((msg.get("text") or {}).get("body") or "").strip()
            auth_reply = whatsapp_auth_service.handle_auth_text(
                db, ws, text=body, phone_e164=phone_e164,
            )
            if auth_reply is not None:
                _reply(to_wa_id, auth_reply)
                return
            if not body:
                _reply(to_wa_id, whatsapp_auth_service.WELCOME_MESSAGE)
                return
            _run_text(db, user, session_id, body, to_wa_id)
            return

        if not whatsapp_auth_service.is_authenticated(ws):
            _reply(to_wa_id, whatsapp_auth_service.LOGIN_REQUIRED_MESSAGE)
            return

        if mtype == "image":
            media = msg.get("image") or {}
            media_id = str(media.get("id") or "")
            caption = str(media.get("caption") or "").strip() or None
            if not media_id:
                _reply(to_wa_id, "I did not receive an image ID. Please resend the photo.")
                return
            dl = whatsapp_service.download_media_bytes(media_id)
            if not dl:
                _reply(to_wa_id, _FRIENDLY)
                return
            raw, mime = dl
            ext = ".jpg"
            if "png" in mime.lower():
                ext = ".png"
            elif "webp" in mime.lower():
                ext = ".webp"
            try:
                intent = image_intent_service.classify_image_intent((raw, mime), caption=caption)
                fk: FileKind = "payment_image" if intent == "payment" else "chat_image"
                uf = _upload_bytes_to_db(
                    db,
                    user_id=user.id,
                    kind=fk,
                    data=raw,
                    content_type=mime,
                    original_name=f"whatsapp_image{ext}",
                )
                if intent == "payment":
                    _run_image_payment(db, user, session_id, uf.id, caption, to_wa_id)
                else:
                    _run_image_shopping_deferred(db, user, session_id, uf.id, caption, to_wa_id)
            except file_service.StorageNotConfiguredError:
                _reply(to_wa_id, "File storage is not configured on this server.")
            except file_service.StorageOperationError:
                logger.warning("WhatsApp image storage failed", exc_info=True)
                _reply(to_wa_id, _FRIENDLY)
            except Exception:  # noqa: BLE001
                logger.exception("WhatsApp image pipeline failed")
                _reply(to_wa_id, _FRIENDLY)
            return

        if mtype in ("audio", "voice"):
            media = msg.get("audio") or msg.get("voice") or {}
            media_id = str(media.get("id") or "")
            if not media_id:
                _reply(to_wa_id, _FRIENDLY)
                return
            dl = whatsapp_service.download_media_bytes(media_id)
            if not dl:
                _reply(to_wa_id, _FRIENDLY)
                return
            raw, mime = dl
            ext = Path(f"x.{mime.split('/')[-1] if '/' in mime else 'bin'}").suffix or ".ogg"
            if ext not in {".ogg", ".opus", ".m4a", ".mp3", ".wav", ".webm", ".mpeg", ".mp4"}:
                ext = ".ogg"
            try:
                uf = _upload_bytes_to_db(
                    db,
                    user_id=user.id,
                    kind="voice_note",
                    data=raw,
                    content_type=mime,
                    original_name=f"whatsapp_voice{ext}",
                )
                _run_voice(db, user, session_id, uf, to_wa_id)
            except Exception:  # noqa: BLE001
                logger.exception("WhatsApp voice pipeline failed")
                _reply(to_wa_id, _FRIENDLY)
            return

        if mtype == "document":
            doc = msg.get("document") or {}
            media_id = str(doc.get("id") or "")
            mime_hint = str(doc.get("mime_type") or "application/octet-stream")
            caption = str(doc.get("caption") or "").strip() or None
            if not media_id:
                _reply(to_wa_id, _FRIENDLY)
                return
            dl = whatsapp_service.download_media_bytes(media_id)
            if not dl:
                _reply(to_wa_id, _FRIENDLY)
                return
            raw, mime = dl
            mime_use = mime_hint if mime_hint else mime
            if mime_use.startswith("image/"):
                ext = ".jpg" if "jpeg" in mime_use else Path(f"x.{mime_use.split('/')[-1]}").suffix or ".jpg"
                try:
                    intent = image_intent_service.classify_image_intent((raw, mime_use), caption=caption)
                    fk = "payment_image" if intent == "payment" else "chat_image"
                    uf = _upload_bytes_to_db(
                        db,
                        user_id=user.id,
                        kind=fk,
                        data=raw,
                        content_type=mime_use,
                        original_name=str(doc.get("filename") or f"whatsapp_doc{ext}"),
                    )
                    if intent == "payment":
                        _run_image_payment(db, user, session_id, uf.id, caption, to_wa_id)
                    else:
                        _run_image_shopping_deferred(db, user, session_id, uf.id, caption, to_wa_id)
                except Exception:  # noqa: BLE001
                    logger.exception("WhatsApp document image failed")
                    _reply(to_wa_id, _FRIENDLY)
            elif mime_use.startswith("audio/"):
                try:
                    uf = _upload_bytes_to_db(
                        db,
                        user_id=user.id,
                        kind="voice_note",
                        data=raw,
                        content_type=mime_use,
                        original_name="whatsapp_document_audio",
                    )
                    _run_voice(db, user, session_id, uf, to_wa_id)
                except Exception:  # noqa: BLE001
                    logger.exception("WhatsApp document audio failed")
                    _reply(to_wa_id, _FRIENDLY)
            else:
                _reply(
                    to_wa_id,
                    "I can read photos and voice notes on WhatsApp. Send a picture of the item or bank slip, or a voice note.",
                )
            return

        _reply(
            to_wa_id,
            "Confam on WhatsApp supports text, photos, and voice notes. Send your question or a picture of what you are buying.",
        )
    except Exception:  # noqa: BLE001
        logger.exception("WEBHOOK: _process_one_inbound failed for from=%s", phone_raw)
        _reply(to_wa_id, _ECHO_FALLBACK)
