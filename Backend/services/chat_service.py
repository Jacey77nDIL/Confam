"""Chat orchestration: persistence + OpenRouter + multimodal turns."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from openai import APIError, BadRequestError
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.session import SessionLocal
from models.chat_session import ChatSession
from models.message import Message
from models.payment_extraction import PaymentExtraction
from models.saved_recipient import SavedRecipient
from models.uploaded_file import UploadedFile
from models.user import User
from services import (
    account_lookup_service,
    ai_service,
    image_intent_service,
    intent_parser_service,
    market_pipeline_service,
    message_classifier_service,
    money_send_helpers,
    openrouter_service,
    payment_extraction_service,
    payment_service,
    product_identification_service,
    recipient_service,
    storage_service,
    transcription_service,
)

logger = logging.getLogger(__name__)

_ASSISTANT_PLACEHOLDER = "Processing…"
# Public alias for other modules (e.g. WhatsApp) that poll until the assistant reply is ready.
PROCESSING_PLACEHOLDER = _ASSISTANT_PLACEHOLDER


def _touch_session(db: Session, session: ChatSession) -> None:
    session.updated_at = datetime.now(timezone.utc)
    db.add(session)


def get_owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return session


def get_owned_file(db: Session, user: User, file_id: int) -> UploadedFile:
    f = db.get(UploadedFile, file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return f


def _mime_base(mime: str | None) -> str:
    if not mime:
        return "application/octet-stream"
    return mime.split(";")[0].strip().lower()


def _legacy_upload_unavailable(uf: UploadedFile) -> bool:
    return (uf.storage_path or "").startswith("legacy-local/")


def _download_uploaded_media(uf: UploadedFile) -> tuple[bytes, str]:
    if _legacy_upload_unavailable(uf):
        raise FileNotFoundError("legacy upload")
    raw = storage_service.download_bytes(uf.storage_path, uf.bucket_name)
    return raw, _mime_base(uf.mime_type)


def build_text_history(
    db: Session,
    session_id: int,
    *,
    limit: int = 24,
    before_message_id: int | None = None,
) -> list[dict]:
    q = select(Message).where(Message.session_id == session_id).order_by(Message.id.asc())
    if before_message_id is not None:
        q = q.where(Message.id < before_message_id)
    rows = db.scalars(q).all()
    out: list[dict] = []
    for m in rows:
        if m.role not in {"user", "assistant"}:
            continue
        if m.role == "assistant":
            out.append({"role": "assistant", "content": m.content or ""})
            continue
        if m.msg_type == "voice" and m.transcript:
            out.append({"role": "user", "content": m.transcript})
        elif m.msg_type == "text" and m.content:
            out.append({"role": "user", "content": m.content})
        elif m.msg_type == "payment_image" and m.ocr_payload:
            note = (m.content or "").strip()
            blob = json.dumps(m.ocr_payload, ensure_ascii=False)
            if note and note != "Payment screenshot":
                out.append(
                    {
                        "role": "user",
                        "content": f'User message with payment screenshot: "{note}"\nStructured OCR: {blob}',
                    },
                )
            else:
                out.append(
                    {
                        "role": "user",
                        "content": "Payment slip OCR (structured): " + blob,
                    },
                )
        elif m.msg_type == "image":
            out.append(
                {
                    "role": "user",
                    "content": m.content or "[User attached a product photo]",
                },
            )
    return out[-limit:]


def _format_naira_display(suggested: str | None) -> str:
    if not suggested or suggested in ("?", ""):
        return "the amount"
    try:
        v = float(str(suggested).replace(",", ""))
        if abs(v - round(v)) < 1e-9:
            return f"₦{int(round(v)):,}"
        return f"₦{v:,.2f}".rstrip("0").rstrip(".")
    except ValueError:
        return f"₦{suggested}"


def _latest_user_transfer_intent(
    db: Session,
    session_id: int,
    *,
    before_message_id: int,
) -> intent_parser_service.TransferIntent | None:
    """Most recent user text in the session that looks like ``send … to {name}`` (skips bare confirmations)."""
    rows = db.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.role == "user",
            Message.id < before_message_id,
            Message.msg_type.in_(("text", "voice")),
        )
        .order_by(Message.id.desc())
        .limit(40),
    ).all()
    for m in rows:
        raw = (m.content or "").strip()
        if m.msg_type == "voice" and (m.transcript or "").strip():
            raw = (m.transcript or "").strip()
        if not raw:
            continue
        if intent_parser_service.looks_like_transfer_confirmation(raw):
            continue
        it = intent_parser_service.parse_transfer_intent(raw)
        if it.is_transfer and it.recipient_query:
            return it
    return None


def _payment_card_payload(
    user_msg: Message,
    row: SavedRecipient,
    amount_naira: float | None,
) -> tuple[str, dict[str, Any]]:
    suggested: str | None = None
    if amount_naira is not None:
        suggested = (
            str(int(amount_naira))
            if abs(amount_naira - int(amount_naira)) < 1e-9
            else f"{amount_naira:.2f}".rstrip("0").rstrip(".")
        )
    if suggested is None:
        cap = (user_msg.content or "").strip() or (user_msg.transcript or "").strip()
        suggested = money_send_helpers.suggested_amount_from_caption(cap or None)
    display = (row.display_name or row.account_name or "Recipient").strip()
    bank = (row.bank_name or "Bank").strip()
    lk = account_lookup_service.lookup_stub_response(account_number=row.account_number)
    smart = money_send_helpers.smart_caption_line(display, suggested)
    meta = money_send_helpers.build_payment_metadata(
        mode="saved_recipient",
        uploaded_file_id=None,
        user_message_id=user_msg.id,
        bank_name=bank,
        account_number=row.account_number,
        ai_account_name=row.account_name or row.display_name,
        account_lookup=lk,
        suggested_amount=suggested,
        smart_caption=smart,
    )
    last4 = row.account_number[-4:] if len(row.account_number) >= 4 else row.account_number
    amt_disp = _format_naira_display(suggested)
    content = f"Tap **Authorize payment** below to send {amt_disp} to {display} ({bank}, …{last4})."
    return content, meta


def _try_assistant_for_transfer_turn(
    db: Session,
    session: ChatSession,
    user: User,
    user_msg: Message,
    text: str,
    *,
    existing_assistant_message_id: int | None = None,
) -> tuple[Message | None, str | None]:
    """
    If this turn should end with the payment card (saved recipient) or an ambiguity reply, build it here.

    When ``existing_assistant_message_id`` is set (voice placeholder), update that row instead of appending.
    """
    ts = text.strip()
    intent_now = intent_parser_service.parse_transfer_intent(ts)

    def _emit(content: str, meta: dict[str, Any] | None) -> Message:
        if existing_assistant_message_id is not None:
            _touch_session(db, session)
            _set_assistant_reply_full(
                db,
                existing_assistant_message_id,
                content=content,
                payment_metadata=meta,
            )
            out = db.get(Message, existing_assistant_message_id)
            if not out:
                raise RuntimeError("assistant message missing after transfer short-circuit")
            return out
        return append_assistant(db, session, content, payment_metadata=meta)

    if intent_parser_service.looks_like_transfer_confirmation(ts) and (
        intent_parser_service.is_bare_transfer_acknowledgement(ts)
        or not (intent_now.is_transfer and intent_now.recipient_query)
    ):
        prior = _latest_user_transfer_intent(db, session.id, before_message_id=user_msg.id)
        if prior and prior.recipient_query:
            amb, row, _sfx = recipient_service.resolve_for_transfer_send(
                db, user.id, prior.recipient_query,
            )
            if not amb and row:
                c, m = _payment_card_payload(user_msg, row, prior.amount_naira)
                return _emit(c, m), None

    if intent_now.is_transfer and intent_now.recipient_query:
        amb, row, sfx = recipient_service.resolve_for_transfer_send(db, user.id, intent_now.recipient_query)
        if amb:
            return _emit(amb, None), None
        if row:
            c, m = _payment_card_payload(user_msg, row, intent_now.amount_naira)
            return _emit(c, m), None
        return None, sfx

    return None, None


def _assistant_text_for_market(
    db: Session,
    user: User | None,
    text: str,
    *,
    source: str,
    session_id: int | None = None,
    before_message_id: int | None = None,
) -> str:
    route = message_classifier_service.classify_text(text.strip())
    if route == "payment":
        return market_pipeline_service.payment_help_reply()
    return market_pipeline_service.handle_message(
        db,
        user,
        text.strip(),
        source=source,
        session_id=session_id,
        before_message_id=before_message_id,
    )


def _assistant_text_for_shopping_image(
    db: Session,
    user: User | None,
    raw: bytes,
    mime_base: str,
    *,
    caption: str | None,
    source: str = "image",
    session_id: int | None = None,
    before_message_id: int | None = None,
) -> str:
    intent = image_intent_service.classify_image_intent((raw, mime_base), caption=caption)
    if intent == "payment":
        return (
            "That looks like a payment screenshot, but I couldn't read the bank details. "
            "Try a clearer photo or use send-money in the app."
        )
    product = product_identification_service.identify_product((raw, mime_base), caption=caption)
    if not product:
        return (
            "I couldn't tell which product this is. "
            'Add a caption like "yam price in wuse" or send a clearer photo.'
        )
    return market_pipeline_service.handle_identified_product(
        db,
        user,
        product,
        caption=caption,
        source=source,
        session_id=session_id,
        before_message_id=before_message_id,
    )


def append_assistant(
    db: Session,
    session: ChatSession,
    content: str,
    *,
    payment_metadata: dict[str, Any] | None = None,
) -> Message:
    msg = Message(
        session_id=session.id,
        role="assistant",
        msg_type="text",
        content=content,
        payment_metadata=payment_metadata,
    )
    db.add(msg)
    _touch_session(db, session)
    db.commit()
    db.refresh(msg)
    return msg


def _set_assistant_reply_full(
    db: Session,
    message_id: int,
    *,
    content: str,
    payment_metadata: dict[str, Any] | None = None,
) -> None:
    m = db.get(Message, message_id)
    if not m:
        return
    m.content = content
    m.payment_metadata = payment_metadata
    db.add(m)
    db.commit()


def _set_message_content(db: Session, message_id: int, content: str | None) -> None:
    m = db.get(Message, message_id)
    if not m:
        return
    m.content = content
    db.add(m)
    db.commit()


def _set_voice_transcript(db: Session, message_id: int, transcript: str | None) -> None:
    m = db.get(Message, message_id)
    if not m:
        return
    m.transcript = transcript
    db.add(m)
    db.commit()


def _run_voice_job(
    *,
    session_id: int,
    user_message_id: int,
    assistant_message_id: int,
    file_id: int,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Background: transcribe, then generate assistant reply, then update rows."""
    db = SessionLocal()
    try:
        user_msg = db.get(Message, user_message_id)
        if not user_msg:
            return
        uf = db.get(UploadedFile, file_id)
        if not uf:
            _set_message_content(db, assistant_message_id, "Voice file missing. Please try again.")
            return
        try:
            raw, _mb = _download_uploaded_media(uf)
        except (FileNotFoundError, storage_service.StorageOperationError):
            _set_message_content(
                db,
                assistant_message_id,
                "That upload is no longer available. Please record again.",
            )
            return
        try:
            transcript = transcription_service.transcribe_audio_bytes(
                raw,
                mime=uf.mime_type,
                path_for_extension=Path(uf.storage_path),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Voice transcription failed in background")
            _set_message_content(
                db,
                assistant_message_id,
                "Could not transcribe that voice note. Try again or send a text message.",
            )
            return

        _set_voice_transcript(db, user_message_id, transcript)

        sess = db.get(ChatSession, user_msg.session_id)
        user_id = sess.user_id if sess else None
        user_obj = db.get(User, user_id) if user_id else None
        if user_obj and sess:
            early, _sfx = _try_assistant_for_transfer_turn(
                db,
                sess,
                user_obj,
                user_msg,
                transcript,
                existing_assistant_message_id=assistant_message_id,
            )
            if early:
                return

        if not market_pipeline_service.is_configured():
            _set_message_content(
                db,
                assistant_message_id,
                "Transcription is ready, but market pricing is not available on this server yet.",
            )
            return

        reply = _assistant_text_for_market(
            db,
            user_obj,
            transcript,
            source="voice",
            session_id=session_id,
            before_message_id=user_message_id,
        ) if user_obj else (
            market_pipeline_service.handle_message(
                db,
                None,
                transcript,
                source="voice",
                session_id=session_id,
                before_message_id=user_message_id,
            )
        )
        _set_message_content(db, assistant_message_id, reply)
    finally:
        db.close()


def _run_image_job(
    *,
    session_id: int,
    assistant_message_id: int,
    user_message_id: int,
    file_id: int,
    caption: str | None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Background: vision reply, or Money Sending Mode if the image looks like a payment context."""
    db = SessionLocal()
    try:
        uf = db.get(UploadedFile, file_id)
        if not uf:
            _set_message_content(db, assistant_message_id, "Image file missing. Please try again.")
            return
        try:
            raw, mb = _download_uploaded_media(uf)
        except (FileNotFoundError, storage_service.StorageOperationError):
            _set_message_content(
                db,
                assistant_message_id,
                "That upload is no longer available. Please upload the image again.",
            )
            return

        sess = db.get(ChatSession, session_id)
        user_obj = db.get(User, sess.user_id) if sess else None

        extracted: dict[str, Any] | None = None
        if openrouter_service.is_configured():
            try:
                extracted = payment_extraction_service.extract_payment_from_image((raw, mb))
            except Exception as exc:  # noqa: BLE001
                logger.info("Money-send probe skipped: %s", exc)

        if extracted and money_send_helpers.payment_intent_from_extraction(extracted):
            # lk = account_lookup_service.resolve_nigerian_bank_account(
            #     bank_name=extracted.get("bank_name"),
            #     account_number=extracted.get("account_number"),
            # )
            lk = account_lookup_service.lookup_stub_response(account_number=extracted.get("account_number"))
            suggested = money_send_helpers.suggested_amount_from_caption(caption)
            verified_name = lk.get("verified_account_name") if lk.get("success") else None
            _raw_ai = extracted.get("account_name")
            ai_name = (str(_raw_ai).strip() if _raw_ai is not None else None) or None
            display = (
                verified_name
                if verified_name
                else (ai_name or extracted.get("bank_name") or "Recipient")
            )
            smart = money_send_helpers.smart_caption_line(str(display), suggested)
            meta = money_send_helpers.build_payment_metadata(
                mode="product_image",
                uploaded_file_id=file_id,
                user_message_id=user_message_id,
                bank_name=extracted.get("bank_name"),
                account_number=extracted.get("account_number"),
                ai_account_name=ai_name,
                account_lookup=lk,
                suggested_amount=suggested,
                smart_caption=smart,
            )
            meta["assistant_message_id"] = assistant_message_id
            um = db.get(Message, user_message_id)
            if um:
                sess = db.get(ChatSession, um.session_id)
                if sess:
                    # Persist recipient for future fuzzy match; bank-verified name preferred.
                    # Isolated savepoint — failure does not abort the vision/payment reply transaction.
                    recipient_service.upsert_payment_recipient_safe(
                        db,
                        sess.user_id,
                        bank_verified_account_name=verified_name,
                        display_account_name=ai_name,
                        account_number=extracted.get("account_number"),
                        bank_name=extracted.get("bank_name"),
                        extra_alias=(caption or "").strip()[:120] or None,
                    )
            _set_assistant_reply_full(
                db,
                assistant_message_id,
                content=smart,
                payment_metadata=meta,
            )
            return

        if not market_pipeline_service.is_configured():
            _set_message_content(
                db,
                assistant_message_id,
                "I got your image, but market pricing is not available on this server yet.",
            )
            return

        reply = _assistant_text_for_shopping_image(
            db,
            user_obj,
            raw,
            mb,
            caption=caption,
            source="image",
            session_id=session_id,
            before_message_id=user_message_id,
        )
        _set_assistant_reply_full(db, assistant_message_id, content=reply, payment_metadata=None)
    finally:
        db.close()


def handle_voice_turn_deferred(
    db: Session,
    user: User,
    session_id: int,
    *,
    file_id: int,
    enqueue,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[Message, Message]:
    """Return immediately, do transcription/AI in background."""
    session = get_owned_session(db, user, session_id)
    uf = get_owned_file(db, user, file_id)
    if _legacy_upload_unavailable(uf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That file is no longer available. Please upload again.",
        )

    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="voice",
        content=None,
        transcript=None,
        file_id=uf.id,
    )
    db.add(user_msg)
    db.flush()

    assistant = Message(
        session_id=session.id,
        role="assistant",
        msg_type="text",
        content=_ASSISTANT_PLACEHOLDER,
    )
    db.add(assistant)
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant)

    enqueue(
        _run_voice_job,
        session_id=session.id,
        user_message_id=user_msg.id,
        assistant_message_id=assistant.id,
        file_id=uf.id,
        latitude=latitude,
        longitude=longitude,
    )
    return user_msg, assistant


def handle_image_turn_deferred(
    db: Session,
    user: User,
    session_id: int,
    *,
    file_id: int,
    caption: str | None,
    enqueue,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[Message, Message]:
    """Return immediately, do vision completion in background."""
    session = get_owned_session(db, user, session_id)
    uf = get_owned_file(db, user, file_id)
    if _legacy_upload_unavailable(uf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That file is no longer available. Please upload again.",
        )

    cap = (caption or "").strip() or None
    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="image",
        content=cap,
        file_id=uf.id,
    )
    db.add(user_msg)
    db.flush()

    assistant = Message(
        session_id=session.id,
        role="assistant",
        msg_type="text",
        content=_ASSISTANT_PLACEHOLDER,
    )
    db.add(assistant)
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant)

    enqueue(
        _run_image_job,
        session_id=session.id,
        assistant_message_id=assistant.id,
        user_message_id=user_msg.id,
        file_id=uf.id,
        caption=cap,
        latitude=latitude,
        longitude=longitude,
    )
    return user_msg, assistant


def handle_text_turn(
    db: Session,
    user: User,
    session_id: int,
    text: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[Message, Message]:
    if not market_pipeline_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market pricing is not available on this server right now.",
        )
    session = get_owned_session(db, user, session_id)
    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="text",
        content=text.strip(),
    )
    db.add(user_msg)
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)

    early, _llm_suffix = _try_assistant_for_transfer_turn(
        db, session, user, user_msg, text.strip(), existing_assistant_message_id=None,
    )
    if early:
        return user_msg, early

    reply = _assistant_text_for_market(
        db,
        user,
        text.strip(),
        source="web",
        session_id=session.id,
        before_message_id=user_msg.id,
    )
    assistant = append_assistant(db, session, reply)
    return user_msg, assistant


def handle_image_turn(
    db: Session,
    user: User,
    session_id: int,
    *,
    file_id: int,
    caption: str | None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[Message, Message]:
    session = get_owned_session(db, user, session_id)
    uf = get_owned_file(db, user, file_id)
    if _legacy_upload_unavailable(uf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That file is no longer available. Please upload again.",
        )

    cap = (caption or "").strip() or None
    try:
        raw, mb = _download_uploaded_media(uf)
    except (FileNotFoundError, storage_service.StorageOperationError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That upload is no longer available. Please try again.",
        ) from None

    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="image",
        content=cap,
        file_id=uf.id,
    )
    db.add(user_msg)
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)

    if openrouter_service.is_configured():
        try:
            extracted = payment_extraction_service.extract_payment_from_image((raw, mb))
        except Exception:  # noqa: BLE001
            extracted = None
        else:
            if extracted and money_send_helpers.payment_intent_from_extraction(extracted):
                lk = account_lookup_service.lookup_stub_response(
                    account_number=extracted.get("account_number"),
                )
                suggested = money_send_helpers.suggested_amount_from_caption(cap)
                verified_name = lk.get("verified_account_name") if lk.get("success") else None
                ai_name = (str(extracted.get("account_name") or "").strip() or None)
                display = verified_name or ai_name or extracted.get("bank_name") or "Recipient"
                smart = money_send_helpers.smart_caption_line(str(display), suggested)
                meta = money_send_helpers.build_payment_metadata(
                    mode="product_image",
                    uploaded_file_id=uf.id,
                    user_message_id=user_msg.id,
                    bank_name=extracted.get("bank_name"),
                    account_number=extracted.get("account_number"),
                    ai_account_name=ai_name,
                    account_lookup=lk,
                    suggested_amount=suggested,
                    smart_caption=smart,
                )
                recipient_service.upsert_payment_recipient_safe(
                    db,
                    user.id,
                    bank_verified_account_name=verified_name,
                    display_account_name=ai_name,
                    account_number=extracted.get("account_number"),
                    bank_name=extracted.get("bank_name"),
                    extra_alias=(cap or "")[:120] or None,
                )
                assistant = append_assistant(db, session, smart, payment_metadata=meta)
                return user_msg, assistant

    if not market_pipeline_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market pricing is not available on this server right now.",
        )

    reply = _assistant_text_for_shopping_image(
        db,
        user,
        raw,
        mb,
        caption=cap,
        source="image",
        session_id=session.id,
        before_message_id=user_msg.id,
    )
    assistant = append_assistant(db, session, reply)
    return user_msg, assistant


def handle_voice_turn(db: Session, user: User, session_id: int, *, file_id: int) -> tuple[Message, Message]:
    session = get_owned_session(db, user, session_id)
    uf = get_owned_file(db, user, file_id)
    if _legacy_upload_unavailable(uf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That file is no longer available. Please upload again.",
        )

    try:
        raw, _mb = _download_uploaded_media(uf)
        transcript = transcription_service.transcribe_audio_bytes(
            raw,
            mime=uf.mime_type,
            path_for_extension=Path(uf.storage_path),
        )
    except (FileNotFoundError, storage_service.StorageOperationError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That upload is no longer available. Please try again.",
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That audio file could not be processed. Try a shorter clip.",
        ) from None
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is temporarily unavailable. Try again shortly.",
        ) from None
    except BadRequestError:
        logger.exception("Transcription API rejected the audio file")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="We could not transcribe that voice note. Try recording again.",
        ) from None
    except APIError:
        logger.exception("Transcription API error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice transcription hit a snag. Please try again.",
        ) from None
    except Exception:  # noqa: BLE001
        logger.exception("Transcription failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice transcription failed. Please try again.",
        ) from None

    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="voice",
        content=None,
        transcript=transcript,
        file_id=uf.id,
    )
    db.add(user_msg)
    _touch_session(db, session)
    db.commit()
    db.refresh(user_msg)

    early, _llm_suffix = _try_assistant_for_transfer_turn(
        db, session, user, user_msg, transcript, existing_assistant_message_id=None,
    )
    if early:
        return user_msg, early

    if not market_pipeline_service.is_configured():
        assistant = append_assistant(
            db,
            session,
            "Transcription is ready, but market pricing is not available on this server yet.",
        )
        return user_msg, assistant

    reply = _assistant_text_for_market(
        db,
        user,
        transcript,
        source="voice",
        session_id=session.id,
        before_message_id=user_msg.id,
    )
    assistant = append_assistant(db, session, reply)
    return user_msg, assistant


def handle_payment_turn(
    db: Session,
    user: User,
    session_id: int,
    *,
    file_id: int,
    accompanying_text: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[Message, Message]:
    session = get_owned_session(db, user, session_id)
    uf = get_owned_file(db, user, file_id)
    if _legacy_upload_unavailable(uf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That file is no longer available. Please upload again.",
        )

    if not openrouter_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment screenshot reading is not available on this server right now.",
        )

    hint = (accompanying_text or "").strip() or None
    try:
        raw, mb = _download_uploaded_media(uf)
        bundle = payment_service.extract_and_resolve((raw, mb), user_hint=hint)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That upload is no longer available. Please try again.",
        ) from None
    except storage_service.StorageOperationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That upload is no longer available. Please try again.",
        ) from None
    except Exception:  # noqa: BLE001
        logger.exception("Payment extraction failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read that payment screenshot. Try a clearer photo.",
        ) from None

    fields = bundle["fields"]
    lk = bundle["account_lookup"]
    verified = bundle["verified_name"]
    stored_account_name = bundle["stored_account_name"]
    parsed_out = bundle["parsed_out"]
    bank = bundle["bank"]
    acct = bundle["account_number"]
    ai_name = bundle["ai_name"]

    suggested = money_send_helpers.suggested_amount_from_caption(hint)

    ocr_payload = {
        "bank_name": bank,
        "account_number": acct,
        "account_name": stored_account_name,
        "parsed_json": parsed_out,
        "extraction_error": fields.get("extraction_error"),
        "source": "openrouter",
        "model": openrouter_service.payment_vision_model(),
        "user_message": hint,
    }
    if verified and stored_account_name:
        ocr_payload["bank_verified_account_name"] = verified

    user_line = hint or "Payment screenshot"
    user_msg = Message(
        session_id=session.id,
        role="user",
        msg_type="payment_image",
        content=user_line,
        file_id=uf.id,
        ocr_payload=ocr_payload,
    )
    db.add(user_msg)

    try:
        db.flush()

        if user_msg.file_id is None or user_msg.file_id != uf.id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payment message is missing a valid file attachment.",
            )
        if db.get(UploadedFile, user_msg.file_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded file record missing")

        extraction = PaymentExtraction(
            message_id=user_msg.id,
            uploaded_file_id=user_msg.file_id,
            bank_name=bank or None,
            account_number=acct or None,
            account_name=stored_account_name,
            raw_text=hint,
            raw_ai_response=fields.get("raw_ai_response"),
            parsed_json=parsed_out,
        )
        db.add(extraction)

        display = stored_account_name or bank or "Recipient"
        base_smart = money_send_helpers.smart_caption_line(str(display), suggested)
        if hint and openrouter_service.is_configured():
            llm = ai_service.payment_followup_reply(
                user_text=hint,
                bank=bank,
                account_number=acct,
                display_name=stored_account_name,
                verified_name=verified,
                suggested_amount=suggested,
            )
            smart = (llm or "").strip() or base_smart
        else:
            smart = base_smart
            if verified:
                smart = (
                    f"{base_smart}\n\n"
                    f"Bank-verified account name: {verified}. Please confirm before you send."
                )

        meta = money_send_helpers.build_payment_metadata(
            mode="payment_screenshot",
            uploaded_file_id=user_msg.file_id,
            user_message_id=user_msg.id,
            bank_name=bank,
            account_number=acct,
            ai_account_name=ai_name,
            account_lookup=lk,
            suggested_amount=suggested,
            smart_caption=base_smart,
        )
        meta["ocr_summary"] = {
            "bank_name": bank,
            "account_number": acct,
            "account_name": stored_account_name,
            "bank_verified_account_name": verified,
            "user_message": hint,
        }

        assistant = Message(
            session_id=session.id,
            role="assistant",
            msg_type="text",
            content=smart,
            payment_metadata=None,
        )
        db.add(assistant)
        db.flush()
        meta["assistant_message_id"] = assistant.id
        assistant.payment_metadata = meta
        # Upsert saved_recipients: new row with bank-verified name when available, else OCR name;
        # existing row gets usage_frequency + last_used. Savepoint contains failures.
        recipient_service.upsert_payment_recipient_safe(
            db,
            user.id,
            bank_verified_account_name=verified,
            display_account_name=stored_account_name,
            account_number=acct,
            bank_name=bank,
            extra_alias=hint.strip()[:120] if hint else None,
        )
        _touch_session(db, session)
        db.commit()
        db.refresh(user_msg)
        db.refresh(assistant)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Payment turn database commit failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save this payment. Please try again.",
        ) from None

    return user_msg, assistant
