from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base

if TYPE_CHECKING:
    from models.user import User


class SavedRecipient(Base):
    """Recently used bank recipients for fuzzy re-match in chat."""

    __tablename__ = "saved_recipients"
    __table_args__ = (UniqueConstraint("user_id", "account_number", name="uq_saved_recipient_user_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    aliases: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    usage_frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="saved_recipients")
