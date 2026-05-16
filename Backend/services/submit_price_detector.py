"""
Rule-based detection and extraction for conversational market price submissions.

Runs before ML so SUBMIT_PRICE is not lost when ``/parse`` misclassifies intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.message import Message

# --- Conversational signals (Nigerian English / Pidgin) -------------------------

_SUBMIT_LONG_PHRASES = re.compile(
    r"\b("
    r"bought\s+(?:it\s+)?for|buy\s+(?:am\s+)?for|got\s+(?:it\s+|this\s+|am\s+)?for|"
    r"got\s+\w+\s+for|pay(?:ed)?\s+|cost\s+me|it\s+cost|"
    r"sold\s+(?:for|at)|selling\s+(?:for|at)|"
    r"now\s+(?:₦|n|ngn)?|is\s+now|"
    r"(?:expensive|cheap)\s*[,\s]+.*\d|"
    r"for\s+(?:₦|n|ngn)?\s*\d|\d+\s*(?:k|thousand)\s+now|"
    r"priced?\s+at|"
    r"last\s+(?:week|time)\s+(?:it\s+)?(?:was|cost)"
    r")\b",
    re.IGNORECASE,
)

# Bare "2k" / "15k" near report-like words
_SUBMIT_SHORT = re.compile(
    r"\b("
    r"\d+(?:\.\d+)?\s*k\b|\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"₦\s*\d+|[Nn]\s*\d[\d,]*|"
    r"\d+\s*thousand"
    r")",
    re.IGNORECASE,
)

_PRODUCT_LEXICON = (
    "garri",
    "rice",
    "beans",
    "yam",
    "plantain",
    "tomato",
    "tomatoes",
    "onion",
    "onions",
    "pepper",
    "oil",
    "palm oil",
    "vegetable oil",
    "fish",
    "chicken",
    "beef",
    "egg",
    "eggs",
    "bread",
    "sugar",
    "salt",
    "flour",
    "maize",
    "corn",
    "semo",
    "cassava",
    "potato",
    "potatoes",
    "crayfish",
    "melon",
    "spaghetti",
    "indomie",
    "noodle",
)

_LOCATION_HINTS = (
    "mile 12",
    "mile12",
    "wuse",
    "yaba",
    "lekki",
    "ikeja",
    "ojota",
    "oyingbo",
    "bodija",
    "mararaba",
    "nyanya",
    "ariaria",
    "onitsha",
    "benin",
)


def _lexicon_regex(terms: tuple[str, ...]) -> re.Pattern[str]:
    esc = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(esc) + r")\b", re.IGNORECASE)


_PRODUCT_RE = _lexicon_regex(_PRODUCT_LEXICON)
_LOCATION_RE = _lexicon_regex(_LOCATION_HINTS)

# "yam is 7k in wuse" / "rice is now 900"
_LEADING_PRODUCT_PRICE = re.compile(
    r"^(\w+(?:\s+\w+)?)\s+is\s+(?:now\s+)?(?:₦|n|ngn)?\s*(\d[\d,\.]*(?:k|thousand|m)?)\b",
    re.IGNORECASE,
)


@dataclass
class SubmitPriceContext:
    """Recent chat lines + inferred entities for anaphora (\"got it for 1k\")."""

    recent_user_lines: list[str] = field(default_factory=list)
    hinted_product: str | None = None
    hinted_location: str | None = None
    image_product: str | None = None


def build_submit_price_context(
    db: Session,
    session_id: int,
    *,
    before_message_id: int | None = None,
    image_product: str | None = None,
) -> SubmitPriceContext:
    q = (
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.role == "user",
        )
        .order_by(Message.id.desc())
        .limit(18)
    )
    if before_message_id is not None:
        q = q.where(Message.id < before_message_id)
    rows = list(db.scalars(q).all())
    rows.reverse()
    lines: list[str] = []
    hinted_product: str | None = None
    hinted_location: str | None = None
    for m in rows:
        t = (m.content or "").strip()
        if m.msg_type == "voice" and (m.transcript or "").strip():
            t = (m.transcript or "").strip()
        elif m.msg_type == "image":
            t = (m.content or "").strip()
        if not t:
            continue
        lines.append(t)
        hp, hl = _infer_query_entities_from_line(t)
        if hp:
            hinted_product = hp
        if hl:
            hinted_location = hl

    img = (image_product or "").strip().lower() or None
    if img and not hinted_product:
        hinted_product = img

    return SubmitPriceContext(
        recent_user_lines=lines,
        hinted_product=hinted_product,
        hinted_location=hinted_location,
        image_product=img,
    )


