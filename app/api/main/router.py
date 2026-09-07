# app/api/main/router.py
import io
import asyncio
import base64
import logging
import os
import re
import uuid
import httpx
from datetime import datetime
from typing import Any, List, Optional

def _fix_text(s: Any) -> Any:
    if not isinstance(s, str) or not s:
        return s
    s = s.replace("AgencAPP", "Agencias").replace("TerapAPP", "Terapias").replace("memorAPP", "memorias")
    if "Ã" not in s and "Â" not in s:
        return s
    try:
        return s.encode("latin1").decode("utf-8")
    except Exception:
        return s

def _clean_mojibake(s: str | None) -> str | None:
    if not s or not isinstance(s, str):
        return s
    # Fix APP artefact from corrupted file
    s = s.replace("AgencAPP", "Agencias").replace("TerapAPP", "Terapias").replace("memorAPP", "memorias")
    # Remove soft hyphens
    s = s.replace("\xad", "")
    # Remove garbled check marks
    s = s.replace("\u00c5\u00a1", "\u00a1")  # Å¡ -> ¡
    # Direct double-encoded pairs (Ã + latin1 byte)
    s = s.replace("\u00c3\u00b3", "\u00f3")  # Ã³ -> ó
    s = s.replace("\u00c3\u00a1", "\u00e1")  # Ã¡ -> á
    s = s.replace("\u00c3\u00a9", "\u00e9")  # Ã© -> é
    s = s.replace("\u00c3\u00ad", "\u00ed")  # Ã­ -> í
    s = s.replace("\u00c3\u00ba", "\u00fa")  # Ãº -> ú
    s = s.replace("\u00c3\u00b1", "\u00f1")  # Ã± -> ñ
    s = s.replace("\u00c3\u00bc", "\u00fc")  # Ã¼ -> ü
    s = s.replace("\u00c3\u00b0", "\u00f0")  # Ã° -> ð
    # Triple-encoded: ÃÂ -> í
    s = s.replace("\u00c3\u00c2", "\u00ed")
    # Remaining latin1->utf8 pass
    if "\u00c3" in s or "\u00c2" in s:
        try:
            s = s.encode("latin1").decode("utf-8")
        except Exception:
            pass
    return s

def _fix_subsectores_data(data: Any) -> Any:
    if not isinstance(data, list):
        return data
    for item in data:
        if isinstance(item, dict):
            if item.get("sector"): item["sector"] = _clean_mojibake(item["sector"])
            if item.get("subsector"): item["subsector"] = _clean_mojibake(item["subsector"])
            # empresas are tickers, no fix
    return data

import pandas as pd
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.database import get_db
from app.models.main import (
    AppConfiguration,
    Calculation,
    CalculationType,
    TemplateComplement,
)
from app.models.user import User
from app.api.main.calculations.macros_service import get_default_or_latest_master_template
from app.schemas.main import (
    AppConfigurationUpdate,
    TemplateComplementCreate,
    TemplateComplementResponse,
    TemplateComplementUpdate,
)
from app.core.config import settings
from app.core.constants import AWS_BASE_PREFIX
from app.services.aws_service import s3_service

BVL_S3_FOLDER = "bvl_cotizacion"
BVL_MARKER_KEY = f"{AWS_BASE_PREFIX}{BVL_S3_FOLDER}/current.json"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Main"])


