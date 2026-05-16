"""OpenRouter chat completions with retries and multimodal support."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Union

import httpx
from dotenv import load_dotenv

from ai.prompts import CONFAM_SYSTEM_PROMPT

VisionImageInput = Union[Path, tuple[bytes, str]]

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "https://confam.app").strip() or "https://confam.app"
OPENROUTER_TITLE = os.getenv("OPENROUTER_APP_TITLE", "Confam").strip() or "Confam"
OPENROUTER_TEXT_MODEL = os.getenv(
    "OPENROUTER_TEXT_MODEL",
    # The OpenRouter free catalog changes; keep defaults aligned with /api/v1/models
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)
OPENROUTER_VISION_MODEL = os.getenv(
    "OPENROUTER_VISION_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)
# Payment / bank-slip vision extraction (overrides vision model for that flow when set).
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "").strip()


def payment_vision_model() -> str:
    return OPENROUTER_MODEL or OPENROUTER_VISION_MODEL


# If a chosen model returns OpenRouter 404 "No endpoints found for ...", fall back once.
OPENROUTER_FALLBACK_TEXT_MODEL = os.getenv(
    "OPENROUTER_FALLBACK_TEXT_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)
OPENROUTER_FALLBACK_VISION_MODEL = os.getenv(
    "OPENROUTER_FALLBACK_VISION_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)


def _completions_url() -> str:
    """Normalize OPENROUTER_API_URL so POST always hits .../chat/completions (404 if path is wrong)."""
    raw = (os.getenv("OPENROUTER_API_URL") or _DEFAULT_COMPLETIONS_URL).strip()
    if "chat/completions" in raw:
        return raw.split("?", 1)[0].rstrip("/")
    raw = raw.rstrip("/")
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return _DEFAULT_COMPLETIONS_URL


def _headers() -> dict[str, str]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    # Wire format uses standard "Referer"; OpenRouter docs also mention HTTP-Referer in JS examples.
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Referer": OPENROUTER_REFERER,
        "X-Title": OPENROUTER_TITLE,
        "X-OpenRouter-Title": OPENROUTER_TITLE,
        "Content-Type": "application/json",
    }


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    last_err: Exception | None = None
    url = _completions_url()
    for attempt in range(3):
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(url, headers=_headers(), json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text or "")[:800]
            if exc.response.status_code == 429:
                ra = exc.response.headers.get("retry-after")
                try:
                    wait_s = float(ra) if ra else 2.0
                except ValueError:
                    wait_s = 2.0
                logger.warning("OpenRouter rate-limited (429). Waiting %ss before retrying.", wait_s)
                last_err = exc
                time.sleep(max(0.5, min(wait_s, 30.0)))
                continue
            # OpenRouter uses 404 for "model has no available endpoints/providers".
            try:
                j = exc.response.json()
            except Exception:  # noqa: BLE001
                j = None
            if (
                exc.response.status_code == 404
                and isinstance(j, dict)
                and isinstance(j.get("error"), dict)
                and "no endpoints found for" in str(j["error"].get("message", "")).lower()
            ):
                requested = str(payload.get("model") or "")
                fallback = (
                    OPENROUTER_FALLBACK_VISION_MODEL
                    if any(m.get("type") == "image_url" for msg in payload.get("messages", []) for m in (msg.get("content") if isinstance(msg.get("content"), list) else []))  # type: ignore[union-attr]
                    else OPENROUTER_FALLBACK_TEXT_MODEL
                )
                if requested and fallback and requested != fallback:
                    logger.warning("OpenRouter model '%s' unavailable; falling back to '%s'", requested, fallback)
                    payload["model"] = fallback
                    last_err = exc
                    continue
            logger.warning(
                "OpenRouter HTTP %s on %s (attempt %s): %s",
                exc.response.status_code,
                url,
                attempt + 1,
                body,
            )
            last_err = exc
            time.sleep(0.6 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("OpenRouter attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"OpenRouter request failed after retries: {last_err}") from last_err


def _normalize_assistant_content(raw: Any) -> str:
    """
    OpenAI-compatible APIs usually return ``message.content`` as a string.
    Some models return a list of blocks (e.g. ``[{"type":"text","text":"..."}]``)
    or that structure as a JSON string — normalize to plain text for chat UI.
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        if raw.get("type") == "text" and isinstance(raw.get("text"), str):
            return raw["text"].strip()
        if isinstance(raw.get("text"), str):
            return raw["text"].strip()
        return str(raw).strip()
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif btype == "refusal" and isinstance(block.get("refusal"), str):
                parts.append(block["refusal"])
        return "\n\n".join(p.strip() for p in parts if p).strip()
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("[") and '"text"' in s:
            try:
                parsed = json.loads(s)
                if isinstance(parsed, (list, dict)):
                    return _normalize_assistant_content(parsed)
            except json.JSONDecodeError:
                pass
        return s
    return str(raw).strip()