def _infer_query_entities_from_line(line: str) -> tuple[str | None, str | None]:
    low = line.lower()
    prod: str | None = None
    loc: str | None = None
    m = re.search(
        r"how\s+much\s+is\s+(.+?)\s+in\s+(.+?)(?:\?|$)",
        low,
    )
    if not m:
        m = re.search(r"price\s+(?:of\s+)?(.+?)\s+in\s+(.+?)(?:\?|$)", low)
    if m:
        prod = _clean_entity(m.group(1))
        loc = _clean_entity(m.group(2))
    else:
        m2 = re.search(r"\bprice\s+of\s+(\w+(?:\s+\w+)?)", low)
        if m2:
            prod = _clean_entity(m2.group(1))
    pm = _PRODUCT_RE.search(line)
    if pm and not prod:
        prod = _clean_entity(pm.group(1))
    lm = _LOCATION_RE.search(line)
    if lm and not loc:
        loc = _clean_entity(lm.group(1))
    return prod, loc


def _clean_entity(s: str) -> str | None:
    x = " ".join(s.strip().lower().split())
    x = re.sub(r"[\?\!\.]+$", "", x)
    if x in ("it", "this", "that", "am", "dat", "one"):
        return None
    return x or None


def probable_submit_price(text: str) -> bool:
    """Fast check: likely a price report, not a pure price question."""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if low.startswith("how much") or re.match(r"^what(?:'s| is) the price", low):
        return False
    if _SUBMIT_LONG_PHRASES.search(t):
        if _SUBMIT_SHORT.search(t):
            return True
    # "Rice is now 900" / "Beans 3500"
    if _LEADING_PRODUCT_PRICE.match(t.strip()):
        return True
    if re.search(
        r"\b(?:is|are)\s+now\s+(?:₦|n|ngn|\d)", t, re.I
    ) and _SUBMIT_SHORT.search(t):
        got_keywords = bool(
            _PRODUCT_RE.search(t) or any(p in low for p in _PRODUCT_LEXICON)
        )
        return got_keywords
    # "tomatoes 12k in mile 12" — product + money + location-ish
    if _PRODUCT_RE.search(t) and _SUBMIT_SHORT.search(t):
        return True
    return False


def _normalize_one_amount(num_str: str, suffix: str | None) -> float | None:
    s = (num_str or "").replace(",", "").strip()
    suf = (suffix or "").lower().strip()
    try:
        base = float(s)
    except ValueError:
        return None
    if suf in ("k", "thousand", "grand"):
        return base * 1000
    if suf == "m":
        return base * 1_000_000
    if abs(base) < 120 and re.search(r"\d+\s*k\b", f"{base}k", re.I):
        pass
    return base


