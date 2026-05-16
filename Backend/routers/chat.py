from __future__ import annotations

import logging
import os
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.session import get_db
from middleware.auth import get_current_user
from models.chat_session import ChatSession
from models.message import Message
from models.uploaded_file import UploadedFile
from models.user import User
from schemas.chat import (
    ChatSessionCreate,
    ChatSessionOut,
    MessageOut,
    SendImageBody,
    SendPaymentBody,
    SendTextBody,
    SendVoiceBody,
    TurnResult,
    UploadedFileOut,
)
from services import chat_service, file_service

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024
ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_AUDIO = {
    "audio/webm",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "application/octet-stream",
}


ALLOWED_UPLOAD_KINDS = frozenset({"chat_image", "payment_image", "voice_note", "avatar"})


def _http_for_storage_error(exc: file_service.StorageOperationError) -> HTTPException:
    logger.warning("Storage operation failed: %s", exc.log)
    if exc.code == "bucket_not_found":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "Storage bucket not found.",
        )
    if exc.code == "permission_denied":
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Storage permission denied.",
        )
    if exc.code == "payload_too_large":
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large.")
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Upload failed. Please try again.",
    )


def _mime_base(mime: str | None) -> str:
    """Strip parameters (e.g. audio/webm;codecs=opus → audio/webm)."""
    if not mime:
        return "application/octet-stream"
    return mime.split(";")[0].strip().lower()


def _resolve_file_kind(mime_base: str, kind: str | None) -> file_service.FileKind:
    if kind is not None and kind.strip():
        k = kind.strip()
        if k not in ALLOWED_UPLOAD_KINDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file category.",
            )
        return cast(file_service.FileKind, k)
    if mime_base in ALLOWED_AUDIO:
        return "voice_note"
    return "chat_image"


def _file_url_for_uploaded(uf: UploadedFile) -> str | None:
    return file_service.object_access_url(
        uf.storage_path,
        bucket_name=uf.bucket_name,
        public_url=uf.public_url,
    )


def _serialize_message(db: Session, m: Message) -> MessageOut:
    file_url = None
    if m.file_id:
        uf = db.get(UploadedFile, m.file_id)
        if uf:
            file_url = _file_url_for_uploaded(uf)
    return MessageOut(
        id=m.id,
        role=m.role,
        msg_type=m.msg_type,
        content=m.content,
        transcript=m.transcript,
        ocr_payload=m.ocr_payload,
        payment_metadata=_enrich_payment_metadata(db, m.payment_metadata),
        file_id=m.file_id,
        file_url=file_url,
        created_at=m.created_at,
    )


def _enrich_payment_metadata(db: Session, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    out = dict(raw)
    fid = out.get("uploaded_file_id")
    if fid and not out.get("preview_file_url"):
        uf = db.get(UploadedFile, int(fid))
        if uf:
            out["preview_file_url"] = _file_url_for_uploaded(uf)
    return out


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatSession]:
    rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc()),
    ).all()
    return list(rows)


@router.post("/sessions", response_model=ChatSessionOut)
def create_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSession:
    s = ChatSession(user_id=current_user.id, title=payload.title)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageOut]:
    chat_service.get_owned_session(db, current_user, session_id)
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.asc()),
    ).all()
    return [_serialize_message(db, m) for m in rows]


@router.post("/sessions/{session_id}/messages/text", response_model=TurnResult)
def send_text(
    session_id: int,
    body: SendTextBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResult:
    user_msg, assistant = chat_service.handle_text_turn(
        db,
        current_user,
        session_id,
        body.text,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return TurnResult(
        user_message=_serialize_message(db, user_msg),
        assistant_message=_serialize_message(db, assistant),
    )


@router.post("/sessions/{session_id}/messages/image", response_model=TurnResult)
def send_image(
    session_id: int,
    body: SendImageBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResult:
    user_msg, assistant = chat_service.handle_image_turn_deferred(
        db,
        current_user,
        session_id,
        file_id=body.file_id,
        caption=body.caption,
        enqueue=background_tasks.add_task,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return TurnResult(
        user_message=_serialize_message(db, user_msg),
        assistant_message=_serialize_message(db, assistant),
    )


@router.post("/sessions/{session_id}/messages/voice", response_model=TurnResult)
def send_voice(
    session_id: int,
    body: SendVoiceBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResult:
    user_msg, assistant = chat_service.handle_voice_turn_deferred(
        db,
        current_user,
        session_id,
        file_id=body.file_id,
        enqueue=background_tasks.add_task,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return TurnResult(
        user_message=_serialize_message(db, user_msg),
        assistant_message=_serialize_message(db, assistant),
    )


@router.post("/sessions/{session_id}/messages/payment", response_model=TurnResult)
def send_payment_image(
    session_id: int,
    body: SendPaymentBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResult:
    user_msg, assistant = chat_service.handle_payment_turn(
        db,
        current_user,
        session_id,
        file_id=body.file_id,
        accompanying_text=body.text,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return TurnResult(
        user_message=_serialize_message(db, user_msg),
        assistant_message=_serialize_message(db, assistant),
    )


@router.post("/files", response_model=UploadedFileOut)
async def upload_file(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    kind: str | None = Query(
        None,
        description="Organize in storage: chat_image | payment_image | voice_note | avatar",
    ),
    upload: UploadFile | None = File(None, description="Preferred multipart field name"),
    file: UploadFile | None = File(None, description="Alternate field name (some clients send `file`)"),
) -> UploadedFileOut:
    part = upload if upload and upload.filename else file
    if part is None or not part.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing file: send multipart form field `upload` or `file`",
        )
    mime_raw = part.content_type or "application/octet-stream"
    mime_base = _mime_base(mime_raw)
    if mime_base in ALLOWED_IMAGE or mime_base in ALLOWED_AUDIO:
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type.",
        )

    raw = await part.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    if not file_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is not configured on this server.",
        )

    fk = _resolve_file_kind(mime_base, kind)
    try:
        path, bucket, pub = file_service.upload_bytes(
            user_id=current_user.id,
            kind=fk,
            data=raw,
            content_type=mime_raw,
            original_name=part.filename,
        )
    except file_service.StorageNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is not configured on this server.",
        ) from None
    except file_service.StorageOperationError as exc:
        raise _http_for_storage_error(exc) from None

    row = UploadedFile(
        user_id=current_user.id,
        storage_path=path,
        bucket_name=bucket,
        public_url=pub,
        file_type=fk,
        original_name=part.filename,
        mime_type=mime_raw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    access = _file_url_for_uploaded(row)
    if not access:
        try:
            access = file_service.signed_url(path, bucket_name=bucket)
        except file_service.StorageOperationError as exc:
            raise _http_for_storage_error(exc) from None

    return UploadedFileOut(
        id=row.id,
        mime_type=row.mime_type,
        original_name=row.original_name,
        file_url=access,
        file_type=row.file_type,
    )
