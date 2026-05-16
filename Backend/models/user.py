from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base

if TYPE_CHECKING:
    from models.connected_card import ConnectedCard
    from models.payment_transaction import PaymentTransaction
    from models.saved_recipient import SavedRecipient


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    saved_recipients: Mapped[list["SavedRecipient"]] = relationship(
        "SavedRecipient",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    connected_cards: Mapped[list["ConnectedCard"]] = relationship(
        "ConnectedCard",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    payment_transactions: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction",
        back_populates="user",
        cascade="all, delete-orphan",
    )
