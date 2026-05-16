from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default="New chat", max_length=255)


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    msg_type: str
    content: str | None
    transcript: str | None
    ocr_payload: dict[str, Any] | None = None
    payment_metadata: dict[str, Any] | None = None
    file_id: int | None = None
    file_url: str | None = None
    created_at: datetime


class ClientGeoMixin(BaseModel):
    """Optional approximate device coordinates (browser geolocation)."""

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _coords_both_or_neither(self) -> ClientGeoMixin:
        if (self.latitude is None) ^ (self.longitude is None):
            self.latitude = None
            self.longitude = None
        return self


class SendTextBody(ClientGeoMixin):
    text: str = Field(..., min_length=1, max_length=8000)


class SendImageBody(ClientGeoMixin):
    file_id: int = Field(..., ge=1)
    caption: str | None = Field(default=None, max_length=2000)


class SendVoiceBody(ClientGeoMixin):
    file_id: int = Field(..., ge=1)


class SendPaymentBody(ClientGeoMixin):
    file_id: int = Field(..., ge=1)
    text: str | None = Field(default=None, max_length=8000)


class TurnResult(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class UploadedFileOut(BaseModel):
    id: int
    mime_type: str | None
    original_name: str | None
    file_url: str | None
    file_type: str
