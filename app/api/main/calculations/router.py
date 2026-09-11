# app/api/main/calculations_router.py
import logging
import re
import time
import traceback
from uuid import uuid4
from typing import Optional

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.main import Calculation, CalculationType
from app.schemas.main import (
    CalculationCreate,
    CalculationResponse,
    CalculationUpdate,
    PaginatedCalculationResponse,
)
from .graphs import _generate_calculation_images
from .macros_service import (
    get_default_or_latest_master_template,
)
from .payload_manager import (
    _normalize_calculation_data,
    _to_calc_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Calculations"])


def _normalize_native_template_values(data):
    """Keep explicit report values under canonical $$CODE$$ keys."""
    if not isinstance(data, dict):
        return data
    values = data.get("template_values")
    if not isinstance(values, dict):
        return data
    normalized = {}
    for raw_code, value in values.items():
        code = f"$${str(raw_code or '').replace('$$', '').replace(' ', '').upper()}$$"
        if code != "$$$$":
            normalized[code] = value
    data["template_values"] = normalized
    return data


def _native_data_values(data):
    """Flatten native JSON into comparable field names without code maps."""
    values = {}

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    if normalized:
                        values.setdefault(normalized, value)
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return values


def _template_value_candidates(label):
    """Generate generic candidates from a template label, not business codes."""
    words = re.findall(r"[a-z0-9]+", str(label or "").lower())
    compact = "".join(words)
    suffixes = ("".join(words[i:]) for i in range(1, len(words)))
    return tuple(dict.fromkeys((compact, *words, *suffixes)))


def _populate_native_template_values(data, calculation_type, db):
    """Attach only exact semantic matches from active template metadata."""
    if not isinstance(data, dict):
        return data
    data = _normalize_native_template_values(data)
    existing = data.get("template_values") or {}
    if not isinstance(existing, dict):
        existing = {}
    source = _native_data_values(data)
    template = get_default_or_latest_master_template(db)
    if not template:
        return data
    for code in template.template_codes:
        if not code or code.deleted_at is not None or code.type != calculation_type:
            continue
        normalized_code = f"$${str(code.code).replace('$$', '').replace(' ', '').upper()}$$"
        if normalized_code in existing or code.template_code_image_id:
            continue
        matched = False
        for candidate in _template_value_candidates(code.nombre):
            if candidate in source:
                existing[normalized_code] = source[candidate]
                matched = True
                logger.info(
                    "[NATIVE TEMPLATE MAP] code=%s label=%s source_key=%s value=%r",
                    normalized_code,
                    code.nombre,
                    candidate,
                    source[candidate],
                )
                break
        if code.source_path and not matched:
            logger.warning(
                "Native template source_path has no matching value: code=%s path=%s",
                normalized_code,
                code.source_path,
            )
        elif not matched:
            logger.info(
                "[NATIVE TEMPLATE UNMAPPED] code=%s label=%s candidates=%s",
                normalized_code,
                code.nombre,
                _template_value_candidates(code.nombre),
            )
    data["template_values"] = existing
    return data

# ==================== ENDPOINTS ====================


@router.get("/calculations", response_model=PaginatedCalculationResponse)
def list_calculations(
    user_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=64),
    type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = select(Calculation)

    if user_id:
        query = query.where(Calculation.user_id == user_id)

    if search:
        query = query.where(Calculation.code.ilike(f"%{search}%"))

    if type:
        query = query.where(Calculation.type == type)

    # Contar total antes de aplicar limit/offset
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar()

    query = (
        query.offset((page - 1) * limit)
        .limit(limit)
        .order_by(Calculation.created_at.desc())
    )
    calculations = db.execute(query).scalars().all()

    return {
        "items": [CalculationResponse.model_validate(c) for c in calculations],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
async def get_calculation(
    request: Request,
    calculation_id: int,
    include_graphs: bool = Query(False),
    bot_token: Optional[str] = Header(None, alias="X-Bot-Token"),
    db: Session = Depends(get_db),
):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    response_data = CalculationResponse.model_validate(calculation).model_dump()

    if include_graphs:
        if bot_token != settings.BOT_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key inválida o ausente.",
            )
        browser = request.app.state.browser
        if not browser:
            raise HTTPException(
                status_code=500, detail="Browser instance not available"
            )

        try:
            # Generar imágenes delegando a la función utilitaria
            base64_images = await _generate_calculation_images(
                calculation.data, browser
            )
            response_data["graphs_base64"] = base64_images
        except Exception as e:
            logger.error(
                f"Error rendering graphs for calculation {calculation_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Error generating calculation graphs"
            )

    return response_data


@router.get("/calculations/by-code/{code}", response_model=CalculationResponse)
async def get_calculation_by_code(
    request: Request,
    code: str,
    include_graphs: bool = Query(False),
    bot_token: Optional[str] = Header(None, alias="X-Bot-Token"),
    db: Session = Depends(get_db),
):
    calculation = (
        db.execute(select(Calculation).where(Calculation.code == code))
        .scalars()
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    # Convertir el modelo validado a diccionario para permitir la inyección de las imágenes
    response_data = CalculationResponse.model_validate(calculation).model_dump()

    if include_graphs:
        if bot_token != settings.BOT_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key inválida o ausente.",
            )
        browser = getattr(request.app.state, "browser", None)
        if not browser:
            logger.error(
                "La instancia del navegador Playwright no está disponible en app.state"
            )
        else:
            try:
                graphs_dict = await _generate_calculation_images(
                    calculation.data, browser
                )
                response_data["graphs_base64"] = graphs_dict
            except Exception as e:
                logger.error(f"Error generando capturas para el código {code}: {e}")
                traceback.print_exc()

    return response_data


@router.post(
    "/calculations",
    response_model=CalculationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):

    t_post = time.perf_counter()
    calc_type = _to_calc_type(payload.type)

    payload_data = dict(payload.data) if isinstance(payload.data, dict) else {}
    prewarmed_session_id = payload_data.pop("prewarmed_session_id", None)

    # Frontends migrated to financiera-web-service already send calculated
    # results. Persist them directly and avoid creating an Excel Online file.
    has_native_results = bool(
        payload_data.get("resultados")
        or payload_data.get("resultados_base")
        or payload_data.get("results")
    )
    if has_native_results and calc_type in (CalculationType.VALORA, CalculationType.KAPITAL):
        calculation = Calculation(
            user_id=payload.user_id,
            code=payload.code,
            type=calc_type,
            calculation_file_id=None,
            data=_normalize_calculation_data(payload_data=payload_data, file_meta=None),
        )
        db.add(calculation)
        db.commit()
        db.refresh(calculation)
        return CalculationResponse.model_validate(calculation)

    if calc_type in (CalculationType.VALORA, CalculationType.KAPITAL):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Este endpoint legacy fue migrado. Calcula usando financiera-web-service y persiste mediante la ruta nativa.",
        )