@router.post("/valora/calculate-excel")
async def calculate_valora_with_excel(payload: dict):
    """Proxy seguro al servicio Windows que ejecuta Excel COM."""
    input_data = dict(payload.get("input") or payload)
    aliases = {
        "date": "fecha", "country": "pais", "currency": "moneda",
        "industry": "sector", "kd": "costo_deuda", "debt": "porcentaje_deuda",
        "capital": "porcentaje_capital", "equity": "porcentaje_capital",
        "beta_unlevered_industry": "beta_desapalancado", "beta_subsector": "beta_desapalancado",
        "beta_subsector_custom": "beta_desapalancado", "beta_unlevered_sensitivity": "beta_desapalancado",
        "beta": "beta_desapalancado", "beta_unlevered": "beta_desapalancado",
        "bono": "anio_bono", "instrument": "tasa_libre_riesgo",
    }
    for source, target in aliases.items():
        if input_data.get(target) in (None, "") and input_data.get(source) not in (None, ""):
            input_data[target] = input_data[source]
    # sanitizar "" -> None y strings numericos -> float
    for key in ["costo_deuda","porcentaje_deuda","porcentaje_capital","beta_desapalancado","revenue_forecast_rate","fdc_forecast_rate","perpetual_growth_rate","tasa_libre_riesgo"]:
        v = input_data.get(key)
        if v == "":
            input_data[key] = None
        elif isinstance(v, str) and v.strip() not in ("", None):
            try:
                cleaned = v.replace(",", ".").replace("%", "").strip()
                # solo convierte si es numerico puro
                float(cleaned)
                input_data[key] = float(cleaned)
            except:
                pass
    # fecha 31/12/2024 -> 2024
    if isinstance(input_data.get("fecha"), str) and "/" in input_data["fecha"]:
        try:
            input_data["fecha"] = input_data["fecha"].strip().split("/")[-1]
        except:
            pass
    # sanitizar shares también
    for key in ["shares"]:
        v = input_data.get(key)
        if v == "":
            input_data[key] = None
        elif isinstance(v, str) and v.strip() not in ("", None):
            try:
                cleaned = v.replace(",", "").replace(" ", "").strip()
                input_data[key] = int(float(cleaned))
            except:
                pass
    # no filtrar agresivo: enviar todo lo no vacío, el web-service ignora extra con extra="ignore"
    # solo elimina "" y None para evitar 422, pero conserva tablas y todos los campos útiles
    input_data = {k: v for k, v in input_data.items() if v not in ("", None)}
    # preservar tablas aunque esten vacias pero con estructura (por si fueron filtradas por ser dict vacío)
    for tbl in ["balance_table","results_table"]:
        if tbl in (payload.get("input") or payload) and tbl not in input_data:
            # si viene del payload original, conservarlo
            orig = (payload.get("input") or payload).get(tbl)
            if orig is not None:
                input_data[tbl] = orig
    request_payload = {"input": input_data, "forecast_method": "ETS", "use_template": True, "return_details": True}
    url = f"{settings.WEB_SERVICE_URL.rstrip('/')}/api/v1/valora/calculate"
    headers = {"X-API-Key": settings.WEB_SERVICE_API_KEY} if settings.WEB_SERVICE_API_KEY else {}
    import json as _json
    logger.info(f"[PROXY] -> {url} payload_keys={list(input_data.keys())} payload={_json.dumps(request_payload)[:2000]}")
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=request_payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:2000]
        logger.error(
            f"[PROXY] upstream_status={exc.response.status_code} "
            f"from web-service: {detail} | payload_keys={list(input_data.keys())}"
        )
        raise HTTPException(status_code=502, detail=f"Excel service error: {detail}") from exc
    except httpx.HTTPError as exc:
        logger.error(f"[PROXY] HTTPError to web-service: {exc}")
        raise HTTPException(status_code=502, detail=f"Excel service unavailable: {exc}") from exc


