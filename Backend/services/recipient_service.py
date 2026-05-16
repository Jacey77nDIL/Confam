"""Saved bank recipient memory + fuzzy matching."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from models.saved_recipient import SavedRecipient

logger = logging.getLogger(__name__)


def _saved_recipients_schema_error(exc: BaseException) -> bool:
    """True when failure is likely missing ``saved_recipients`` columns (e.g. account_name)."""
    cur: BaseException | None = exc
    for _ in range(12):
        if cur is None:
            return False
        if isinstance(cur, ProgrammingError):
            return True
        if type(cur).__name__ == "UndefinedColumn":
            return True
        low = str(cur).lower()
        if "undefinedcolumn" in low:
            return True
        if "does not exist" in low and any(
            col in low for col in ("account_name", "aliases", "usage_frequency", "last_used", "bank_name")
        ):
            return True
        cur = (
            getattr(cur, "__cause__", None)
            or getattr(cur, "__context__", None)
            or getattr(cur, "orig", None)
        )
    return False


def _tokenize(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) >= 2]


def _aliases_list(row: SavedRecipient) -> list[str]:
    raw = row.aliases
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]
    return []


def _row_match_blob(row: SavedRecipient) -> str:
    """Lowercased text blob used for substring / token matching."""
    parts = [
        (row.display_name or "").lower(),
        str(getattr(row, "account_name", None) or "").lower(),
        (row.account_number or "").lower(),
        " ".join(a.lower() for a in _aliases_list(row)),
    ]
    return " ".join(p for p in parts if p)


def _substring_hits_saved_name(qlow: str, row: SavedRecipient) -> bool:
    """
    True when the user's name query matches this saved row: full phrase substring, or every
    significant token (len ≥ 3) appears somewhere in name / account_name / account / aliases.
    """
    if len(qlow) < 3:
        return False
    blob = _row_match_blob(row)
    if not blob.strip():
        return False
    if qlow in blob:
        return True
    tokens = [t for t in re.split(r"[^\w]+", qlow) if len(t) >= 3]
    if not tokens:
        return False
    return all(t in blob for t in tokens)


def _score_row(query: str, row: SavedRecipient) -> float:
    """Score saved recipient vs user text. Requires real token overlap — fuzzy ratio alone cannot win."""
    q = query.strip().lower()
    if not q:
        return 0.0
    name = (row.display_name or "").lower()
    _an = getattr(row, "account_name", None)
    account_name = (str(_an).strip().lower() if _an is not None else "")
    alias_blob = " ".join(_aliases_list(row)).lower()
    qt = _tokenize(q)
    nt = _tokenize(name + " " + account_name + " " + alias_blob)
    if not qt:
        return 0.0
    hits = 0
    for t in qt:
        for u in nt:
            if t == u or u.startswith(t) or t.startswith(u):
                hits += 1
                break
            # allow one typo on longer tokens (>= 5) only when lengths are close
            if len(t) >= 5 and len(u) >= 5 and abs(len(t) - len(u)) <= 2:
                r = SequenceMatcher(None, t, u).ratio()
                if r >= 0.88:
                    hits += 1
                    break
    overlap = hits / max(len(qt), 1)
    ratio = max(
        SequenceMatcher(None, q, name).ratio(),
        SequenceMatcher(None, q, account_name).ratio() if account_name else 0.0,
    )
    if hits == 0:
        # Without a name-token hit, do not match on vague whole-string similarity (e.g. "akachukwu" vs "Ikemdinachukwu").
        return min(0.32, 0.22 * ratio)
    return min(1.0, 0.55 * overlap + 0.45 * ratio)


def find_ranked_matches(db: Session, user_id: int, query: str, *, limit: int = 8) -> list[tuple[SavedRecipient, float]]:
    if not query.strip():
        return []
    try:
        rows = db.scalars(select(SavedRecipient).where(SavedRecipient.user_id == user_id)).all()
    except ProgrammingError as e:
        logger.warning(
            "find_ranked_matches: ProgrammingError loading saved_recipients (add account_name migration?): %s",
            e,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("find_ranked_matches rollback after ProgrammingError", exc_info=True)
        return []
    except Exception as e:  # noqa: BLE001
        if _saved_recipients_schema_error(e):
            logger.warning(
                "find_ranked_matches: saved_recipients schema error (e.g. UndefinedColumn account_name): %s",
                e,
                exc_info=True,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("find_ranked_matches rollback after schema error", exc_info=True)
            return []
        raise
    scored: list[tuple[SavedRecipient, float]] = []
    qlow = query.strip().lower()
    for r, sc in [(r, _score_row(query, r)) for r in rows]:
        scf = float(sc)
        if len(qlow) >= 3 and _substring_hits_saved_name(qlow, r):
            scf = max(scf, 0.56)
        scored.append((r, scf))
    scored.sort(key=lambda x: -x[1])
    return [pair for pair in scored if pair[1] > 0.15][:limit]


def format_ambiguous_message(candidates: list[tuple[SavedRecipient, float]]) -> str:
    lines: list[str] = []
    for r, _ in candidates[:4]:
        last4 = r.account_number[-4:] if len(r.account_number) >= 4 else r.account_number
        bank = r.bank_name or "Bank"
        lines.append(f"• {r.display_name} — {bank} • …{last4}")
    return (
        "I matched more than one saved person. Who did you mean?\n"
        + "\n".join(lines)
        + "\n\nReply with their full name or last 4 digits of the account."
    )


def _payment_card_match_row(ranked: list[tuple[SavedRecipient, float]]) -> SavedRecipient | None:
    """
    Pick a single saved recipient for the in-app payment card — looser than fuzzy-only scoring
    so short names (e.g. \"Jason\") still match a longer saved ``display_name`` (substring boost in ``find_ranked_matches``).
    """
    if not ranked:
        return None
    s0 = ranked[0][1]
    if s0 < 0.36:
        return None
    if len(ranked) > 1:
        s1 = ranked[1][1]
        if s1 >= 0.36 and (s0 - s1) < 0.09:
            return None
    return ranked[0][0]


def resolve_for_transfer_send(
    db: Session,
    user_id: int,
    recipient_query: str,
) -> tuple[str | None, SavedRecipient | None, str | None]:
    """
    Match ``recipient_query`` against ``saved_recipients``.

    Returns ``(ambiguous_reply, matched_row, llm_suffix)``:
    - If ``ambiguous_reply`` is set, use it as the full assistant message.
    - Else if ``matched_row`` is set, show the in-app payment card (no extra LLM hint required).
    - Else ``llm_suffix`` is extra system guidance (e.g. no saved match).
    """
    q = recipient_query.strip()
    if not q:
        return None, None, None
    ranked = find_ranked_matches(db, user_id, q)
    strong = [p for p in ranked if p[1] >= 0.35]
    if len(strong) >= 2 and (strong[0][1] - strong[1][1]) < 0.12:
        return format_ambiguous_message(strong[:4]), None, None
    row = _payment_card_match_row(ranked)
    qlow = q.lower()
    if row is None and len(qlow) >= 3:
        try:
            all_rows = db.scalars(select(SavedRecipient).where(SavedRecipient.user_id == user_id)).all()
        except Exception:  # noqa: BLE001
            logger.debug("resolve_for_transfer_send: could not load saved_recipients for substring pass", exc_info=True)
            all_rows = []
        sub_hits = [r for r in all_rows if _substring_hits_saved_name(qlow, r)]
        if len(sub_hits) >= 2:
            return format_ambiguous_message([(r, 0.5) for r in sub_hits[:4]]), None, None
        if len(sub_hits) == 1:
            row = sub_hits[0]
    if row is not None:
        return None, row, None
    return None, None, no_match_instruction(q)


def no_match_instruction(recipient_query: str) -> str:
    """Tell the model not to invent or recycle unrelated accounts when the name does not match saved recipients."""
    safe = recipient_query.strip()[:120]
    return (
        f'[Recipient "{safe}" does not match any saved recipient in Confam for this user. '
        "Do not reuse bank details from other people in this chat. "
        "Do not invent or restate a 10-digit account number. "
        "Reply briefly that you have no saved account under that name, and ask for a bank screenshot or full details if they want help checking.]"
    )


def record_recipient(
    db: Session,
    user_id: int,
    *,
    display_name: str | None,
    account_number: str | None,
    bank_name: str | None,
    extra_alias: str | None = None,
    tx_ref: str | None = None,
    account_name: str | None = None,
) -> None:
    """
    Upsert a saved recipient. Never raises: DB errors are logged and the session is rolled back.

    Requires non-empty ``bank_name`` (confirmed bank details); otherwise skips with an info log.
    ``account_name`` is optional and stored only when non-empty after strip.
    """
    ref = (tx_ref or "").strip() or (account_number or "unknown")
    if not account_number or len(account_number) != 10 or not account_number.isdigit():
        return
    bank = (bank_name or "").strip()
    if not bank:
        logger.info(
            "Skipped saving recipient for %s - missing required bank details.",
            ref,
        )
        return

    raw_display = (display_name or "").strip()
    raw_alias = (extra_alias or "").strip()
    explicit_acct_name = (account_name or "").strip()
    display_for_row = raw_display or raw_alias or explicit_acct_name or "Recipient"
    account_name_for_row = explicit_acct_name or raw_display or raw_alias or None

    try:
        now = datetime.now(timezone.utc)
        existing = db.scalar(
            select(SavedRecipient).where(
                SavedRecipient.user_id == user_id,
                SavedRecipient.account_number == account_number,
            ),
        )
        if existing:
            existing.display_name = display_for_row[:255]
            if account_name_for_row:
                existing.account_name = account_name_for_row[:255]
            existing.bank_name = bank[:255]
            existing.usage_frequency = int(existing.usage_frequency or 0) + 1
            existing.last_used = now
            aliases = _aliases_list(existing)
            for piece in (extra_alias, display_for_row):
                if piece and piece.strip() and piece.strip() not in aliases:
                    aliases.append(piece.strip()[:120])
            existing.aliases = aliases
            db.add(existing)
            return
        seed_aliases: list[str] = []
        if extra_alias and extra_alias.strip():
            seed_aliases.append(extra_alias.strip()[:120])
        if display_for_row and display_for_row not in seed_aliases:
            seed_aliases.append(display_for_row[:120])
        db.add(
            SavedRecipient(
                user_id=user_id,
                display_name=display_for_row[:255],
                account_number=account_number,
                bank_name=bank[:255],
                account_name=account_name_for_row[:255] if account_name_for_row else None,
                aliases=seed_aliases or None,
                usage_frequency=1,
                last_used=now,
            ),
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "saved_recipients record_recipient failed (non-fatal) ref=%s user_id=%s",
            ref,
            user_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("record_recipient rollback failed", exc_info=True)


def upsert_payment_recipient_safe(
    db: Session,
    user_id: int,
    *,
    bank_verified_account_name: str | None,
    display_account_name: str | None,
    account_number: str | None,
    bank_name: str | None,
    extra_alias: str | None = None,
) -> None:
    """
    After a payment-related turn: insert or update saved_recipients.

    - Prefer **bank-verified** account holder name when present (Squad lookup).
    - Otherwise use OCR / assistant display name.
    - If the row exists (same user + account_number): bumps usage_frequency and last_used
      (via record_recipient).

    Uses a SAVEPOINT so ORM/DB errors here do not abort the outer chat transaction; on failure
    the savepoint is rolled back automatically.
    """
    verified = (bank_verified_account_name or "").strip()
    display = (display_account_name or "").strip()
    chosen = verified or display or None
    try:
        with db.begin_nested():
            record_recipient(
                db,
                user_id,
                display_name=chosen,
                account_number=account_number,
                bank_name=bank_name,
                extra_alias=extra_alias,
                account_name=chosen,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "saved_recipients upsert failed for user_id=%s account=%s (savepoint rolled back)",
            user_id,
            account_number,
            exc_info=True,
        )
