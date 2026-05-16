"""
ORM package for BuyWise.

See also the sibling ``models.py`` (documentation only; ``import models`` loads this package).

``SavedRecipient`` maps ``saved_recipients``; ``bank_name`` and ``account_name`` are nullable
(see ``models.saved_recipient``). Sync the table with the ORM using
``database/migrations/ensure_saved_recipients_orm_columns.sql`` (adds ``account_name``, ``aliases``,
``usage_frequency``, ``last_used``, and ``bank_name`` if missing).
"""

from models.connected_card import ConnectedCard
from models.chat_session import ChatSession
from models.message import Message
from models.payment_extraction import PaymentExtraction
from models.payment_transaction import PaymentTransaction
from models.saved_recipient import SavedRecipient
from models.uploaded_file import UploadedFile
from models.user import User
from models.whatsapp_session import WhatsappInboundDedupe, WhatsappSession

__all__ = [
    "User",
    "ChatSession",
    "Message",
    "UploadedFile",
    "PaymentExtraction",
    "SavedRecipient",
    "ConnectedCard",
    "PaymentTransaction",
    "WhatsappSession",
    "WhatsappInboundDedupe",
]
