"""Central backend defaults and environment validation."""

from __future__ import annotations

import logging
import os
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Supabase Storage bucket id (must match the bucket name in the Supabase dashboard).
_env_bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or "").strip()
SUPABASE_STORAGE_BUCKET_ID: str = _env_bucket or "confam-uploads"

_DB_INVALID_MSG = "DATABASE_URL is invalid or host is unreachable."


def _is_supabase_postgres_host(hostname: str) -> bool:
    h = (hostname or "").lower()
    return "supabase.co" in h or "pooler.supabase.com" in h


def _ensure_sslmode_require(url: str) -> str:
    """Append sslmode=require for Supabase Postgres hosts when not already set (required by Supabase)."""
    parts = urlsplit(url)
    if not _is_supabase_postgres_host(parts.hostname or ""):
        return url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if any(k.lower() == "sslmode" for k in query):
        return url
    query["sslmode"] = "require"
    new_query = urlencode(list(query.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _redacted_database_url(url: str) -> str:
    """Same connection target as ``url`` but with password replaced by ``***``."""
    parts = urlsplit(url)
    host = parts.hostname or "(no-host)"
    port = f":{parts.port}" if parts.port else ""
    user = parts.username or ""
    if parts.password is not None:
        user_display = f"{user}:***" if user else "***"
    else:
        user_display = user or ""
    if user_display:
        netloc = f"{user_display}@{host}{port}"
    else:
        netloc = f"{host}{port}"
    path = parts.path or ""
    q = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{netloc}{path}{q}"


def _validate_database_url_format(url: str) -> None:
    raw = (url or "").strip()
    if not raw:
        print(_DB_INVALID_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1)
    lowered = raw.lower()
    if not (lowered.startswith("postgresql://") or lowered.startswith("postgres://")):
        print(_DB_INVALID_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1)
    parts = urlsplit(raw)
    if not parts.hostname or not str(parts.hostname).strip():
        print(_DB_INVALID_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1)


def log_database_target() -> None:
    """Log which database host the app will use (password redacted)."""
    if not DATABASE_URL:
        logger.warning("DATABASE_URL is not set.")
        return
    parts = urlsplit(DATABASE_URL)
    host = parts.hostname or "(unknown)"
    logger.info("Database host: %s | redacted URL: %s", host, _redacted_database_url(DATABASE_URL))


_raw_db = (os.getenv("DATABASE_URL") or "").strip()
if not _raw_db:
    print(_DB_INVALID_MSG, file=sys.stderr, flush=True)
    raise SystemExit(1)
_validate_database_url_format(_raw_db)
DATABASE_URL: str = _ensure_sslmode_require(_raw_db)

# WhatsApp Cloud API (WABA subscription + Graph). Falls back to legacy META_* names in .env.
_graph_ver = (os.getenv("WHATSAPP_GRAPH_API_VERSION") or os.getenv("META_GRAPH_API_VERSION") or "v25.0").strip()
if _graph_ver.lower().startswith("v"):
    WHATSAPP_GRAPH_API_VERSION: str = _graph_ver
else:
    WHATSAPP_GRAPH_API_VERSION = f"v{_graph_ver}"

WHATSAPP_BUSINESS_ID: str = (
    (os.getenv("WHATSAPP_BUSINESS_ID") or os.getenv("META_BUSINESS_ACCOUNT_ID") or "").strip()
)
WHATSAPP_ACCESS_TOKEN: str = (
    (os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN") or "").strip()
)
WHATSAPP_PHONE_NUMBER_ID: str = (
    (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("META_PHONE_NUMBER_ID") or "").strip()
)

# Market Price ML layer (NEUROPAY-GTCO ``POST /parse``). Run on a port other than Confam (default 8001).
ML_API_URL: str = (os.getenv("ML_API_URL") or "http://127.0.0.1:8001").strip().rstrip("/")
ML_CONFIDENCE_MIN: float = float(os.getenv("ML_CONFIDENCE_MIN") or "0.65")
