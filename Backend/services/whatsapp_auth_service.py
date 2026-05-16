"""WhatsApp sign-in: email + password before using the Confam chat pipeline."""

from __future__ import annotations

import logging
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.chat_session import ChatSession
from models.user import User
from models.whatsapp_session import WhatsappSession
from services import auth_service
from utils.security import pwd_context

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOGOUT_RE = re.compile(r"^\s*(logout|sign\s*out|log\s*out)\s*$", re.IGNORECASE)

WELCOME_MESSAGE = (
    "Welcome to Confam on WhatsApp.\n\n"
    "Before we continue, sign in with the same email and password you use in the Confam app.\n\n"
    "Step 1 of 2: Reply with your email (e.g. you@gmail.com)."
)

_ASK_PASSWORD = (
    "Step 2 of 2: Reply with your Confam password.\n\n"
    "We only use it to verify your account — it won't be repeated in this chat."
)

_SIGNED_IN = (
    "You're signed in. How can I help?\n\n"
    "Ask about market prices, send a product photo, share a payment screenshot, or send a voice note."
)

LOGIN_REQUIRED_MESSAGE = (
    "Please sign in first.\n\n"
    "Reply with the email you use in the Confam app (e.g. you@gmail.com)."
)

_BAD_EMAIL = "That doesn't look like a valid email. Example: you@gmail.com"

_BAD_CREDENTIALS = (
    "Incorrect email or password.\n\n"
    "Reply with your email again to restart sign-in."
)

_LOGGED_OUT = "You've been signed out. Reply with your Confam email to sign in again."


def is_authenticated(ws: WhatsappSession) -> bool:
    return ws.linked_user_id is not None


def is_internal_wa_user(user: User) -> bool:
    return (user.email or "").endswith("@whatsapp.confam.internal")


def handle_auth_text(
    db: Session,
    ws: WhatsappSession,
    *,
    text: str,
    phone_e164: str,
) -> str | None:
    """
    Process inbound text for login / logout.

    Returns a reply to send on WhatsApp, or ``None`` if the caller should continue
    with normal chat (user is authenticated and message is not a logout command).
    """
    body = (text or "").strip()
    if not body:
        return WELCOME_MESSAGE

    if _LOGOUT_RE.match(body):
        if is_authenticated(ws):
            _logout_session(db, ws, phone_e164)
            return _LOGGED_OUT
        ws.auth_pending_email = None
        db.add(ws)
        db.commit()
        return WELCOME_MESSAGE

    if is_authenticated(ws):
        return None

    if ws.auth_pending_email:
        return _verify_password_and_link(db, ws, password=body, phone_e164=phone_e164)

    return _capture_email(db, ws, email_raw=body)


def _capture_email(db: Session, ws: WhatsappSession, *, email_raw: str) -> str:
    email = email_raw.strip().lower()
    if not _EMAIL_RE.match(email):
        if "@" in email_raw:
            return f"{_BAD_EMAIL}\n\n{WELCOME_MESSAGE}"
        return WELCOME_MESSAGE
    if email.endswith("@whatsapp.confam.internal"):
        return f"{_BAD_EMAIL}\n\n{WELCOME_MESSAGE}"
    ws.auth_pending_email = email
    db.add(ws)
    db.commit()
    return _ASK_PASSWORD


def _verify_password_and_link(
    db: Session,
    ws: WhatsappSession,
    *,
    password: str,
    phone_e164: str,
) -> str:
    email = (ws.auth_pending_email or "").strip().lower()
    if not email:
        ws.auth_pending_email = None
        db.add(ws)
        db.commit()
        return WELCOME_MESSAGE

    user = auth_service.verify_credentials(db, email, password)
    if user is None:
        ws.auth_pending_email = None
        db.add(ws)
        db.commit()
        logger.info("WhatsApp login failed for phone=%s email=%s", phone_e164, email)
        return _BAD_CREDENTIALS

    _link_session_to_user(db, ws, user, phone_e164=phone_e164)
    logger.info("WhatsApp login ok phone=%s user_id=%s", phone_e164, user.id)
    return _SIGNED_IN


def _link_session_to_user(db: Session, ws: WhatsappSession, user: User, *, phone_e164: str) -> None:
    chat = db.get(ChatSession, ws.chat_session_id)
    if chat:
        chat.user_id = user.id
        db.add(chat)
    ws.user_id = user.id
    ws.linked_user_id = user.id
    ws.auth_pending_email = None
    if phone_e164 and not user.phone_e164:
        user.phone_e164 = phone_e164
        db.add(user)
    db.add(ws)
    db.commit()


def synthetic_wa_user(db: Session, phone_e164: str) -> User:
    """Placeholder user until WhatsApp sign-in completes."""
    digits = re.sub(r"\D", "", phone_e164)
    email = f"wa_{digits}@whatsapp.confam.internal"
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing
    u = User(
        full_name=f"WhatsApp {phone_e164}",
        email=email,
        hashed_password=pwd_context.hash(secrets.token_urlsafe(24)[:48]),
        phone_e164=None,
    )
    db.add(u)
    db.flush()
    return u


def _logout_session(db: Session, ws: WhatsappSession, phone_e164: str) -> None:
    placeholder = synthetic_wa_user(db, phone_e164)
    chat = ChatSession(user_id=placeholder.id, title="WhatsApp")
    db.add(chat)
    db.flush()
    ws.user_id = placeholder.id
    ws.chat_session_id = chat.id
    ws.linked_user_id = None
    ws.auth_pending_email = None
    db.add(ws)
    db.commit()
