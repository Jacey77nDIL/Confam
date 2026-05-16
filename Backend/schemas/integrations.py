from pydantic import BaseModel, Field


class CardVerificationInitiateIn(BaseModel):
    return_url: str = Field(..., max_length=2048, description="Frontend callback after Squad checkout")


class CardVerificationInitiateOut(BaseModel):
    checkout_url: str
    transaction_ref: str
    message: str = "Open the secure checkout to finish linking your card."


class CardVerificationFinalizeOut(BaseModel):
    success: bool
    message: str


class ConnectedCardOut(BaseModel):
    status: str
    card_type: str | None = None
    masked_pan: str | None = None
    last4: str | None = None
    brand_label: str | None = None


class PaymentExecuteIn(BaseModel):
    amount_kobo: int = Field(..., ge=100, description="Amount in kobo (₦1 = 100)")
    recipient_account_number: str = Field(..., min_length=10, max_length=14)
    recipient_bank_name: str | None = Field(default=None, max_length=255)
    recipient_account_name: str = Field(..., min_length=2, max_length=255)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    assistant_message_id: int | None = Field(default=None, ge=1)


class PaymentExecuteOut(BaseModel):
    success: bool
    message: str
    transaction_id: int | None = None
    duplicate: bool = False
    payout_deferred: bool = False
