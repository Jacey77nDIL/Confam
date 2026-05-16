"""Price report storage and aggregate stats for market QUERY responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.price_report import PriceReport

MIN_PRICE_NAIRA = 50.0
MAX_PRICE_NAIRA = 50_000_000.0
DUPLICATE_WINDOW_MINUTES = 5


@dataclass(frozen=True)
class PriceStats:
    count: int
    latest_price: float
    average_price: float
    min_price: float
    max_price: float
    latest_at: datetime | None


def normalize_entity(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def validate_submitted_price(price: float | None) -> str | None:
    """Return an error message if price is invalid, else ``None``."""
    if price is None:
        return "Please include a price in naira."
    if price < MIN_PRICE_NAIRA:
        return f"That price looks too low (minimum ₦{int(MIN_PRICE_NAIRA):,}). Please double-check."
    if price > MAX_PRICE_NAIRA:
        return "That price looks unusually high. Please confirm the amount."
    return None


def get_price_stats(db: Session, product: str, location: str) -> PriceStats | None:
    p = normalize_entity(product)
    loc = normalize_entity(location)
    row = db.execute(
        select(
            func.count(PriceReport.id),
            func.max(PriceReport.created_at),
            func.avg(PriceReport.price),
            func.min(PriceReport.price),
            func.max(PriceReport.price),
        ).where(
            func.lower(PriceReport.product) == p,
            func.lower(PriceReport.location) == loc,
        ),
    ).one()
    count = int(row[0] or 0)
    if count == 0:
        return None

    latest_row = db.scalars(
        select(PriceReport)
        .where(
            func.lower(PriceReport.product) == p,
            func.lower(PriceReport.location) == loc,
        )
        .order_by(PriceReport.created_at.desc())
        .limit(1),
    ).first()

    return PriceStats(
        count=count,
        latest_price=float(latest_row.price) if latest_row else float(row[2] or 0),
        average_price=float(row[2] or 0),
        min_price=float(row[3] or 0),
        max_price=float(row[4] or 0),
        latest_at=row[1],
    )


def has_recent_duplicate(
    db: Session,
    *,
    user_id: int | None,
    product: str,
    location: str,
    price: float,
) -> bool:
    if user_id is None:
        return False
    since = datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    p = normalize_entity(product)
    loc = normalize_entity(location)
    existing = db.scalars(
        select(PriceReport.id)
        .where(
            PriceReport.user_id == user_id,
            func.lower(PriceReport.product) == p,
            func.lower(PriceReport.location) == loc,
            PriceReport.price == float(price),
            PriceReport.created_at >= since,
        )
        .limit(1),
    ).first()
    return existing is not None


def save_price_report(
    db: Session,
    *,
    user_id: int | None,
    raw_message: str,
    normalized_message: str | None,
    product: str,
    location: str,
    price: float,
    unit: str | None,
    quantity: float | None,
    confidence: float,
    source: str,
    extracted_by: str = "ml",
) -> PriceReport:
    row = PriceReport(
        user_id=user_id,
        raw_message=raw_message,
        normalized_message=normalized_message,
        product=normalize_entity(product),
        location=normalize_entity(location),
        unit=(unit or "").strip() or None,
        quantity=quantity,
        price=float(price),
        confidence=float(confidence),
        source=source,
        extracted_by=(extracted_by or "ml").strip()[:32] or "ml",
    )
    db.add(row)
    db.flush()
    return row