def complete_text_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    system_suffix: str | None = None,
    temperature: float | None = None,
) -> str:
    """messages: OpenAI-style role/content list (user/assistant), system injected."""
    chosen = model or OPENROUTER_TEXT_MODEL
    system = CONFAM_SYSTEM_PROMPT + (system_suffix or "")
    temp = 0.45 if temperature is None else float(temperature)
    payload = {
        "model": chosen,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": temp,
    }
    data = _post(payload)
    try:
        raw = data["choices"][0]["message"]["content"]
        return _normalize_assistant_content(raw)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {data}") from exc


def _image_data_url(image_path: Path) -> tuple[str, str]:
    mime = "image/jpeg"
    suffix = image_path.suffix.lower()
    if suffix in {".png"}:
        mime = "image/png"
    elif suffix in {".webp"}:
        mime = "image/webp"
    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return mime, f"data:{mime};base64,{b64}"


def _image_data_url_from_input(image: VisionImageInput) -> tuple[str, str]:
    if isinstance(image, Path):
        return _image_data_url(image)
    raw, mime_in = image
    mime = (mime_in or "image/jpeg").split(";")[0].strip().lower()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        mime = "image/jpeg"
    b64 = base64.b64encode(raw).decode("ascii")
    return mime, f"data:{mime};base64,{b64}"


def complete_vision_custom(
    image: VisionImageInput,
    *,
    system_prompt: str,
    user_text: str,
    model: str | None = None,
    temperature: float = 0.1,
) -> str:
    """Single-image vision call with a custom system prompt (no Confam chat persona)."""
    _mime, data_url = _image_data_url_from_input(image)
    vision_messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    chosen = model or payment_vision_model()
    payload = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system_prompt},
            *vision_messages,
        ],
        "temperature": temperature,
    }
    data = _post(payload)
    try:
        raw = data["choices"][0]["message"]["content"]
        return _normalize_assistant_content(raw)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {data}") from exc


def complete_vision_chat(
    messages: list[dict[str, Any]],
    image: VisionImageInput,
    *,
    caption: str | None = None,
    model: str | None = None,
    system_suffix: str | None = None,
) -> str:
    _, data_url = _image_data_url_from_input(image)

    user_text = caption or "What is a fair Nigerian market price for this? Give negotiation tips."
    vision_messages = [
        *messages,
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    chosen = model or OPENROUTER_VISION_MODEL
    system = CONFAM_SYSTEM_PROMPT + (system_suffix or "")
    payload = {
        "model": chosen,
        "messages": [{"role": "system", "content": system}, *vision_messages],
        "temperature": 0.45,
    }
    data = _post(payload)
    try:
        raw = data["choices"][0]["message"]["content"]
        return _normalize_assistant_content(raw)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {data}") from exc


def is_configured() -> bool:
    return bool(OPENROUTER_API_KEY)
