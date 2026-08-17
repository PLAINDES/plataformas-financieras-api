import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.database import get_db
from app.models.main import Calculation, Report, ReportPayment
from app.models.user import User
from app.schemas.payments import (
    PaymentClientDetails,
    PaymentDiagnosticRequest,
    PaymentDiagnosticResponse,
    PaymentGatewayPayload,
    PaymentSessionResponse,
    PaymentStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/main/report-payments", tags=["Report payments"])

_CURRENCY_ALIASES = {"SOLES": "PEN", "SOL": "PEN", "S/": "PEN"}
_CHECKOUT_URL_PREFIX = "https://platinumarket.proideas.org/embedded/pay"


def _normalize_currency(value: str | None) -> str:
    currency = (value or "").strip().upper()
    currency = _CURRENCY_ALIASES.get(currency, currency)
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=422, detail="El reporte no tiene una moneda ISO valida")
    return currency


def _redirect_url(configured_url: str, request: Request, path: str) -> str:
    if configured_url.strip():
        return configured_url.strip()
    origin = request.headers.get("origin", "").rstrip("/") or "http://localhost:5173"
    return f"{origin}{path}"


def _validate_payment_table(db: Session) -> None:
    try:
        db.execute(select(ReportPayment.id).limit(1)).first()
    except SQLAlchemyError as exc:
        logger.exception("Payment table validation failed")
        raise HTTPException(
            status_code=503,
            detail="La migracion de pagos no esta disponible. Ejecute 'alembic upgrade head'.",
        ) from exc


def _build_payment_payload(
    data: PaymentDiagnosticRequest,
    request: Request,
    db: Session,
    current_user: User,
) -> tuple[Report, Calculation, PaymentGatewayPayload]:
    report = db.get(Report, data.report_id)
    if not report or report.deleted_at is not None or not report.activo:
        raise HTTPException(status_code=404, detail="Reporte no disponible")

    calculation = db.get(Calculation, data.calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculo no encontrado")
    if calculation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="El calculo no pertenece al usuario autenticado")
    if calculation.type != report.type:
        raise HTTPException(status_code=422, detail="El reporte no es compatible con el calculo")

    amount = Decimal(report.precio or 0)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="El reporte no tiene un precio valido")
    description = (report.contenido or "").strip()
    if not description:
        raise HTTPException(status_code=422, detail="El reporte no tiene descripcion de pago")
    phone_number = (current_user.phone_number or "").strip()
    if len(phone_number) < 7:
        raise HTTPException(status_code=422, detail="El usuario no tiene un telefono valido")

    _validate_payment_table(db)
    payload = PaymentGatewayPayload(
        amount=float(amount),
        currency=_normalize_currency(report.moneda),
        description=description,
        external_reference_id=f"report-{report.id}-calculation-{calculation.id}-{uuid.uuid4().hex}",
        success_redirect_url=_redirect_url(settings.PAYMENT_SUCCESS_REDIRECT_URL, request, "/pagos/exito"),
        failure_redirect_url=_redirect_url(settings.PAYMENT_FAILURE_REDIRECT_URL, request, "/pagos/error"),
        client_details=PaymentClientDetails(
            email=current_user.email,
            first_name=current_user.name.strip(),
            last_name=(current_user.lastname or "").strip(),
            phone_number=phone_number,
        ),
    )
    return report, calculation, payload


def _payment_status_response(payment: ReportPayment) -> PaymentStatusResponse:
    return PaymentStatusResponse(
        payment_id=payment.id,
        external_reference_id=payment.external_reference_id,
        report_id=payment.report_id,
        calculation_id=payment.calculation_id,
        amount=float(payment.amount),
        currency=payment.currency,
        status=payment.status,
        transaction_id=payment.transaction_id,
        expires_at=payment.expires_at.isoformat() if payment.expires_at else None,
        paid_at=payment.paid_at.isoformat() if payment.paid_at else None,
        created_at=payment.created_at.isoformat(),
    )


