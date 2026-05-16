"""Market pricing: rule-based SUBMIT first, then ML ``/process`` for user-facing replies."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from config import ML_CONFIDENCE_MIN
from models.user import User
from services import market_analytics_service, ml_parser_service, submit_price_detector
from services.market_analytics_service import PriceStats
from services.ml_parser_service import MLParseResult, MLParserError

logger = logging.getLogger(__name__)

_GREETING_REPLY = (
    "Welcome to Confam! Ask for a market price, e.g. "
    '"how much is garri in yaba", or report what you paid: '
    '"tomatoes 15000 at mile 12".'
)
_UNKNOWN_REPLY = (
    "I couldn't quite get that. Try something like: "
    '"how much is rice in wuse market".'
)
_ML_DOWN_REPLY = (
    "Market pricing is temporarily unavailable. "
    "Please try again in a moment."
)
_PAYMENT_TEXT_REPLY = (
    "To send money, say who you want to pay (e.g. send 5000 to Ada) "
    "or upload a payment screenshot."
)

_MISSING_PRODUCT = "unspecified"
_MISSING_LOCATION = "unknown"


def payment_help_reply() -> str:
    return _PAYMENT_TEXT_REPLY


def is_configured() -> bool:
    return ml_parser_service.is_configured()


def normalize_message(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _display_name(value: str) -> str:
    return " ".join(w.capitalize() for w in (value or "").split())


def _fmt_naira(amount: float) -> str:
    if abs(amount - round(amount)) < 1e-9:
        return f"{int(round(amount)):,}"
    return f"{amount:,.2f}".rstrip("0").rstrip(".")


def _format_query_reply(product: str, location: str, stats: PriceStats) -> str:
    prod = _display_name(product)
    loc = _display_name(location)
    avg = stats.average_price
    lo = stats.min_price
    hi = stats.max_price
    if stats.count == 1 or abs(lo - hi) < 1:
        return f"{prod} in {loc} is around ₦{_fmt_naira(avg)} (from {stats.count} report)."
    return (
        f"{prod} in {loc} is around ₦{_fmt_naira(avg)} "
        f"(roughly ₦{_fmt_naira(lo)}–₦{_fmt_naira(hi)} from {stats.count} reports)."
    )


def _handle_query(db: Session, parsed: MLParseResult) -> str:
    if not parsed.product or not parsed.location:
        if _low_confidence(parsed, require_product=True, require_location=True):
            return _clarify_product_location()
        return "Please include both the product and market/location."

    stats = market_analytics_service.get_price_stats(db, parsed.product, parsed.location)
    if not stats:
        prod = _display_name(parsed.product)
        loc = _display_name(parsed.location)
        return (
            f"No price data yet for {prod} in {loc}. "
            f"If you've bought it recently, tell us what you paid — e.g. "
            f'"{parsed.product} 5000 at {parsed.location}".'
        )
    return _format_query_reply(parsed.product, parsed.location, stats)


def _low_confidence(
    parsed: MLParseResult,
    *,
    require_product: bool = False,
    require_location: bool = False,
) -> bool:
    if parsed.confidence >= ML_CONFIDENCE_MIN:
        return False
    if require_product and not parsed.product:
        return True
    if require_location and not parsed.location:
        return True
    return parsed.confidence < ML_CONFIDENCE_MIN


def _clarify_product_location() -> str:
    return "Please rephrase with the product and market, e.g. how much is garri in yaba."


def _try_save_extraction(
    db: Session,
    user: User | None,
    *,
    raw_message: str,
    normalized_message: str,
    data: dict[str, Any],
    source: str,
    extracted_by: str,
) -> str | None:
    price = data.get("price")
    if price is None:
        return None
    err = market_analytics_service.validate_submitted_price(float(price))
    if err:
        return err

    product = (data.get("product") or _MISSING_PRODUCT) or _MISSING_PRODUCT
    location = (data.get("location") or _MISSING_LOCATION) or _MISSING_LOCATION
    unit = data.get("unit")
    conf = float(data.get("confidence") or 0.7)

    uid = user.id if user else None
    if market_analytics_service.has_recent_duplicate(
        db,
        user_id=uid,
        product=product,
        location=location,
        price=float(price),
    ):
        return "You already submitted that price a moment ago. Thanks!"

    market_analytics_service.save_price_report(
        db,
        user_id=uid,
        raw_message=raw_message,
        normalized_message=normalized_message,
        product=product,
        location=location,
        price=float(price),
        unit=str(unit) if unit is not None else None,
        quantity=_as_float(data.get("quantity")),
        confidence=conf,
        source=source,
        extracted_by=extracted_by,
    )
    db.commit()

    prod_disp = _display_name(product)
    loc_disp = _display_name(location)
    if product == _MISSING_PRODUCT:
        return (
            f"Logged ₦{_fmt_naira(float(price))} (location: {loc_disp}). "
            "Next time name the product too, e.g. rice 2500 in Yaba."
        )
    return f"Thanks! Recorded {prod_disp} at ₦{_fmt_naira(float(price))} in {loc_disp}."


def _as_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def handle_message(
    db: Session,
    user: User | None,
    message: str,
    *,
    source: str = "web",
    normalized_override: str | None = None,
    session_id: int | None = None,
    before_message_id: int | None = None,
    image_product: str | None = None,
) -> str:
    raw = (message or "").strip()
    if not raw:
        return "Send a message about a product and market, e.g. how much is garri in yaba."

    if not is_configured():
        return _ML_DOWN_REPLY

    normalized = normalized_override or normalize_message(raw)
    if session_id is not None:
        ctx = submit_price_detector.build_submit_price_context(
            db,
            session_id,
            before_message_id=before_message_id,
            image_product=image_product,
        )
    else:
        ip = (image_product or "").strip().lower() or None
        ctx = submit_price_detector.SubmitPriceContext(image_product=ip)

    # --- 1) Rule-based submit (pre-ML; source of truth when confident) ---
    if submit_price_detector.probable_submit_price(normalized):
        extracted = submit_price_detector.extract_submit_price_data(normalized, ctx)
        if extracted and extracted.get("price") is not None:
            saved = _try_save_extraction(
                db,
                user,
                raw_message=raw,
                normalized_message=normalized,
                data=extracted,
                source=source,
                extracted_by="image_context"
                if image_product
                else "submit_price_rules",
            )
            if saved:
                return saved

        if (
            submit_price_detector.normalize_price_from_text(normalized) is not None
        ):
            return (
                "I see a price — add what you bought and where "
                "(e.g. rice 900 in Lekki) so I can log it."
            )

    # --- 2) ML /process — full pipeline reply (NLU + price engine + response gen) ---
    uid = str(user.id) if user else "anonymous"
    try:
        return ml_parser_service.process_market_message(normalized, user_id=uid)
    except MLParserError:
        logger.exception("ML /process failed")
        return _ML_DOWN_REPLY


def handle_identified_product(
    db: Session,
    user: User | None,
    product: str,
    *,
    caption: str | None = None,
    source: str = "image",
    session_id: int | None = None,
    before_message_id: int | None = None,
) -> str:
    from services.product_identification_service import build_market_query

    query = build_market_query(product, caption)
    return handle_message(
        db,
        user,
        query,
        source=source,
        normalized_override=normalize_message(query),
        session_id=session_id,
        before_message_id=before_message_id,
        image_product=product,
    )