@router.get("/internal/active-master-template")
def get_active_master_template(
    db: Session = Depends(get_db),
    api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Returns the admin-selected master workbook to the Windows Excel service."""
    configured_key = settings.WEB_SERVICE_API_KEY.strip()
    if not configured_key or api_key != configured_key:
        raise HTTPException(status_code=403, detail="Invalid internal service key")
    template = get_default_or_latest_master_template(db)
    if not template or not template.onedrive_item_id:
        raise HTTPException(status_code=404, detail="No active master template is available")
    return {
        "id": template.id,
        "name": template.nombre,
        "onedrive_item_id": template.onedrive_item_id,
        "filename": template.original_filename or template.onedrive_filename or "Valora_Template.xlsx",
    }


def _get_latest_calculation_by_user_and_type(
    db: Session, user_id: int, calc_type: CalculationType
) -> Calculation | None:
    return (
        db.execute(
            select(Calculation)
            .where(Calculation.user_id == user_id, Calculation.type == calc_type)
            .order_by(Calculation.updated_at.desc(), Calculation.id.desc())
        )
        .scalars()
        .first()
    )


@router.get("/health")
def main_health():
    return {"status": "ok"}


# ==================== TEMPLATE COMPLEMENTS ====================
@router.get("/template-complements", response_model=List[TemplateComplementResponse])
def list_template_complements(db: Session = Depends(get_db)):
    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()
    return [TemplateComplementResponse.model_validate(complement)] if complement else []


@router.get(
    "/template-complements/{complement_id}", response_model=TemplateComplementResponse
)
def get_template_complement_by_id(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    return TemplateComplementResponse.model_validate(complement)


@router.get("/template-complements/by-name/{complement_name}")
def get_template_complement(
    complement_name: str,
    only_name: bool = Query(False, alias="only-name"),
    only_date: bool = Query(False, alias="only-date"),
    country: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Any:

    if only_name and complement_name != "damodaran":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El query parameter 'only-name' es exclusivo para el complemento 'damodaran'.",
        )

    if only_date and complement_name != "rf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El query parameter 'only-date' es exclusivo para el complemento 'rf'.",
        )

    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.nombre == complement_name)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()

    if not complement:
        return []

    data_list = _fix_subsectores_data(complement.data) if complement_name == "subsectores" and isinstance(complement.data, list) else (complement.data if isinstance(complement.data, list) else [])

    # ==========================================
    # Extracción exacta de valor
    # ==========================================
    if country and year:
        # 1. Normalizar los parámetros que vienen de la URL
        search_year = str(year).replace(".0", "").strip()
        search_country = str(country).strip().lower()
        search_period = str(period).strip().upper() if period else None

        if complement_name == "ir":
            for item in data_list:
                # 2. Normalizar la data que viene de la BD (Excel)
                db_fecha = str(item.get("fecha", "")).replace(".0", "").strip()
                db_pais = str(item.get("pais", "")).strip().lower()

                if db_fecha == search_year and db_pais == search_country:
                    return {"valor": item.get("valor")}
            return {"valor": None}

        if complement_name == "devaluacion" and search_period:
            for item in data_list:
                db_fecha = str(item.get("fecha", "")).replace(".0", "").strip()
                db_periodo = str(item.get("periodo", "")).strip().upper()

                if db_fecha == search_year and db_periodo == search_period:
                    # Buscar la llave del país ignorando mayúsculas y espacios
                    country_key = next(
                        (
                            k
                            for k in item.keys()
                            if str(k).strip().lower() == search_country
                        ),
                        None,
                    )
                    if country_key:
                        return {"valor": item.get(country_key)}

            # Si termina el bucle y no hay match
            return {"valor": None}

    # =====================
    # Lógica Existente
    # =====================
    if only_name:
        # 1. Extraer y limpiar espacios en blanco a los lados
        industrias_crudas = [
            str(item.get("industria")).strip()
            for item in data_list
            if isinstance(item, dict) and item.get("industria")
        ]
        # 2. Eliminar los duplicados (por los años) y ordenar alfabéticamente
        return sorted(list(set(industrias_crudas)))

    if only_date:
        fechas_crudas = [
            str(item.get("fecha")).strip()
            for item in data_list
            if isinstance(item, dict) and item.get("fecha")
        ]
        fechas_unicas = list(set(fechas_crudas))

        def parse_date_for_sort(date_str):
            try:
                return datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                pass
            try:
                return datetime.strptime(date_str, "%Y")
            except ValueError:
                return datetime.min

        fechas_unicas.sort(key=parse_date_for_sort, reverse=True)
        return fechas_unicas

    return [TemplateComplementResponse.model_validate(complement)]


@router.post(
    "/template-complements",
    response_model=TemplateComplementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_complement(
    payload: TemplateComplementCreate, db: Session = Depends(get_db)
):
    """
    Creates a new complement. Soft-deletes any existing complement with the same nombre
    so that only one active record per nombre exists at a time.
    """
    # Soft-delete all previous records with the same nombre
    old_records = (
        db.execute(
            select(TemplateComplement)
            .where(TemplateComplement.nombre == payload.nombre)
            .where(TemplateComplement.deleted_at.is_(None))
            .order_by(TemplateComplement.created_at.desc())
        )
        .scalars()
        .all()
    )

    # Fix mojibake en payload antes de merge
    if payload.nombre == "subsectores" and isinstance(payload.data, list):
        payload.data = _fix_subsectores_data(payload.data)
    merged_data = payload.data

    # Lógica de Merge si ya existe historial
    if old_records and payload.nombre in ["damodaran", "riesgo", "tax", "subsectores"]:
        old_record = old_records[0]  # El activo más reciente
        old_data = _fix_subsectores_data(old_record.data) if payload.nombre == "subsectores" and isinstance(old_record.data, list) else (old_record.data if isinstance(old_record.data, list) else [])
        new_data = payload.data if isinstance(payload.data, list) else []

        if payload.nombre == "subsectores":
            # Merge aditivo: añade empresas nuevas, actualiza BOA/ticker_info si ticker ya existe
            merged_dict: dict[tuple[str, str], dict] = {}
            for item in old_data:
                sector = _clean_mojibake(item.get("sector", "")).strip() if item.get("sector") else ""
                subsector = _clean_mojibake(item.get("subsector", "")).strip() if item.get("subsector") else ""
                if sector and subsector:
                    # clone to avoid mutating old
                    merged_dict[(sector.lower(), subsector.lower())] = dict(item)
                    merged_dict[(sector.lower(), subsector.lower())]["sector"] = sector
                    merged_dict[(sector.lower(), subsector.lower())]["subsector"] = subsector
            for item in new_data:
                sector = _clean_mojibake(item.get("sector", "")).strip() if item.get("sector") else ""
                subsector = _clean_mojibake(item.get("subsector", "")).strip() if item.get("subsector") else ""
                if not (sector and subsector):
                    continue
                key = (sector.lower(), subsector.lower())
                if key in merged_dict:
                    existing = merged_dict[key]
                    # Une empresas sin duplicar
                    old_emps = existing.get("empresas") or []
                    new_emps = item.get("empresas") or []
                    merged_emps = list(dict.fromkeys([*(e.strip() for e in old_emps if e), *(e.strip() for e in new_emps if e)]))
                    existing["empresas"] = merged_emps
                    # Actualiza BOA/ticker_info si vienen
                    if item.get("empresas_boa"):
                        existing["empresas_boa"] = {**(existing.get("empresas_boa") or {}), **item["empresas_boa"]}
                    if item.get("ticker_info"):
                        existing["ticker_info"] = {**(existing.get("ticker_info") or {}), **item["ticker_info"]}
                    # otros campos del nuevo pisan
                    for k, v in item.items():
                        if k not in ("empresas", "empresas_boa", "ticker_info"):
                            existing[k] = v
                    existing["sector"] = sector
                    existing["subsector"] = subsector
                else:
                    merged_dict[key] = dict(item)
                    merged_dict[key]["sector"] = sector
                    merged_dict[key]["subsector"] = subsector
            merged_data = list(merged_dict.values())
        else:
            # Extraer los años que vienen en el nuevo Excel para no duplicarlos
            incoming_years = {
                str(item.get("fecha")) for item in new_data if item.get("fecha")
            }

            # Retener solo los datos del JSON antiguo que NO correspondan a los años subidos
            # (Esto permite actualizar un año si se vuelve a subir)
            retained_data = [
                item for item in old_data if str(item.get("fecha")) not in incoming_years
            ]

            # Combinar el historial retenido con la nueva carga
            merged_data = retained_data + new_data

    # Guard: si el merge produce vacío, NO borrar lo que ya existe
    if not merged_data and old_records and payload.nombre == "subsectores":
        return TemplateComplementResponse.model_validate(old_records[0])

    # Marcar como eliminados lógicamente los registros anteriores
    for old in old_records:
        old.deleted_at = datetime.utcnow()

    # Inyectar la data fusionada en el payload antes de guardar
    payload_dict = payload.model_dump()
    payload_dict["data"] = merged_data

    complement = TemplateComplement(**payload_dict)
    db.add(complement)
    db.commit()
    db.refresh(complement)

    return TemplateComplementResponse.model_validate(complement)


@router.put(
    "/template-complements/{complement_id}", response_model=TemplateComplementResponse
)
def update_template_complement(
    complement_id: int, payload: TemplateComplementUpdate, db: Session = Depends(get_db)
):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(complement, key, value)
    db.commit()
    db.refresh(complement)
    return TemplateComplementResponse.model_validate(complement)


@router.delete(
    "/template-complements/{complement_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_template_complement(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    complement.deleted_at = datetime.utcnow()
    db.commit()
    return None


@router.delete(
    "/template-complements/by-name/{complement_name}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_template_complement_by_name(complement_name: str, db: Session = Depends(get_db)):
    complements = (
        db.execute(
            select(TemplateComplement)
            .where(TemplateComplement.nombre == complement_name)
            .where(TemplateComplement.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )
    if not complements:
        raise HTTPException(status_code=404, detail="Template complement not found")
    for comp in complements:
        comp.deleted_at = datetime.utcnow()
    db.commit()
    return None


# ==================== APP CONFIGURATIONS ====================


@router.get("/settings/{module}", response_model=dict)
def get_app_settings(module: str, db: Session = Depends(get_db)):
    """
    Obtiene la configuración de un módulo en formato JSON.
    """
    config = (
        db.execute(select(AppConfiguration).where(AppConfiguration.module == module))
        .scalars()
        .first()
    )

    if not config:
        # Valores por defecto inyectados si la tabla está vacía
        if module == "kapital":
            return {"max_sensibilizaciones": 3}
        return {}

    return config.settings


@router.patch("/settings/{module}", response_model=dict)
def update_app_settings(
    module: str, payload: AppConfigurationUpdate, db: Session = Depends(get_db)
):
    """
    Crea o actualiza la configuración JSON de un módulo.
    """
    config = (
        db.execute(select(AppConfiguration).where(AppConfiguration.module == module))
        .scalars()
        .first()
    )

    if config:
        # Se genera un nuevo diccionario en memoria utilizando dict()
        current_settings = dict(config.settings or {})
        current_settings.update(payload.settings)
        config.settings = current_settings
    else:
        # Si es la primera vez que se guarda, creamos el registro
        config = AppConfiguration(module=module, settings=payload.settings)
        db.add(config)

    db.commit()
    db.refresh(config)

    return config.settings


# ==================== VALORA TEMPLATE ====================

VALORA_S3_FOLDER = "templates/valora-eeff"
VALORA_MAX_FILES = 10
VALORA_CURRENT_MARKER_KEY = f"{AWS_BASE_PREFIX}/{VALORA_S3_FOLDER}/_current.json"


def _build_valora_file_url(object_key: str) -> str:
    region = settings.AWS_REGION_NAME
    return f"https://{settings.AWS_BUCKET_NAME}.s3.{region}.amazonaws.com/{object_key}"


def _get_current_valora_key() -> str | None:
    """Lee el marker JSON para saber cuál archivo es el actual."""
    data = s3_service.get_json_object(VALORA_CURRENT_MARKER_KEY)
    return data.get("current_object_key") if data else None


def _set_current_valora_key(object_key: str) -> bool:
    """Escribe el marker JSON con el archivo actual."""
    return s3_service.put_json_object(VALORA_CURRENT_MARKER_KEY, {"current_object_key": object_key})
def _list_valora_templates() -> list[dict]:
    """Lista las plantillas de Valora desde S3, ordenadas por fecha (más reciente primero)."""
    prefix = f"{AWS_BASE_PREFIX}/{VALORA_S3_FOLDER}/"
    files = s3_service.list_files(prefix)
    # Ordenar por fecha descendente (más reciente primero)
    files.sort(key=lambda x: x["last_modified"], reverse=True)

    current_key = _get_current_valora_key()
    templates = []
    for f in files:
        key = f["object_key"]
        filename = key.split("/")[-1]
        # Saltar archivos del sistema
        if filename.startswith("_"):
            continue

        # El original_name está codificado en el filename: timestamp__original_name.ext
        if "__" in filename:
            original_name = filename.split("__", 1)[1]
        else:
            original_name = filename

        templates.append({
            "url": _build_valora_file_url(key),
            "filename": filename,
            "original_name": original_name,
            "last_modified": f["last_modified"].isoformat(),
            "object_key": key,
            "is_current": key == current_key,
        })
    return templates


@router.get("/valora-template")
def get_valora_template():
    """
    Retorna el historial de plantillas de estados financieros de Valora desde S3.
    """
    templates = _list_valora_templates()
    return {"templates": templates}


@router.post("/valora-template/upload", status_code=status.HTTP_200_OK)
async def upload_valora_template(file: UploadFile = File(...)):
    """
    Sube una nueva plantilla Excel para los estados financieros de Valora.
    Mantiene máximo 10 archivos en S3; si hay 10, elimina el más antiguo.
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó ningún archivo.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".xlsx", ".xls"]:
        raise HTTPException(
            status_code=400, detail="Solo se permiten archivos Excel (.xlsx, .xls)"
        )

    # Verificar cuántos archivos hay antes de subir
    existing = _list_valora_templates()
    if len(existing) >= VALORA_MAX_FILES:
        # Eliminar el más antiguo (último de la lista porque está ordenada descendente)
        oldest = existing[-1]
        s3_service.delete_file(oldest["object_key"])

    # Generar nombre único: timestamp__original_name.ext
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_original = os.path.basename(file.filename).replace(" ", "_")
    unique_filename = f"{timestamp}__{safe_original}"

    try:
        s3_result = s3_service.upload_file(
            file, folder=VALORA_S3_FOLDER, custom_filename=unique_filename
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error subiendo archivo a AWS S3: {str(e)}"
        )

    # La plantilla recién subida siempre es la actual por defecto
    _set_current_valora_key(s3_result["object_key"])

    # Retornar el historial actualizado
    updated_templates = _list_valora_templates()
    return {"templates": updated_templates}