@router.get("/{payment_id}", response_model=PaymentStatusResponse)
def get_payment_status(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentStatusResponse:
    payment = db.get(ReportPayment, payment_id)
    if not payment or payment.user_id != current_user.id:
        # Do not reveal whether a payment belonging to another user exists.
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return _payment_status_response(payment)


@router.post("/diagnostic", response_model=PaymentDiagnosticResponse)
def diagnose_payment_payload(
    data: PaymentDiagnosticRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentDiagnosticResponse:
    report, calculation, payload = _build_payment_payload(data, request, db, current_user)
    print(
        f"[PAYMENT][DIAGNOSTIC PAYLOAD] user_id={current_user.id} "
        f"report_id={report.id} calculation_id={calculation.id}\n"
        f"{json.dumps(payload.model_dump(), ensure_ascii=False, indent=2)}",
        flush=True,
    )
    return PaymentDiagnosticResponse(
        success=True,
        payment_table_ready=True,
        payload=payload,
        message="Payload de pago validado. No se creo ningun cobro.",
    )


@router.post("/sessions", response_model=PaymentSessionResponse)
async def create_payment_session(
    data: PaymentDiagnosticRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentSessionResponse:
    if not settings.CULQI_PAYMENTS_ENABLED:
        print(
            "[PAYMENT][CONFIG ERROR] CULQI_PAYMENTS_ENABLED=False",
            flush=True,
        )
        raise HTTPException(status_code=503, detail="La pasarela de pago no esta habilitada")
    base_url = settings.CULQI_INTEGRATION_BASE_URL.strip().rstrip("/")
    api_key = settings.CULQI_INTEGRATION_API_KEY.strip()
    if not base_url or not api_key:
        print(
            "[PAYMENT][CONFIG ERROR] "
            f"base_url_configurada={bool(base_url)} api_key_configurada={bool(api_key)}",
            flush=True,
        )
        raise HTTPException(status_code=503, detail="Falta configurar Certprox en el backend")

    report, calculation, payload = _build_payment_payload(data, request, db, current_user)
    reusable_payment = db.execute(
        select(ReportPayment)
        .where(
            ReportPayment.user_id == current_user.id,
            ReportPayment.report_id == report.id,
            ReportPayment.calculation_id == calculation.id,
            ReportPayment.status == "pending",
            ReportPayment.session_token.is_not(None),
            ReportPayment.checkout_url.is_not(None),
        )
        .order_by(ReportPayment.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if reusable_payment and (
        reusable_payment.expires_at is None
        or reusable_payment.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        print(
            f"[PAYMENT][SESSION REUSED] payment_id={reusable_payment.id} "
            f"user_id={current_user.id} status=pending",
            flush=True,
        )
        return PaymentSessionResponse(
            success=True,
            payment_id=reusable_payment.id,
            session_token=reusable_payment.session_token,
            checkout_url=reusable_payment.checkout_url,
            expires_at=(
                reusable_payment.expires_at.isoformat()
                if reusable_payment.expires_at
                else None
            ),
            status="pending",
            message="Sesion de pago pendiente reutilizada",
        )

    payment = ReportPayment(
        external_reference_id=payload.external_reference_id,
        report_id=report.id,
        calculation_id=calculation.id,
        user_id=current_user.id,
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        description=payload.description,
        status="pending",
        customer_email=payload.client_details.email,
        customer_first_name=payload.client_details.first_name,
        customer_last_name=payload.client_details.last_name,
        customer_phone=payload.client_details.phone_number,
    )
    db.add(payment)
    db.flush()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/integrations/culqi/embedded/sessions",
                json=payload.model_dump(),
                headers={"X-API-Key": api_key},
            )
        response.raise_for_status()
        gateway_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        db.rollback()
        error_response = getattr(exc, "response", None)
        response_status = getattr(error_response, "status_code", None)
        response_body = getattr(error_response, "text", "")[:2000]
        logger.exception(
            "Certprox session creation failed (status=%s, response=%s)",
            response_status,
            response_body or "sin respuesta HTTP",
        )
        raise HTTPException(status_code=502, detail="Certprox no pudo crear la sesion de pago") from exc

    session_token = str(gateway_data.get("session_token") or "").strip()
    checkout_url = str(gateway_data.get("checkout_url") or "").strip()
    expires_at_raw = gateway_data.get("expires_at")
    if not gateway_data.get("success") or not session_token or not checkout_url:
        db.rollback()
        logger.error("Incomplete Certprox response keys=%s", sorted(gateway_data.keys()))
        raise HTTPException(status_code=502, detail="Certprox devolvio una sesion incompleta")
    if not checkout_url.startswith(_CHECKOUT_URL_PREFIX):
        db.rollback()
        logger.error("Certprox returned an unexpected checkout URL")
        raise HTTPException(status_code=502, detail="Certprox devolvio una URL no permitida")

    expires_at = None
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            logger.warning("Certprox returned invalid expires_at")

    payment.session_token = session_token
    payment.checkout_url = checkout_url
    payment.expires_at = expires_at
    db.commit()
    db.refresh(payment)
    print(
        f"[PAYMENT][SESSION CREATED] payment_id={payment.id} user_id={current_user.id} "
        f"report_id={report.id} calculation_id={calculation.id} status=pending",
        flush=True,
    )
    return PaymentSessionResponse(
        success=True,
        payment_id=payment.id,
        session_token=session_token,
        checkout_url=checkout_url,
        expires_at=str(expires_at_raw) if expires_at_raw else None,
        status="pending",
        message="Sesion de pago creada correctamente",
    )
