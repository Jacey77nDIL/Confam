"""Speech-to-text: Groq (OpenAI-compatible) or OpenAI Whisper."""

from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv(
    "GROQ_API_BASE",
    "https://api.groq.com/openai/v1",
)
GROQ_TRANSCRIPTION_MODEL = os.getenv(
    "GROQ_TRANSCRIPTION_MODEL",
    "whisper-large-v3-turbo",
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")

_VALID_AUDIO_EXT = frozenset(
    {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga", ".ogg", ".flac"},
)

# MediaRecorder can sometimes upload a near-empty blob if the user taps record quickly
# (or permissions fail). Catch this before calling the transcription API.
_MIN_AUDIO_BYTES = int(os.getenv("MIN_AUDIO_BYTES", "2048"))

# Optional Whisper hint: improves code-switching (Pidgin, names, ₦) when the API supports `prompt`.
_TRANSCRIPTION_PROMPT = os.getenv(
    "TRANSCRIPTION_PROMPT",
    "Nigerian English, Pidgin, Yoruba and Igbo words, market prices, naira, send money, transfer, bank, account number, names.",
).strip()


def _mime_base(mime: str | None) -> str:
    if not mime:
        return "application/octet-stream"
    return mime.split(";")[0].strip().lower()


def _upload_filename(path: Path, mime_base: str) -> str:
    """APIs infer format from filename extension — avoid bare UUID names without extension."""
    ext = path.suffix.lower()
    if ext in _VALID_AUDIO_EXT:
        return f"recording{ext}"
    if mime_base == "audio/webm":
        return "recording.webm"
    if mime_base in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "recording.wav"
    if mime_base == "audio/mpeg":
        return "recording.mp3"
    if mime_base in {"audio/mp4", "audio/m4a"}:
        return "recording.m4a"
    if mime_base == "audio/ogg":
        return "recording.ogg"
    return "recording.webm"


def transcribe_audio_bytes(
    raw_bytes: bytes,
    *,
    mime: str | None = None,
    path_for_extension: Path | None = None,
) -> str:
    """Transcribe in-memory audio (e.g. from Supabase Storage download)."""
    if len(raw_bytes) == 0:
        raise ValueError("Audio file is empty")
    if len(raw_bytes) < _MIN_AUDIO_BYTES:
        raise ValueError(
            "Audio is too short to transcribe. Press and hold record for at least a moment, then try again."
        )

    mime_base = _mime_base(mime)
    p = path_for_extension or Path("recording.webm")
    upload_name = _upload_filename(p, mime_base)
    upload_mime = mime_base if mime_base.startswith("audio/") else "audio/webm"

    providers: list[tuple[str, OpenAI, str]] = []
    if GROQ_API_KEY:
        providers.append(
            (
                "groq",
                OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL.rstrip("/")),
                GROQ_TRANSCRIPTION_MODEL,
            )
        )
    if OPENAI_API_KEY:
        providers.append(("openai", OpenAI(api_key=OPENAI_API_KEY), OPENAI_TRANSCRIPTION_MODEL))
    if not providers:
        raise RuntimeError(
            "No transcription API key configured. Set GROQ_API_KEY (recommended) "
            "or OPENAI_API_KEY in the backend .env — see .env.example.",
        )

    buf = BytesIO(raw_bytes)
    buf.seek(0)

    last_err: Exception | None = None
    for idx, (name, client, model) in enumerate(providers):
        try:
            # Pass a filename + in-memory bytes so the SDK does not read a closed on-disk handle.
            buf.seek(0)
            logger.debug("Transcribing via %s model=%s file=%s bytes=%s", name, model, upload_name, len(raw_bytes))
            create_kw: dict[str, str] = {}
            if _TRANSCRIPTION_PROMPT:
                create_kw["prompt"] = _TRANSCRIPTION_PROMPT[:1200]
            transcript = client.audio.transcriptions.create(
                model=model,
                file=(upload_name, buf, upload_mime),
                **create_kw,
            )
            text = getattr(transcript, "text", None) or str(transcript)
            return text.strip()
        except APIError as exc:
            # Some networks/regions block Groq/OpenAI endpoints and return 403.
            status_code = getattr(exc, "status_code", None)
            msg = getattr(exc, "message", None) or str(exc)
            if status_code == 403:
                logger.warning("Transcription provider '%s' returned 403: %s", name, msg)
                last_err = exc
                # Try the next provider if available
                if idx < len(providers) - 1:
                    continue
                raise RuntimeError(
                    "Transcription access denied (403). This is usually caused by a blocked network, "
                    "firewall/proxy, or provider regional restriction. Try a different network/VPN, "
                    "or configure OPENAI_API_KEY to fall back from GROQ."
                ) from exc
            last_err = exc
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            # Non-403 errors: don't loop indefinitely, but allow fallback if there is another provider.
            if idx < len(providers) - 1:
                logger.warning("Transcription via %s failed (%s); trying next provider", name, exc)
                continue
            break

    raise RuntimeError(f"Transcription failed: {last_err}") from last_err


def transcribe_audio_file(path: Path, *, mime: str | None = None) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Audio path is not a file: {path}")
    return transcribe_audio_bytes(path.read_bytes(), mime=mime, path_for_extension=path)