@router.post("/valora-template/set-default", status_code=status.HTTP_200_OK)
def set_default_valora_template(payload: dict):
    """
    Marca una plantilla del historial como la actual (predeterminada).
    Solo actualiza el marker JSON _current.json, no modifica el archivo.
    """
    object_key = payload.get("object_key")
    if not object_key:
        raise HTTPException(status_code=400, detail="No se proporcionó object_key.")

    # Verificar que el archivo existe
    existing = _list_valora_templates()
    if not any(t["object_key"] == object_key for t in existing):
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en S3.")

    # Actualizar el marker
    if not _set_current_valora_key(object_key):
        raise HTTPException(status_code=400, detail="Error actualizando el marker en S3.")

    # Retornar historial actualizado
    updated_templates = _list_valora_templates()
    return {"templates": updated_templates}


# === BVL COTIZACIÓN ==========================================================


class BvlCotizacionItem(BaseModel):
    empresa: str
    id: str
    numero_acciones: Optional[float]
    capitalizacion_bursatil: Optional[float]
    valor_por_accion: Optional[float]


class BvlCotizacionResponse(BaseModel):
    items: list[BvlCotizacionItem]


class BvlDeletePayload(BaseModel):
    empresa: str
    id: str


def _parse_number_peruvian(value) -> Optional[float]:
    """Convierte strings como 'S/502,731,591' o '1,196,979,979' a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Quitar prefijo de moneda
    s = re.sub(r"^[A-Z]{2,3}\s*", "", s)
    # Quitar separadores de miles
    s = s.replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _dataframe_to_bvl_items(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    col_map = {}
    for col in df.columns:
        col_norm = str(col).strip().lower().replace(" ", "_")
        if col_norm in ("empresa", "company", "nombre"):
            col_map[col] = "empresa"
        elif col_norm in ("id", "ticker", "código", "codigo"):
            col_map[col] = "id"
        elif col_norm in (
            "n._de_acciones",
            "n_de_acciones",
            "número_de_acciones",
            "numero_de_acciones",
            "acciones",
        ):
            col_map[col] = "numero_acciones"
        elif col_norm in (
            "capitalización_bursátil",
            "capitalizacion_bursatil",
            "capitalización",
            "capitalizacion",
        ):
            col_map[col] = "capitalizacion_bursatil"
        elif col_norm in ("valor_por_accion", "valor_por_acción", "precio", "valor"):
            col_map[col] = "valor_por_accion"
    df = df.rename(columns=col_map)

    required = {"empresa", "id"}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan columnas requeridas: {', '.join(missing)}. "
            "Columnas detectadas: " + ", ".join(str(c) for c in df.columns),
        )

    items = []
    for _, row in df.iterrows():
        empresa = str(row.get("empresa", "")).strip()
        id_val = str(row.get("id", "")).strip()
        if not empresa or not id_val:
            continue
        items.append(
            {
                "empresa": empresa,
                "id": id_val,
                "numero_acciones": _parse_number_peruvian(row.get("numero_acciones")),
                "capitalizacion_bursatil": _parse_number_peruvian(
                    row.get("capitalizacion_bursatil")
                ),
                "valor_por_accion": _parse_number_peruvian(row.get("valor_por_accion")),
            }
        )
    return items


@router.get("/bvl-cotizacion", response_model=BvlCotizacionResponse)
def get_bvl_cotizacion():
    data = s3_service.get_json_object(BVL_MARKER_KEY)
    if not data:
        return {"items": []}
    items = data.get("items", [])
    return {"items": items}


@router.post("/bvl-cotizacion/upload", response_model=BvlCotizacionResponse)
async def upload_bvl_cotizacion(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin),
):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó ningún archivo.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".xlsx", ".xls", ".csv"]:
        raise HTTPException(
            status_code=400, detail="Solo se permiten archivos Excel o CSV"
        )

    content = await file.read()
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"No se pudo leer el archivo: {e}"
        ) from e

    items = _dataframe_to_bvl_items(df)

    s3_service.put_json_object(
        BVL_MARKER_KEY,
        {"items": items, "updated_at": datetime.utcnow().isoformat()},
    )

    return {"items": items}


@router.post("/valora/pdf-to-template")
async def valora_pdf_to_template(file: UploadFile = File(...)):
    """
    Convierte EEFF PDF a plantilla Valora usando IA (Gemini + Prompt Maestro 51 reglas).
    Retorna balance_table/results_table listos para hidratar el frontend.
    """
    logger.info(f"[VALORA PDF] >>> POST recibido: {file.filename} size={file.size if hasattr(file, 'size') else 'unknown'}")
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó archivo PDF")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo PDF permitido")
    content = await file.read()
    logger.info(f"[VALORA PDF] Bytes leídos: {len(content)} - iniciando extracción")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF supera 10MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="PDF vacío")
    try:
        from app.services.valora.pdf_extractor import pdf_to_template
        logger.info("[VALORA PDF] Llamando a pdf_to_template (IA)...")
        result = await pdf_to_template(content)
        template_key = _get_current_valora_key()
        if not template_key:
            raise RuntimeError("No hay una plantilla Valora vigente configurada")
        template_bytes = s3_service.download_file_bytes(template_key)
        from app.services.valora.template_filler import fill_valora_template

        filled_bytes = await asyncio.to_thread(
            fill_valora_template,
            template_bytes,
            result,
        )
        logger.info(f"[VALORA PDF] <<< Completado status={result.get('status')} model={result.get('model_used')}")
        filename = f"{result.get('metadata', {}).get('empresa', 'EEFF').replace(' ', '_')}_rellenado.xlsx"
        return {**result, "xlsx_base64": base64.b64encode(filled_bytes).decode("ascii"), "filename": filename}
    except ValueError as e:
        logger.warning(f"[VALORA PDF] ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[VALORA PDF] RuntimeError: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception(f"[VALORA PDF] Error: {e}")
        raise HTTPException(status_code=500, detail="Error procesando PDF con IA")

@router.delete("/bvl-cotizacion/empresa", response_model=BvlCotizacionResponse)
async def delete_bvl_empresa(
    payload: BvlDeletePayload,
    current_user: User = Depends(get_current_admin),
):
    data = s3_service.get_json_object(BVL_MARKER_KEY)
    items = data.get("items", []) if data else []
    filtered = [
        item for item in items
        if not (item.get("empresa") == payload.empresa and item.get("id") == payload.id)
    ]

    if len(filtered) == len(items):
        raise HTTPException(status_code=404, detail="Empresa no encontrada en la cotización BVL.")

    s3_service.put_json_object(
        BVL_MARKER_KEY,
        {"items": filtered, "updated_at": datetime.utcnow().isoformat()},
    )

    return {"items": filtered}
