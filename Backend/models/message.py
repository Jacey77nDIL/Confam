from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant | system
    msg_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="text",
    )  # text | image | voice | payment_image
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    payment_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    session = relationship("ChatSession", back_populates="messages")
    file = relationship("UploadedFile", foreign_keys=[file_id])
