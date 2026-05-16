"""HTTP client for Squad (GTBank Squad) APIs: retries, timeouts, sanitized errors."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from services import squad_service

load_dotenv()

logger = logging.getLogger(__name__)

SQUAD_SECRET_KEY = os.getenv("SQUAD_SECRET_KEY", "").strip()

_DEFAULT_TIMEOUT = httpx.Timeout(25.0, connect=10.0)
_MAX_RETRIES = 3
_BACKOFF_SEC = 0.35


class SquadConfigurationError(RuntimeError):
    pass


def squad_secret() -> str:
    if not SQUAD_SECRET_KEY:
        raise SquadConfigurationError("Squad is not configured (SQUAD_SECRET_KEY).")
    return SQUAD_SECRET_KEY


def squad_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {squad_secret()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def user_facing_error(_status: int, payload: Any) -> str:
    """Never leak raw provider payloads to end users."""
    if isinstance(payload, dict):
        msg = payload.get("message")
        if isinstance(msg, str) and msg and len(msg) < 160:
            # Short generic Squad messages are okay; still avoid internal keys.
            if any(x in msg.lower() for x in ("unauthorized", "forbidden", "invalid key")):
                return "Payment provider authentication failed. Please try again later."
            return "We could not complete that step with the payment provider. Please try again."
    return "We could not complete that step with the payment provider. Please try again."


def squad_api_base() -> str:
    """Resolved Squad API origin (respects SQUAD_API_BASE and legacy host normalization)."""
    return squad_service.resolve_squad_api_base()


def squad_post(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """POST JSON to Squad. Returns (status, parsed_json_or_none)."""
    base = squad_api_base()
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                r = client.post(url, headers=squad_headers(), json=body)
            data: dict[str, Any] | list[Any] | None
            try:
                data = r.json() if r.content else None
            except Exception:  # noqa: BLE001
                data = None
            if r.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            if isinstance(data, dict) and r.status_code >= 400:
                logger.warning(
                    "Squad POST %s HTTP %s message=%s",
                    path,
                    r.status_code,
                    str(data.get("message") or data.get("Message") or "")[:300],
                )
            return r.status_code, data if isinstance(data, (dict, list)) else None
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning("Squad POST %s attempt %s failed: %s", path, attempt + 1, exc)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    return 0, None


def squad_get(path: str) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """GET JSON from Squad. Returns (status, parsed_json_or_none)."""
    base = squad_api_base()
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            headers = {k: v for k, v in squad_headers().items() if k.lower() != "content-type"}
            headers.setdefault("Accept", "application/json")
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                r = client.get(url, headers=headers)
            data: dict[str, Any] | list[Any] | None
            try:
                data = r.json() if r.content else None
            except Exception:  # noqa: BLE001
                data = None
            if r.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            if isinstance(data, dict) and r.status_code >= 400:
                logger.warning(
                    "Squad GET %s HTTP %s message=%s",
                    path,
                    r.status_code,
                    str(data.get("message") or data.get("Message") or "")[:300],
                )
            return r.status_code, data if isinstance(data, (dict, list)) else None
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning("Squad GET %s attempt %s failed: %s", path, attempt + 1, exc)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    return 0, None


def squad_is_configured() -> bool:
    return bool(SQUAD_SECRET_KEY)
