"""Supabase Storage: upload, signed URLs, download, delete (no local filesystem)."""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from config import SUPABASE_STORAGE_BUCKET_ID

logger = logging.getLogger(__name__)

FileKind = Literal["chat_image", "payment_image", "voice_note", "avatar"]

_PREFIX: dict[FileKind, str] = {
    "chat_image": "chat-images",
    "payment_image": "payment-images",
    "voice_note": "voice-notes",
    "avatar": "avatars",
}

_SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
_BUCKET = SUPABASE_STORAGE_BUCKET_ID
_SIGN_TTL = int(os.getenv("SUPABASE_SIGNED_URL_TTL_SECONDS", "3600"))

# When true (default), chat/media URLs use signed URLs so private buckets work in <img> / <audio>.
# Set to 0/false/no to prefer persisted get_public_url (bucket must allow public reads).
_FORCE_SIGNED_URLS = os.getenv("SUPABASE_FORCE_SIGNED_URLS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


class StorageNotConfiguredError(RuntimeError):
    """Raised when Supabase URL or service role key is missing."""


class StorageOperationError(RuntimeError):
    """Raised for upload/download failures; ``code`` maps to HTTP semantics in routers."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "unknown",
        log: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.log = log or message


_client = None


def invalidate_storage_client() -> None:
    """Close the shared httpx client (if any) and drop the Supabase client so the next call rebuilds connections."""
    global _client
    if _client is None:
        return
    hc = getattr(_client.options, "httpx_client", None)
    if hc is not None:
        try:
            hc.close()
        except Exception:  # noqa: BLE001
            logger.debug("httpx client close failed", exc_info=True)
    _client = None


def is_configured() -> bool:
    """True when URL + service role key are set (bucket id always has a default from config)."""
    return bool(_SUPABASE_URL and _SERVICE_KEY)


def default_bucket() -> str:
    return _BUCKET


def _get_client():
    global _client
    if not is_configured():
        raise StorageNotConfiguredError(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (bucket defaults to confam-uploads).",
        )
    if _client is None:
        import httpx
        from supabase import ClientOptions, create_client
        from supabase_auth import SyncMemoryStorage

        try:
            import certifi

            verify: str | bool = certifi.where()
        except ImportError:
            verify = True

        # HTTP/2 off + certifi: avoids flaky TLS / MAC errors on lossy paths; shared across Storage/PostgREST/Auth.
        http_client = httpx.Client(
            http2=False,
            verify=verify,
            timeout=httpx.Timeout(120.0, connect=30.0),
        )
        _client = create_client(
            _SUPABASE_URL,
            _SERVICE_KEY,
            ClientOptions(storage=SyncMemoryStorage(), httpx_client=http_client),
        )
    return _client


def _raw_storage_error(exc: BaseException) -> str:
    parts = [str(exc), repr(exc)]
    cur: BaseException | None = exc
    for _ in range(6):
        if cur is None:
            break
        msg = getattr(cur, "message", None)
        if isinstance(msg, str) and msg.strip():
            parts.append(msg.strip())
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return " | ".join(p for p in parts if p)


def _classify_storage_exception(exc: BaseException) -> tuple[str, str, str]:
    """
    Map Supabase/storage client errors to (code, safe_user_message, log_line).

    ``safe_user_message`` is intentionally generic (no raw provider text to clients).
    """
    try:
        from storage3.exceptions import StorageApiError
    except ImportError:
        StorageApiError = ()  # type: ignore[misc, assignment]

    if isinstance(exc, StorageApiError):  # type: ignore[arg-type]
        status = exc.status
        log = f"StorageApiError status={status} code={exc.code!r} message={exc.message!r}"
        try:
            st = int(status)
        except (TypeError, ValueError):
            st = 0
        if st == 404:
            return (
                "bucket_not_found",
                "Storage bucket not found. Confirm SUPABASE_STORAGE_BUCKET matches your Supabase bucket id.",
                log,
            )
        if st in (401, 403):
            return (
                "permission_denied",
                "Storage permission denied. Confirm SUPABASE_SERVICE_ROLE_KEY is the service role secret.",
                log,
            )
        if st == 413:
            return ("payload_too_large", "File too large for storage.", log)
        raw = (exc.message or "").lower()
        if re.search(r"not\s*found|does\s*not\s*exist|no\s*bucket|bucket\s*not\s*found", raw):
            return (
                "bucket_not_found",
                "Storage bucket not found. Confirm SUPABASE_STORAGE_BUCKET matches your Supabase bucket id.",
                log,
            )
        return ("unknown", "Upload failed. Please try again.", log)

    raw = _raw_storage_error(exc).lower()
    log = _raw_storage_error(exc)

    if re.search(r"\b404\b|not\s*found|does\s*not\s*exist|no\s*bucket|bucket\s*not\s*found", raw):
        return (
            "bucket_not_found",
            "Storage bucket not found. Confirm SUPABASE_STORAGE_BUCKET matches your Supabase bucket id.",
            log,
        )
    if re.search(
        r"\b401\b|\b403\b|unauthorized|forbidden|permission|jwt|invalid.*key|row level security|rls",
        raw,
    ):
        return (
            "permission_denied",
            "Storage permission denied. Confirm SUPABASE_SERVICE_ROLE_KEY is the service role secret.",
            log,
        )
    if "payload too large" in raw or "413" in raw or "entity too large" in raw:
        return ("payload_too_large", "File too large for storage.", log)
    return ("unknown", "Upload failed. Please try again.", log)


def _safe_ext(original_name: str | None, mime_base: str, kind: FileKind) -> str:
    ext = Path(original_name or "").suffix.lower()
    if kind in ("chat_image", "payment_image", "avatar"):
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            if "png" in mime_base:
                ext = ".png"
            elif "webp" in mime_base:
                ext = ".webp"
            else:
                ext = ".jpg"
        return ext
    if ext not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".bin", ".mp4"}:
        if "wav" in mime_base:
            ext = ".wav"
        elif "mpeg" in mime_base or ext == ".mp3":
            ext = ".mp3"
        elif "mp4" in mime_base or "m4a" in mime_base:
            ext = ".m4a"
        else:
            ext = ".webm"
    return ext


def build_object_path(
    *,
    user_id: int,
    kind: FileKind,
    ext: str,
) -> str:
    folder = _PREFIX[kind]
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex
    return f"{folder}/{user_id}_{ts}_{uid}{ext}"


def _voice_note_content_type(ext: str, header_mime: str) -> str:
    """Strict content-type for voice uploads (storage3 is sensitive to MIME for some buffers)."""
    e = ext.lower()
    if e == ".m4a":
        return "audio/x-m4a"
    if e == ".webm":
        return "audio/webm"
    if e == ".wav":
        return "audio/wav"
    if e == ".mp3":
        return "audio/mpeg"
    if e == ".ogg":
        return "audio/ogg"
    hb = (header_mime or "").split(";")[0].strip().lower()
    if hb.startswith("audio/"):
        return hb
    return "application/octet-stream"


def _upload_content_type_and_bytes(
    *,
    kind: FileKind,
    data: bytes,
    content_type: str,
    original_name: str | None,
    ext: str,
) -> tuple[bytes, str]:
    """Return raw body bytes and the ``Content-Type`` for the Storage API (storage3 expects ``bytes``, not ``BytesIO``)."""
    mime_base = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if kind == "voice_note":
        ct = _voice_note_content_type(ext, mime_base)
    else:
        ct = mime_base or "application/octet-stream"

    return data, ct


def _supabase_storage_upload(
    *,
    kind: str,
    bucket: str,
    path: str,
    file_content: bytes,
    file_options: dict[str, str],
) -> None:
    """Call Storage ``upload`` with raw ``bytes`` (storage3 0.9.x mishandled ``BytesIO`` and HTTP errors)."""
    try:
        client = _get_client()
        client.storage.from_(bucket).upload(
            path,
            file=file_content,
            file_options=file_options,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to upload %s: %s", kind, exc, exc_info=True)
        code, user_msg, log = _classify_storage_exception(exc)
        raise StorageOperationError(user_msg, code=code, log=log) from exc


def _public_url_for_object(bucket: str, path: str) -> str | None:
    """Supabase public object URL (works in chat only if the bucket/object allows public read)."""
    try:
        client = _get_client()
        pub = client.storage.from_(bucket).get_public_url(path)
        if isinstance(pub, str) and pub.startswith("http"):
            return pub
        if isinstance(pub, dict):
            u = pub.get("publicUrl") or pub.get("publicURL")
            if isinstance(u, str) and u.startswith("http"):
                return u
    except Exception:  # noqa: BLE001
        logger.debug("get_public_url failed for %s/%s", bucket, path, exc_info=True)
    return None


def upload_bytes(
    *,
    user_id: int,
    kind: FileKind,
    data: bytes,
    content_type: str,
    original_name: str | None,
) -> tuple[str, str, str | None]:
    """
    Upload object to the configured bucket.

    Returns ``(storage_path, bucket_name, public_url)`` where ``public_url`` is from
    ``get_public_url`` when available (persisted for public buckets or when forcing public URLs).
    """
    mime_base = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    ext = _safe_ext(original_name, mime_base, kind)
    path = build_object_path(user_id=user_id, kind=kind, ext=ext)
    bucket = _BUCKET
    try:
        file_content, upload_ct = _upload_content_type_and_bytes(
            kind=kind,
            data=data,
            content_type=content_type,
            original_name=original_name,
            ext=ext,
        )
        _supabase_storage_upload(
            kind=kind,
            bucket=bucket,
            path=path,
            file_content=file_content,
            file_options={"content-type": upload_ct, "cache-control": "3600"},
        )
    except StorageNotConfiguredError:
        raise
    except StorageOperationError:
        raise

    public_url = _public_url_for_object(bucket, path)
    return path, bucket, public_url


def download_bytes(storage_path: str, bucket_name: str | None = None) -> bytes:
    bucket = bucket_name or _BUCKET
    try:
        client = _get_client()
        data = client.storage.from_(bucket).download(storage_path)
        if data is None:
            raise StorageOperationError("empty download", code="empty", log="download returned None")
        if isinstance(data, bytes):
            return data
        return bytes(data)
    except StorageNotConfiguredError:
        raise
    except StorageOperationError:
        raise
    except Exception as exc:  # noqa: BLE001
        code, _, log = _classify_storage_exception(exc)
        logger.warning("Supabase download failed bucket=%s path=%s: %s", bucket, storage_path, log, exc_info=True)
        raise StorageOperationError("download failed", code=code, log=log) from exc


def signed_url(
    storage_path: str,
    *,
    bucket_name: str | None = None,
    expires_in: int | None = None,
) -> str:
    bucket = bucket_name or _BUCKET
    ttl = expires_in if expires_in is not None else _SIGN_TTL
    if storage_path.startswith("voice-notes/"):
        # Longer default so <audio> can stream without the URL expiring mid-session.
        voice_ttl = int(os.getenv("VOICE_SIGNED_URL_TTL_SECONDS", "86400"))
        ttl = max(ttl, voice_ttl)
    try:
        client = _get_client()
        api = client.storage.from_(bucket)
        try:
            res = api.create_signed_url(storage_path, ttl)
        except TypeError:
            res = api.create_signed_url(storage_path, expires_in=ttl)
        if isinstance(res, dict):
            url = res.get("signedURL") or res.get("signedUrl") or res.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
        raise StorageOperationError("unexpected signed URL response", code="bad_response", log=str(res))
    except StorageNotConfiguredError:
        raise
    except StorageOperationError:
        raise
    except Exception as exc:  # noqa: BLE001
        code, _, log = _classify_storage_exception(exc)
        logger.warning("Supabase signed_url failed bucket=%s path=%s: %s", bucket, storage_path, log, exc_info=True)
        raise StorageOperationError("signed url failed", code=code, log=log) from exc


def delete_object(storage_path: str, bucket_name: str | None = None) -> None:
    bucket = bucket_name or _BUCKET
    try:
        _get_client().storage.from_(bucket).remove([storage_path])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Supabase delete failed bucket=%s path=%s: %s",
            bucket,
            storage_path,
            _raw_storage_error(exc),
            exc_info=True,
        )


def object_access_url(
    storage_path: str,
    *,
    bucket_name: str | None = None,
    public_url: str | None = None,
) -> str | None:
    """
    URL for browsers.

    By default (``SUPABASE_FORCE_SIGNED_URLS`` unset or true) returns a **signed** URL so
    **private** buckets work in ``<img>`` / ``<audio>``. When ``SUPABASE_FORCE_SIGNED_URLS``
    is false/0/no, prefers a persisted ``get_public_url`` value (bucket must allow public reads).
    """
    if storage_path.startswith("legacy-local/"):
        return None
    bucket = bucket_name or _BUCKET
    if not _FORCE_SIGNED_URLS and public_url and public_url.startswith("http"):
        return public_url
    try:
        return signed_url(storage_path, bucket_name=bucket)
    except Exception:  # noqa: BLE001
        logger.debug("object_access_url signed fallback failed for %s", storage_path, exc_info=True)
        if public_url and public_url.startswith("http"):
            return public_url
        return None
