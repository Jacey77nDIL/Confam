from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base

if TYPE_CHECKING:
    from models.user import User


class PaymentTransaction(Base):
    """
    Chat-initiated card charge + (when enabled) Squad wallet payout to recipient.

    ``status`` values include ``pending``, ``processing``, ``failed``, ``success`` (legacy),
    and ``FUNDS_COLLECTED`` when the card charge succeeded but outbound payout is deferred
    (collection-only / manual disbursement).
    """

    __tablename__ = "payment_transactions"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_payment_idempotency"),)

    STATUS_FUNDS_COLLECTED = "FUNDS_COLLECTED"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_account: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_bank: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    squad_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorization_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="payment_transactions")