def normalize_price_from_text(text: str) -> float | None:
    """Best single naira amount from a line (prefers k / explicit naira)."""
    t = text or ""
    candidates: list[tuple[float, int]] = []  # value, strength

    def add(val: float, strength: int) -> None:
        if 30 <= val <= 50_000_000:
            candidates.append((val, strength))

    for m in re.finditer(
        r"(₦|N|NGN|naira)\s*([\d,]+(?:\.\d+)?)",
        t,
        re.I,
    ):
        try:
            add(float(m.group(2).replace(",", "")), 5)
        except ValueError:
            pass

    for m in re.finditer(
        r"\b(\d+(?:\.\d+)?)\s*(k|K)\b",
        t,
    ):
        try:
            base = float(m.group(1))
            add(base * 1000, 4)
        except ValueError:
            pass

    for m in re.finditer(
        r"([\d,]+(?:\.\d+)?)\s*(k|K|thousand|m|M)\b",
        t,
    ):
        v = _normalize_one_amount(m.group(1), m.group(2))
        if v is not None:
            add(v, 4)

    for m in re.finditer(
        r"\b([\d,]+)(?=\s*(?:naira|ngn)\b)",
        t,
        re.I,
    ):
        try:
            add(float(m.group(1).replace(",", "")), 3)
        except ValueError:
            pass

    for m in re.finditer(
        r"\b(\d+)\s+thousand\b",
        t,
        re.I,
    ):
        add(float(m.group(1)) * 1000, 4)

    # Bare number — weak
    for m in re.finditer(r"\b(\d{3,}(?:,\d{3})*(?:\.\d+)?)\b", t):
        try:
            add(float(m.group(1).replace(",", "")), 1)
        except ValueError:
            pass

    if not candidates:
        for m in re.finditer(r"\b(\d{1,2})\b", t):
            try:
                n = float(m.group(1))
                if 1 <= n <= 9 and re.search(r"\b" + re.escape(m.group(1)) + r"\s*k\b", t, re.I):
                    add(n * 1000, 3)
            except ValueError:
                pass

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[1], -x[0]))
    return candidates[0][0]


def extract_submit_price_data(
    message: str,
    ctx: SubmitPriceContext,
) -> dict[str, object] | None:
    """
    Extract structured submit payload. Returns None if no price found.
    """
    raw = (message or "").strip()
    if not raw:
        return None
    price = normalize_price_from_text(raw)
    if price is None:
        return None

    product: str | None = None
    loc: str | None = None
    unit: str | None = None

    m = _LEADING_PRODUCT_PRICE.match(raw.strip())
    if m:
        product = _clean_entity(m.group(1))
        pfrag = m.group(2)
        p2 = normalize_price_from_text(pfrag + " ")
        if p2 is not None:
            price = float(p2)

    if not product:
        gm = re.search(
            r"got\s+(?!it\b|this\b|that\b|am\b)(\w+)\s+for",
            raw,
            re.I,
        )
        if gm:
            w = gm.group(1).lower()
            if w not in ("it", "this", "that", "am"):
                product = _clean_entity(gm.group(1))

    if not product:
        pm = _PRODUCT_RE.search(raw)
        if pm:
            product = _clean_entity(pm.group(1))

    ll = re.search(
        r"\b(?:in|at|inside)\s+([a-z0-9][a-z0-9\s]{0,40}?)(?:\.|,|$)",
        raw,
        re.I,
    )
    if ll:
        loc = _clean_entity(ll.group(1))

    if not loc:
        lm = _LOCATION_RE.search(raw)
        if lm:
            loc = _clean_entity(lm.group(1))

    um = re.search(r"\b(per|per\s+)\s*(mudu|kg|basket|bag|paint)\b", raw, re.I)
    if um:
        unit = f"{um.group(2)}".lower()

    # Context merge (memory)
    if not product:
        product = ctx.hinted_product or ctx.image_product
    if not loc:
        loc = ctx.hinted_location

    # Confidence
    conf = 0.55
    if _SUBMIT_LONG_PHRASES.search(raw):
        conf += 0.12
    if product and product in raw.lower():
        conf += 0.12
    if product and (ctx.hinted_product == product or ctx.image_product == product):
        conf += 0.05
    if loc:
        conf += 0.08
    if unit:
        conf += 0.03
    conf = min(0.95, conf)

    return {
        "intent": "SUBMIT_PRICE",
        "product": product,
        "location": loc,
        "price": float(price),
        "unit": unit,
        "confidence": round(conf, 2),
        "source_message": raw,
    }
