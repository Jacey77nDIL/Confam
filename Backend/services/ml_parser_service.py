"""HTTP client for the Market Price ML layer: ``POST /parse`` and ``POST /process``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from config import ML_API_URL

logger = logging.getLogger(__name__)

_PARSE_PATH = "/parse"
_PROCESS_PATH = "/process"
_HEALTH_PATH = "/health"
_TIMEOUT = 25.0
_MAX_RETRIES = 2


class MLParserError(RuntimeError):
    """ML API unreachable or returned an invalid payload."""


@dataclass(frozen=True)
class MLParseResult:
    intent: str
    product: str | None
    unit: str | None
    location: str | None
    price: float | None
    quantity: float | None
    confidence: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MLParseResult:
        return cls(
            intent=str(data.get("intent") or "UNKNOWN").upper(),
            product=_opt_str(data.get("product")),
            unit=_opt_str(data.get("unit")),
            location=_opt_str(data.get("location")),
            price=_opt_float(data.get("price")),
            quantity=_opt_float(data.get("quantity")),
            confidence=float(data.get("confidence") or 0.0),
        )


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_configured() -> bool:
    return bool(ML_API_URL)


def health_check() -> bool:
    if not is_configured():
        return False
    url = f"{ML_API_URL.rstrip('/')}{_HEALTH_PATH}"
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(url)
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def parse_market_message(message: str) -> MLParseResult:
    """
    POST ``/parse`` with ``{"message": "..."}``.
    """
    text = (message or "").strip()
    if not text:
        raise MLParserError("empty message")
    if not is_configured():
        raise MLParserError("ML_API_URL is not configured")

    url = f"{ML_API_URL.rstrip('/')}{_PARSE_PATH}"
    payload = {"message": text}
    last_err: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(url, json=payload)
            if response.status_code >= 500:
                last_err = MLParserError(f"ML API HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                logger.warning(
                    "ML /parse HTTP %s: %s",
                    response.status_code,
                    (response.text or "")[:400],
                )
                raise MLParserError(f"ML API rejected request (HTTP {response.status_code})")
            data = response.json()
            if not isinstance(data, dict):
                raise MLParserError("ML API returned non-object JSON")
            parsed = MLParseResult.from_dict(data)
            logger.info(
                "ML /parse intent=%s product=%s location=%s",
                parsed.intent,
                parsed.product,
                parsed.location,
            )
            return parsed
        except MLParserError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("ML /parse attempt %s failed: %s", attempt + 1, exc)

    raise MLParserError(f"ML API unavailable: {last_err}") from last_err


def process_market_message(message: str, *, user_id: str) -> str:
    """
    POST ``/process`` with ``raw_text``, ``user_id``, ``timestamp``.

    Returns the ``reply`` string from the ML layer.

    Raises ``MLParserError`` when the service is down or the response is invalid.
    """
    text = (message or "").strip()
    if not text:
        raise MLParserError("empty message")
    if not is_configured():
        raise MLParserError("ML_API_URL is not configured")

    url = f"{ML_API_URL.rstrip('/')}{_PROCESS_PATH}"
    payload: dict[str, Any] = {
        "raw_text": text,
        "user_id": (user_id or "").strip() or "anonymous",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    last_err: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(url, json=payload)
            if response.status_code >= 500:
                last_err = MLParserError(f"ML API HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                logger.warning(
                    "ML /process HTTP %s: %s",
                    response.status_code,
                    (response.text or "")[:400],
                )
                raise MLParserError(f"ML API rejected request (HTTP {response.status_code})")
            data = response.json()
            if not isinstance(data, dict):
                raise MLParserError("ML API returned non-object JSON")
            reply = data.get("reply")
            if reply is None:
                raise MLParserError("ML API response missing reply")
            out = str(reply).strip()
            if not out:
                raise MLParserError("ML API returned empty reply")
            logger.info("ML /process reply_len=%s", len(out))
            return out
        except MLParserError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("ML /process attempt %s failed: %s", attempt + 1, exc)

    raise MLParserError(f"ML API unavailable: {last_err}") from last_err
