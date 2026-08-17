from pydantic import BaseModel, Field


class PaymentDiagnosticRequest(BaseModel):
    report_id: int = Field(..., gt=0)
    calculation_id: int = Field(..., gt=0)


class PaymentClientDetails(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone_number: str


class PaymentGatewayPayload(BaseModel):
    amount: float
    currency: str
    description: str
    external_reference_id: str
    success_redirect_url: str
    failure_redirect_url: str
    client_details: PaymentClientDetails


class PaymentDiagnosticResponse(BaseModel):
    success: bool
    payment_table_ready: bool
    payload: PaymentGatewayPayload
    message: str


class PaymentSessionResponse(BaseModel):
    success: bool
    payment_id: int
    session_token: str
    checkout_url: str
    expires_at: str | None = None
    status: str
    message: str


class PaymentStatusResponse(BaseModel):
    payment_id: int
    external_reference_id: str
    report_id: int
    calculation_id: int
    amount: float
    currency: str
    status: str
    transaction_id: str | None = None
    expires_at: str | None = None
    paid_at: str | None = None
    created_at: str
