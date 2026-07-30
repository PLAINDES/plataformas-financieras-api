# app/api/main/router.py
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.main import (
    AppConfiguration,
    Calculation,
    CalculationType,
    TemplateComplement,
)
from app.schemas.main import (
    AppConfigurationUpdate,
    TemplateComplementCreate,
    TemplateComplementResponse,
    TemplateComplementUpdate,
)
from app.core.config import settings
from app.core.constants import AWS_BASE_PREFIX
from app.services.aws_service import s3_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Main"])


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

    data_list = complement.data if isinstance(complement.data, list) else []

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

    merged_data = payload.data

    # Lógica de Merge si ya existe historial
    if old_records and payload.nombre in ["damodaran", "riesgo", "tax", "subsectores"]:
        old_record = old_records[0]  # El activo más reciente
        old_data = old_record.data if isinstance(old_record.data, list) else []
        new_data = payload.data if isinstance(payload.data, list) else []

        if payload.nombre == "subsectores":
            # Para subsectores, fusionar por sector y subsector, sin duplicados
            # La estructura de cada elemento es {"sector": "...", "subsector": "...", "empresas": [...], "empresas_boa": {...}}
            merged_dict = {}
            for item in old_data:
                # Normalizar claves
                sector = item.get("sector", "").strip() if item.get("sector") else ""
                subsector = item.get("subsector", "").strip() if item.get("subsector") else ""
                if sector and subsector:
                    merged_dict[(sector.lower(), subsector.lower())] = item
            for item in new_data:
                sector = item.get("sector", "").strip() if item.get("sector") else ""
                subsector = item.get("subsector", "").strip() if item.get("subsector") else ""
                if sector and subsector:
                    # Sobrescribir con nuevos datos si coincide sector y subsector
                    merged_dict[(sector.lower(), subsector.lower())] = item
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
