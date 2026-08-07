# app/api/main/calculations_router.py
import logging
import time
import traceback
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
from app.services.onedrive.service import get_onedrive_service

from .excel_engine import (
    _enrich_payload_with_excel_outputs,
    _enrich_payload_with_valora_excel,
    _extract_input_payload,
)
from .graphs import _generate_calculation_images
from .macros_service import (
    _clone_default_template_for_calculation,
    _enrich_input_with_macros,
    _inject_macro_data_into_payload,
    get_default_or_latest_master_template,
)
from .payload_manager import (
    _extract_latest_input_from_history,
    _normalize_calculation_data,
    _sanitize_input_for_history,
    _to_calc_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Calculations"])

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

    t_macro = time.perf_counter()
    _inject_macro_data_into_payload(db, payload_data)
    print(f"[TIMER] POST macro injection: {time.perf_counter() - t_macro:.3f} seg", flush=True)

    # 1. OBTENER LA PLANTILLA MAESTRA DIRECTAMENTE
    t_template = time.perf_counter()
    source_template = get_default_or_latest_master_template(db)
    print(f"[TIMER] POST get template: {time.perf_counter() - t_template:.3f} seg", flush=True)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Master template no configurada.")

    master_item_id = source_template.onedrive_item_id
    calculation_file_meta = None

<<<<<<< HEAD
    if calc_type == CalculationType.VALORA:
        # PRUEBAS: usar directamente la plantilla maestra subida en lugar de
        # crear una copia de trabajo de Valora. Luego podemos reactivar este
        # bloque para volver al flujo aislado por copia.
        # try:
        #     calculation_file_meta = await _clone_default_template_for_calculation(
        #         db, calc_type
        #     )
        #     master_item_id = calculation_file_meta["onedrive_item_id"]
        # except HTTPException:
        #     raise
        # except Exception as exc:
        #     logger.exception("No se pudo crear la copia de trabajo de Valora")
        #     raise HTTPException(
        #         status_code=status.HTTP_502_BAD_GATEWAY,
        #         detail="No se pudo crear la copia de trabajo de Valora",
        #     ) from exc
        pass
=======
    if calc_type in (CalculationType.VALORA, CalculationType.KAPITAL):
        try:
            calculation_file_meta = await _clone_default_template_for_calculation(
                db, calc_type
            )
            master_item_id = calculation_file_meta["onedrive_item_id"]
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"No se pudo crear la copia de trabajo de {calc_type.value}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"No se pudo crear la copia de trabajo de {calc_type.value}",
            ) from exc
