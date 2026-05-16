"""
Chat / media file access via Supabase Storage.

All operations use the bucket id from ``config.SUPABASE_STORAGE_BUCKET_ID`` (defaults to
``confam-uploads`` when ``SUPABASE_STORAGE_BUCKET`` is unset).

Uploads use ``storage_service`` (voice-note MIME handling, HTTP/1.1 + certifi on the shared
httpx client). This module coerces ``BytesIO`` / binary buffers with ``seek(0)`` then a single
``read()`` into ``bytes``, logs payload size, retries transient TLS/read errors, and is the
stable import surface for routers.
"""

from __future__ import annotations

import inspect
import logging
import ssl
import time
from io import BytesIO
from typing import BinaryIO

import httpx

from config import SUPABASE_STORAGE_BUCKET_ID as STORAGE_BUCKET_ID
from services import storage_service as _storage

from services.storage_service import (
    FileKind,
    StorageNotConfiguredError,
    StorageOperationError,
    delete_object,
    download_bytes,
    is_configured,
    object_access_url,
    signed_url,
)

logger = logging.getLogger(__name__)

_UPLOAD_READ_RETRIES = 3
_UPLOAD_READ_BACKOFF_SEC = 1.0


def _iter_exception_chain(exc: BaseException | None):
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _is_transient_read_error(exc: BaseException) -> bool:
    """True for transport-layer failures that often succeed on retry (e.g. SSL MAC / read reset)."""
    for cur in _iter_exception_chain(exc):
        if isinstance(cur, (httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError)):
            return True
        if isinstance(cur, ssl.SSLError) and "BAD_RECORD_MAC" in str(cur):
            return True
    return False


def _coerce_upload_bytes(data: bytes | bytearray | BinaryIO | object) -> bytes:
    """Normalize upload payloads to ``bytes`` (storage3 must not receive ``BytesIO``)."""
    if isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
        return payload
    if isinstance(data, BytesIO):
        data.seek(0)
        payload: bytes = data.read()
        return payload
    read = getattr(data, "read", None)
    if not callable(read):
        raise TypeError(f"upload payload must be bytes or a binary buffer, got {type(data)!r}")
    if inspect.iscoroutinefunction(read):
        raise TypeError(
            "Async buffers (e.g. UploadFile) are not supported here; use `await upload.read()` "
            "and pass the resulting bytes to upload_bytes.",
        )
    seek = getattr(data, "seek", None)
    if callable(seek):
        seek(0)
    payload = read()
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, bytes):
        return payload
    raise TypeError(f"buffer read() must return bytes, got {type(payload)!r}")


def upload_bytes(
    *,
    user_id: int,
    kind: FileKind,
    data: bytes | bytearray | BinaryIO,
    content_type: str,
    original_name: str | None,
) -> tuple[str, str, str | None]:
    """Upload to bucket ``STORAGE_BUCKET_ID`` (see ``storage_service.upload_bytes``)."""
    body = _coerce_upload_bytes(data)
    logger.info(
        "Prepared storage upload payload: %s bytes (kind=%s, user_id=%s)",
        len(body),
        kind,
        user_id,
    )

    last_exc: StorageOperationError | None = None
    for attempt in range(_UPLOAD_READ_RETRIES):
        try:
            return _storage.upload_bytes(
                user_id=user_id,
                kind=kind,
                data=body,
                content_type=content_type,
                original_name=original_name,
            )
        except StorageOperationError as exc:
            last_exc = exc
            if attempt + 1 < _UPLOAD_READ_RETRIES and _is_transient_read_error(exc):
                logger.warning(
                    "Storage upload transient error (attempt %s/%s): %s; resetting client and retrying",
                    attempt + 1,
                    _UPLOAD_READ_RETRIES,
                    exc.log or str(exc),
                )
                _storage.invalidate_storage_client()
                time.sleep(_UPLOAD_READ_BACKOFF_SEC)
                continue
            raise
    assert last_exc is not None
    raise last_exc


__all__ = [
    "STORAGE_BUCKET_ID",
    "FileKind",
    "StorageNotConfiguredError",
    "StorageOperationError",
    "delete_object",
    "download_bytes",
    "is_configured",
    "object_access_url",
    "signed_url",
    "upload_bytes",
]