@router.post("/calculations/native", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
async def create_native_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):
    """Persiste resultados producidos por financiera-web-service en el flujo nativo."""
    calculation = Calculation(
        user_id=payload.user_id, code=payload.code, type=_to_calc_type(payload.type),
        calculation_file_id=None,
        data=_populate_native_template_values(
            dict(payload.data) if isinstance(payload.data, dict) else {},
            _to_calc_type(payload.type),
            db,
        ),
    )
    db.add(calculation)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.put("/calculations/{calculation_id}/native", response_model=CalculationResponse)
async def update_native_calculation(calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)):
    """Actualiza resultados nativos sin recalcular en Excel Online."""
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field in ("calculation_file_id", "user_id", "type"):
        if field in update_data:
            setattr(calculation, field, update_data[field])
    if "data" in update_data:
        calculation.data = _populate_native_template_values(
            update_data["data"], calculation.type, db
        )
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.put("/calculations/{calculation_id}", response_model=CalculationResponse)
async def update_calculation(
    calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)
):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)

    if "data" in update_data:
        native_data = update_data["data"]
        has_native_results = isinstance(native_data, dict) and bool(
            native_data.get("resultados")
            or native_data.get("resultados_base")
            or native_data.get("results")
        )
        if has_native_results and calculation.type in (
            CalculationType.VALORA,
            CalculationType.KAPITAL,
        ):
            calculation.data = _populate_native_template_values(
                native_data, calculation.type, db
            )
            db.commit()
            db.refresh(calculation)
            return CalculationResponse.model_validate(calculation)

        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Este endpoint legacy fue migrado. Usa /calculations/{id}/native para cálculos nativos.",
        )

    for key, value in update_data.items():
        setattr(calculation, key, value)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.post(
    "/calculations/{calculation_id}/refresh", response_model=CalculationResponse
)
async def refresh_calculation(
    calculation_id: int, payload: dict = Body({}), db: Session = Depends(get_db)
):
    """Refresh a calculation while preserving native calculations without Graph."""
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calculation.type != CalculationType.KAPITAL:
        return CalculationResponse.model_validate(calculation)

    native_data = calculation.data if isinstance(calculation.data, dict) else {}
    if not native_data.get("resultados"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="El refresh legacy fue eliminado. Este cálculo debe recrearse mediante el flujo nativo.",
        )

    latest_input = (native_data.get("inputs") or [{}])[-1]
    headers = {"X-API-Key": settings.WEB_SERVICE_API_KEY} if settings.WEB_SERVICE_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{settings.WEB_SERVICE_URL.rstrip('/')}/api/v1/kapital/calculate",
                json={"input": latest_input},
                headers=headers,
            )
            response.raise_for_status()
            native_result = response.json()
        base = native_result.get("base_results") or {}
        sensitivity = native_result.get("sensitivity_results") or []
        calculation.data = {
            **native_data,
            "inputs": [latest_input],
            "resultados": [{**(base.get("resultados") or {}), "inputs": latest_input}],
            "sensibilizacion": [
                {**(item.get("resultados") or {}), "inputs": item.get("inputs")}
                for item in sensitivity
            ],
        }
        db.commit()
        db.refresh(calculation)
        return CalculationResponse.model_validate(calculation)
    except httpx.HTTPError as exc:
        logger.exception("Native Kapital refresh failed: %s", exc)
        raise HTTPException(status_code=502, detail="Error recalculando Kapital en el servicio nativo") from exc


@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(calculation)
    db.commit()
    return None
