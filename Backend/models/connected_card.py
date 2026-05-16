"""Persisted tokenized card (Squad) — never store PAN/CVV."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base

if TYPE_CHECKING:
    from models.user import User


class ConnectedCard(Base):
    __tablename__ = "connected_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    squad_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorization_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    reusable_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    masked_pan: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    expiry_month: Mapped[str | None] = mapped_column(String(4), nullable=True)
    expiry_year: Mapped[str | None] = mapped_column(String(8), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verification_transaction_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    verification_gateway_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refund_initiated: Mapped[bool] = mapped_column(default=False)

    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="connected_cards")
