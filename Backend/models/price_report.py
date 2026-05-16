"""Crowd-sourced market price reports (fed by ML `/parse` pipeline)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class PriceReport(Base):
    __tablename__ = "price_reports"
    __table_args__ = (
        Index("ix_price_reports_product", "product"),
        Index("ix_price_reports_location", "location"),
        Index("ix_price_reports_created_at", "created_at"),
        Index("ix_price_reports_product_location", "product", "location"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    product: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    extracted_by: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ml"
    )  # ml | submit_price_rules | hybrid | image_context
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
