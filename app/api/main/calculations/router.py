# app/api/main/calculations_router.py
import os
import logging
import re
import json
import time
from datetime import datetime as _dt
from uuid import uuid4
from typing import Any, List, Optional
import httpx
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import select
from urllib.parse import quote
from app.db.database import get_db
from app.models.main import Calculation, CalculationType, TemplateComplement
from app.models.templates import MasterTemplate
from app.schemas.main import CalculationCreate, CalculationUpdate, CalculationResponse
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig


from .utils import (
    _extract_input_payload,
    _to_calc_type,
    _sanitize_input_for_history,
    _extract_latest_input_from_history,
    _enrich_payload_with_excel_outputs,
    _normalize_calculation_data,
    _inject_macro_data_into_payload,
    get_default_or_latest_master_template
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Calculations"])

# ==================== ENDPOINTS ====================

@router.get("/calculations", response_model=List[CalculationResponse])
def list_calculations(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Calculation)
    if user_id:
        query = query.where(Calculation.user_id == user_id)
    result = db.execute(query)
    calculations = result.scalars().all()
    return [CalculationResponse.model_validate(c) for c in calculations]

@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)

@router.get("/calculations/by-code/{code}", response_model=CalculationResponse)
def get_calculation_by_code(code: str, db: Session = Depends(get_db)):
    calculation = db.execute(
        select(Calculation).where(Calculation.code == code)
    ).scalars().first()

    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)

@router.post("/calculations", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
async def create_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):

    t_post = time.perf_counter()
    calc_type = _to_calc_type(payload.type)


    payload_data = dict(payload.data) if isinstance(payload.data, dict) else {}
    prewarmed_session_id = payload_data.pop("prewarmed_session_id", None)

    _inject_macro_data_into_payload(db, payload_data)

    # 1. OBTENER LA PLANTILLA MAESTRA DIRECTAMENTE (SIN CLONAR)
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Master template no configurada.")

    master_item_id = source_template.onedrive_item_id

    # 2. CALCULAR EN RAM
    if calc_type == CalculationType.KAPITAL:
        latest_input = _extract_input_payload(payload_data)
        include_sensibilizacion = latest_input.get("beta_desapalancado") is not None
        try:
            payload_data = await _enrich_payload_with_excel_outputs(
                payload_data,
                master_item_id, # Usamos el maestro como calculadora
                include_resultados=True,
                include_sensibilizacion=include_sensibilizacion,
                existing_session_id=prewarmed_session_id
            )
        except Exception as exc:
            logger.warning(f"Error procesando en RAM: {exc}")

    # GUARDAR EN BD
    t_db = time.perf_counter()
    calculation = Calculation(
        user_id=payload.user_id,
        code=payload.code,
        type=calc_type,
        #calculation_file_id=(file_meta.get("onedrive_item_id") or "")[:36] or None,
        #data=_normalize_calculation_data(payload_data, #file_meta=file_meta),
        calculation_file_id=None, 
        data=_normalize_calculation_data(payload_data),
    )

    db.add(calculation)
    db.commit()
    db.refresh(calculation)

    print(f"[TIMER] TIEMPO TOTAL DEL ENDPOINT POST: {time.perf_counter() - t_post:.2f} seg", flush=True)

    return CalculationResponse.model_validate(calculation)

@router.put("/calculations/{calculation_id}", response_model=CalculationResponse)
async def update_calculation(calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)


    if "data" in update_data:
        include_input_history = True
        include_resultados_history = True
        include_sensibilizacion_history = True
        base_changed = True
        only_boa_update = False

        _inject_macro_data_into_payload(db, update_data["data"])

        if calculation.type == CalculationType.KAPITAL:
            # 1. Obtenemos el ID de la plantilla maestra
            source_template = get_default_or_latest_master_template(db)
            if not source_template or not source_template.onedrive_item_id:
                raise HTTPException(status_code=400, detail="Master template no configurada.")

            master_item_id = source_template.onedrive_item_id

            incoming_input_raw = _extract_input_payload(update_data["data"])
            incoming_input_base = _sanitize_input_for_history(incoming_input_raw)
            current_input_base = _sanitize_input_for_history(
                _extract_latest_input_from_history(calculation.data)
            )
            has_beta_for_sensitivity = incoming_input_raw.get("beta_desapalancado") is not None
            base_changed = bool(incoming_input_base) and incoming_input_base != current_input_base


            #only_boa_update = has_beta_for_sensitivity and not base_changed

            include_input_history = True
            include_resultados_history = base_changed
            include_sensibilizacion_history = has_beta_for_sensitivity

            # Solo para pasar a la función de _enrich (si no hay base_changed, no se extraen resultados)
            only_boa_update = has_beta_for_sensitivity and not base_changed

            existing_session = None

            #  Prioridad: La sesión que acaba de mandar el frontend
            if isinstance(update_data["data"], dict) and update_data["data"].get("active_session_id"):
                existing_session = update_data["data"].get("active_session_id")

            # Si el frontend no mandó nada, intentamos usar la de la BD
            elif isinstance(calculation.data, dict) and calculation.data.get("active_session_id"):
                existing_session = calculation.data.get("active_session_id")
            try:
                t_put = time.perf_counter()
                update_data["data"] = await _enrich_payload_with_excel_outputs(
                    update_data["data"],
                    master_item_id,
                    include_resultados=base_changed,
                    include_sensibilizacion=has_beta_for_sensitivity,
                    existing_session_id=existing_session
                )
                print(f"[TIMER] TIEMPO TOTAL DEL ENDPOINT PUT: {time.perf_counter() - t_put:.2f} seg", flush=True)
            except (HTTPException, ValueError, TypeError, RuntimeError, httpx.TimeoutException, httpx.HTTPError) as exc:
                logger.warning("Could not enrich kapital update payload from Excel: %s", exc)

        update_data["data"] = _normalize_calculation_data(
            payload_data=update_data["data"],
            existing_data=calculation.data,
            include_input_history=include_input_history,
            include_resultados_history=include_resultados_history,
            include_sensibilizacion_history=include_sensibilizacion_history,
        )

        if isinstance(update_data["data"], dict) and "active_session_id" not in update_data["data"]:
            update_data["data"]["active_session_id"] = existing_session

    for key, value in update_data.items():
        setattr(calculation, key, value)
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
            source_template.onedrive_item_id, 
            persist_changes=False
        )
        return {"session_id": session_id}
    except Exception as e:
        logger.error(f"Error en pre-warm: {e}")
        raise HTTPException(status_code=500, detail="No se pudo pre-calentar la sesión de Excel")


@router.post("/calculations/prewarm/keep-alive", status_code=status.HTTP_200_OK)
async def keep_alive_excel_session(
    session_id: str = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Mantiene viva una sesión de Excel previamente pre-calentada."""
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        return {"status": "ignored"}

    service = get_onedrive_service()
    await service._refresh_workbook_session(source_template.onedrive_item_id, session_id)
    return {"status": "refreshed"}