>>>>>>> 8510b7a (feat: delete empresa BVL + estabilización cálculo Excel (Valora/Kapital))

    # 2. CALCULAR EN RAM
    if calc_type == CalculationType.KAPITAL:
        latest_input = _extract_input_payload(payload_data)
        
        # Preparar input de sensibilización
        sensitivity_input = None
        has_beta = latest_input.get("beta_desapalancado") is not None
        has_sens_subsector = bool(latest_input.get("subsector_sensibilizacion"))
        has_sens_industry = bool(latest_input.get("industria_sensibilizacion"))

        if has_beta or has_sens_subsector or has_sens_industry:
            sensitivity_input = dict(latest_input)
            if has_sens_industry:
                sensitivity_input["industria"] = latest_input.get("industria_sensibilizacion")
            if has_sens_subsector:
                sensitivity_input["subsector"] = latest_input.get("subsector_sensibilizacion")
            
            t_sens_macro = time.perf_counter()
            _enrich_input_with_macros(db, sensitivity_input)
            print(f"[TIMER] POST sensitivity macro enrichment: {time.perf_counter() - t_sens_macro:.3f} seg", flush=True)
            
            if has_beta:
                if "damodaran" not in sensitivity_input or not isinstance(sensitivity_input["damodaran"], dict):
                    sensitivity_input["damodaran"] = {}
                sensitivity_input["damodaran"]["beta"] = latest_input.get("beta_desapalancado")

        include_sensibilizacion = sensitivity_input is not None
        t_excel = time.perf_counter()
        try:
            payload_data = await _enrich_payload_with_excel_outputs(
                payload_data,
                master_item_id,
                include_resultados=True,
                include_sensibilizacion=include_sensibilizacion,
                existing_session_id=None,
                sensitivity_input=sensitivity_input
            )
        except Exception as exc:
            logger.warning(f"Error procesando en RAM: {exc}")
        print(f"[TIMER] POST Excel enrichment total: {time.perf_counter() - t_excel:.3f} seg", flush=True)

    elif calc_type == CalculationType.VALORA:
        t_excel = time.perf_counter()
        try:
            payload_data = await _enrich_payload_with_valora_excel(
                payload_data,
                master_item_id,
                existing_session_id=None,
            )
        except Exception as exc:
            logger.exception(f"Error procesando Valora en RAM: {exc}")
        print(f"[TIMER] POST Excel Valora enrichment total: {time.perf_counter() - t_excel:.3f} seg", flush=True)

    # GUARDAR EN BD
    t_db = time.perf_counter()
    calculation = Calculation(
        user_id=payload.user_id,
        code=payload.code,
        type=calc_type,
        calculation_file_id=None,
        data=_normalize_calculation_data(
            payload_data=payload_data,
            file_meta=calculation_file_meta,
        ),
    )

    db.add(calculation)
    db.commit()
    db.refresh(calculation)
    print(f"[TIMER] POST DB save: {time.perf_counter() - t_db:.3f} seg", flush=True)

    print(
        f"[TIMER] TIEMPO TOTAL DEL ENDPOINT POST: {time.perf_counter() - t_post:.2f} seg",
        flush=True,
    )

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
        include_input_history = True
        include_resultados_history = True
        include_sensibilizacion_history = True
        base_changed = True
        enriched_sensibilizacion = None
        has_beta_for_sensitivity = False
        calculation_file_meta = None
        existing_session = None

        t_macro = time.perf_counter()
        _inject_macro_data_into_payload(db, update_data["data"])
        print(f"[TIMER] PUT macro injection: {time.perf_counter() - t_macro:.3f} seg", flush=True)

        if calculation.type == CalculationType.KAPITAL:
            # 1. Obtenemos el ID de la plantilla maestra
            t_template = time.perf_counter()
            source_template = get_default_or_latest_master_template(db)
            print(f"[TIMER] PUT get template: {time.perf_counter() - t_template:.3f} seg", flush=True)
            if not source_template or not source_template.onedrive_item_id:
                raise HTTPException(
                    status_code=400, detail="Master template no configurada."
                )

            master_item_id = source_template.onedrive_item_id

            incoming_input_raw = _extract_input_payload(update_data["data"])
            current_input_raw = _extract_latest_input_from_history(calculation.data)
            
            incoming_input_base = _sanitize_input_for_history(incoming_input_raw)
            current_input_base = _sanitize_input_for_history(current_input_raw)

            # Detectar si cambió el sector/subsector principal
            main_sector_changed = (
                incoming_input_raw.get("industria") != current_input_raw.get("industria") or
                incoming_input_raw.get("subsector") != current_input_raw.get("subsector")
            )

            # Preparar input de sensibilidad si existen los campos o si el sector principal cambió
            sensitivity_input = None
            has_beta = incoming_input_raw.get("beta_desapalancado") is not None
            has_sens_subsector = bool(incoming_input_raw.get("subsector_sensibilizacion"))
            has_sens_industry = bool(incoming_input_raw.get("industria_sensibilizacion"))

            if has_beta or has_sens_subsector or has_sens_industry or main_sector_changed:
                sensitivity_input = dict(incoming_input_raw)
                
                # Si el cambio viene por industria/subsector principal, lo usamos para la sensibilidad
                if main_sector_changed and not has_sens_industry:
                    sensitivity_input["industria"] = incoming_input_raw.get("industria")
                elif has_sens_industry:
                    sensitivity_input["industria"] = incoming_input_raw.get("industria_sensibilizacion")

                if main_sector_changed and not has_sens_subsector:
                    sensitivity_input["subsector"] = incoming_input_raw.get("subsector")
                elif has_sens_subsector:
                    sensitivity_input["subsector"] = incoming_input_raw.get("subsector_sensibilizacion")
                
                # Enriquecer con macros
                t_sens_macro = time.perf_counter()
                _enrich_input_with_macros(db, sensitivity_input)
                print(f"[TIMER] PUT sensitivity macro enrichment: {time.perf_counter() - t_sens_macro:.3f} seg", flush=True)
                
                # Override beta
                if has_beta:
                    if "damodaran" not in sensitivity_input or not isinstance(sensitivity_input["damodaran"], dict):
                        sensitivity_input["damodaran"] = {}
                    sensitivity_input["damodaran"]["beta"] = incoming_input_raw.get("beta_desapalancado")
                elif main_sector_changed and not has_beta:
                    # Si cambió el sector principal, el BOA de esa sensibilidad debe ser el BOA calculado por Damodaran
                    # El valor de 'beta' ya fue inyectado por _enrich_input_with_macros arriba
                    pass

            has_beta_for_sensitivity = sensitivity_input is not None

            # Un cambio base solo ocurre si los parámetros financieros cambian Y el sector sigue siendo el mismo.
            # Si el sector cambió, forzamos que se trate como una sensibilización y no como un cambio en el cálculo principal.
            base_changed = (
                bool(incoming_input_base) and 
                incoming_input_base != current_input_base and 
                not main_sector_changed
            )
            
            include_input_history = base_changed
            include_resultados_history = base_changed
            include_sensibilizacion_history = has_beta_for_sensitivity

            existing_session = None

            #  Prioridad: La sesión que acaba de mandar el frontend
            if isinstance(update_data["data"], dict) and update_data["data"].get(
                "active_session_id"
            ):
                existing_session = update_data["data"].get("active_session_id")

            # Si el frontend no mandó nada, intentamos usar la de la BD
            elif isinstance(calculation.data, dict) and calculation.data.get(
                "active_session_id"
            ):
                existing_session = calculation.data.get("active_session_id")
            try:
                t_put = time.perf_counter()
                t_excel = time.perf_counter()
                update_data["data"] = await _enrich_payload_with_excel_outputs(
                    update_data["data"],
                    master_item_id,
                    include_resultados=base_changed,
                    include_sensibilizacion=has_beta_for_sensitivity,
                    existing_session_id=existing_session,
                    sensitivity_input=sensitivity_input
                )
                print(f"[TIMER] PUT Excel enrichment total: {time.perf_counter() - t_excel:.3f} seg", flush=True)
                if isinstance(update_data["data"], dict):
                    enriched_sensibilizacion = update_data["data"].get(
                        "sensibilizacion"
                    )
                print(
                    f"[TIMER] TIEMPO TOTAL DEL ENDPOINT PUT: {time.perf_counter() - t_put:.2f} seg",
                    flush=True,
                )
            except (
                HTTPException,
                ValueError,
                TypeError,
                RuntimeError,
                httpx.TimeoutException,
                httpx.HTTPError,
            ) as exc:
                logger.warning(
                    "Could not enrich kapital update payload from Excel: %s", exc
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="No se pudo recalcular el cálculo Kapital en Excel",
                ) from exc

        elif calculation.type == CalculationType.VALORA:
            source_template = get_default_or_latest_master_template(db)
            if source_template and source_template.onedrive_item_id:
                current_file = (
                    calculation.data.get("file")
                    if isinstance(calculation.data, dict)
                    and isinstance(calculation.data.get("file"), dict)
                    else None
                )
                workbook_item_id = (
                    current_file.get("onedrive_item_id") if current_file else None
                )

                if not workbook_item_id:
                    calculation_file_meta = (
                        await _clone_default_template_for_calculation(
                            db, CalculationType.VALORA
                        )
                    )
                    workbook_item_id = calculation_file_meta["onedrive_item_id"]
                elif isinstance(update_data["data"], dict) and update_data["data"].get(
                    "active_session_id"
                ):
                    existing_session = update_data["data"].get("active_session_id")
                elif isinstance(calculation.data, dict) and calculation.data.get(
                    "active_session_id"
                ):
                    existing_session = calculation.data.get("active_session_id")

                try:
                    update_data["data"] = await _enrich_payload_with_valora_excel(
                        update_data["data"],
                        workbook_item_id,
                        existing_session_id=existing_session,
                    )
                except Exception as exc:
                    logger.exception(
                        "Could not enrich valora update payload from Excel"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="No se pudo recalcular Valora en su copia de trabajo",
                    ) from exc

        update_data["data"] = _normalize_calculation_data(
            payload_data=update_data["data"],
            existing_data=calculation.data,
            file_meta=calculation_file_meta,
            include_input_history=include_input_history,
            include_resultados_history=include_resultados_history,
            include_sensibilizacion_history=include_sensibilizacion_history,
        )

        if has_beta_for_sensitivity and isinstance(update_data["data"], dict):
            if not update_data["data"].get("sensibilizacion") and isinstance(
                enriched_sensibilizacion, list
            ):
                update_data["data"]["sensibilizacion"] = enriched_sensibilizacion

        if (
            isinstance(update_data["data"], dict)
            and "active_session_id" not in update_data["data"]
        ):
            update_data["data"]["active_session_id"] = existing_session

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
    """
    Sincroniza y recalcula el estado de la hoja de cálculo en OneDrive.
    Acepta un prewarmed_session_id para optimizar recursos de Microsoft Graph.
    """
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calculation.type != CalculationType.KAPITAL:
        return CalculationResponse.model_validate(calculation)

    latest_input = _extract_latest_input_from_history(calculation.data)
    if not latest_input:
        raise HTTPException(
            status_code=400, detail="No se encontraron inputs históricos"
        )

    # Recuperar el ID precalentado enviado por el cliente frontend
    prewarmed_session_id = payload.get("prewarmed_session_id")

    refresh_payload = {"inputs": [latest_input]}
    _inject_macro_data_into_payload(db, refresh_payload)

    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Plantilla maestra no configurada")

    # Preparar input de sensibilidad si existen los campos
    sensitivity_input = None
    has_beta = latest_input.get("beta_desapalancado") is not None
    has_sens_subsector = bool(latest_input.get("subsector_sensibilizacion"))
    has_sens_industry = bool(latest_input.get("industria_sensibilizacion"))

    if has_beta or has_sens_subsector or has_sens_industry:
        sensitivity_input = dict(latest_input)
        if has_sens_industry:
            sensitivity_input["industria"] = latest_input.get("industria_sensibilizacion")
        if has_sens_subsector:
            sensitivity_input["subsector"] = latest_input.get("subsector_sensibilizacion")
        
        # Enriquecer con macros
        _enrich_input_with_macros(db, sensitivity_input)
        
        # Override beta
        if has_beta:
            if "damodaran" not in sensitivity_input or not isinstance(sensitivity_input["damodaran"], dict):
                sensitivity_input["damodaran"] = {}
            sensitivity_input["damodaran"]["beta"] = latest_input.get("beta_desapalancado")

    try:
        # Enriquecer y forzar recálculo usando la sesión existente o creando una nueva
        enriched_data = await _enrich_payload_with_excel_outputs(
            payload_data=refresh_payload,
            item_id=source_template.onedrive_item_id,
            include_resultados=True,
            include_sensibilizacion=sensitivity_input is not None,
            existing_session_id=prewarmed_session_id,
            sensitivity_input=sensitivity_input
        )
    except Exception as exc:
        logger.error(f"Fallo durante la ejecución de actualización del Excel: {exc}")
        raise HTTPException(
            status_code=500, detail="Error de sincronización con el motor de cálculo"
        )

    # Mantener e inyectar el session id activo resultante para que lo herede el PDF posterior
    session_id_to_persist = (
        enriched_data.get("active_session_id") or prewarmed_session_id
    )

    calculation.data = _normalize_calculation_data(
        payload_data=enriched_data,
        existing_data=calculation.data,
        include_resultados_history=True,
        include_sensibilizacion_history=False,
    )

    if isinstance(calculation.data, dict):
        calculation.data["active_session_id"] = session_id_to_persist

    db.commit()
    db.refresh(calculation)

    return CalculationResponse.model_validate(calculation)


@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(calculation)
    db.commit()
    return None


@router.post("/calculations/prewarm", status_code=status.HTTP_200_OK)
async def prewarm_excel_session(db: Session = Depends(get_db)):
    """
    Abre una sesión volátil en RAM con la plantilla maestra de Excel.
    Devuelve el session_id para que el frontend lo use al hacer el cálculo real.
    """
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Master template no configurada.")

    service = get_onedrive_service()
    try:
        session_id = await service._create_workbook_session(
            source_template.onedrive_item_id, persist_changes=True
        )
        return {"session_id": session_id}
    except Exception as e:
        logger.error(f"Error en pre-warm: {e}")
        raise HTTPException(
            status_code=500, detail="No se pudo pre-calentar la sesión de Excel"
        )


@router.post("/calculations/prewarm/keep-alive", status_code=status.HTTP_200_OK)
async def keep_alive_excel_session(
    session_id: str = Body(..., embed=True), db: Session = Depends(get_db)
):
    """Mantiene viva una sesión de Excel previamente pre-calentada."""
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        return {"status": "ignored"}

    service = get_onedrive_service()
    await service._refresh_workbook_session(
        source_template.onedrive_item_id, session_id
    )
    return {"status": "refreshed"}
