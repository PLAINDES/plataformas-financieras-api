from app.services.aws_service import s3_service
# app/api/main/master_templates_router.py
"""
CRUD de Plantillas Maestras + integración OneDrive + Extracción automática de Template Codes.
Cada plantilla maestra es un archivo Excel que define el modelo financiero.
Se sube a OneDrive y se extrae automáticamente los Template Codes de hojas específicas.
"""
import io
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
import openpyxl

from app.db.database import get_db
from app.api.deps import get_current_admin
from app.models.templates.master_templates import MasterTemplate
from app.models.main import TemplateCode
from app.models.templates import CalculationType
from app.models.cms import Media
from app.schemas.templates import (
    MasterTemplateCreate, MasterTemplateUpdate, MasterTemplateResponse,
    TemplateCodeResponse,
)
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig
from app.services.template_code_extractor import get_template_code_extractor
from app.services.template_code_utils import normalize_code
from app.services.libreoffice_chart_extractor_service import get_libreoffice_chart_extractor
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main/master-templates",
    tags=["Master Templates"],
    dependencies=[Depends(get_current_admin)],
)

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]


def _normalize_template_name(template_name: str) -> str:
    normalized = (template_name or "TEMPLATE").upper()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^A-Z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_") or "TEMPLATE"


# === CREATE ===================================================================
@router.post("", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_master_template(payload: MasterTemplateCreate, db: Session = Depends(get_db)):
    """
    Crea una nueva plantilla maestra (sin subir archivo).
    Para subir archivo y extraer códigos, usar POST /{template_id}/upload después.
    
    El nombre debe tener entre 3 y 255 caracteres.
    """
    # Validations
    if not payload.nombre or len(payload.nombre) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre debe tener al menos 3 caracteres"
        )
    if len(payload.nombre) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre no puede exceder 255 caracteres"
        )
    
    if payload.description and len(payload.description) > 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La descripción no puede exceder 1000 caracteres"
        )
    
    obj = MasterTemplate(
        nombre=payload.nombre.strip(),
        description=payload.description.strip() if payload.description else None,
        is_active=payload.is_active,
        hojas_config=payload.hojas_config,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


# === LIST ===================================================================
@router.get("", response_model=list[MasterTemplateResponse])
def list_master_templates(
    limit: int = 10,
    offset: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Lista plantillas maestras con paginación y búsqueda.
    
    Args:
        limit: Número de resultados (default: 10)
        offset: Desplazamiento inicial (default: 0)
        search: Término de búsqueda en nombre o descripción (opcional)
    
    Returns:
        Lista de plantillas maestras
    """
    query = select(MasterTemplate).where(MasterTemplate.deleted_at.is_(None))
    
    if search:
        search_term = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                MasterTemplate.nombre.ilike(search_term),
                MasterTemplate.description.ilike(search_term),
            )
        )
    
    query = query.order_by(MasterTemplate.created_at.desc())
    
    templates = db.execute(query.offset(offset).limit(limit)).scalars().all()
    return [MasterTemplateResponse.model_validate(t) for t in templates]


# === GENERIC ROUTES (AFTER SPECIFIC ROUTES) ===========================
# All /{template_id} routes and subroutes come last to avoid routing conflicts


# === GET ONE ==================================================================
@router.get("/{template_id}", response_model=MasterTemplateResponse)
def get_master_template(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    return MasterTemplateResponse.model_validate(obj)


# === UPDATE ===================================================================
@router.put("/{template_id}", response_model=MasterTemplateResponse)
def update_master_template(
    template_id: int, payload: MasterTemplateUpdate, db: Session = Depends(get_db)
):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


# === DELETE ===================================================================
@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_master_template(template_id: int, db: Session = Depends(get_db)):
    """
    Elimina una plantilla maestra (soft delete).
    
    IMPORTANTE: Esto solo marca la plantilla como eliminada en la BD.
    El archivo Excel en OneDrive NO se elimina automáticamente.
    Para eliminar archivos de OneDrive, usar DELETE /onedrive/files/{item_id}
    """
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    # Soft-delete media asociados a la plantilla
    media_rows = db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None))
            & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all()
    for media in media_rows:
        media.deleted_at = datetime.utcnow()

    # Soft-delete códigos asociados al archivo actual (celdas + charts de media)
    codes_to_soft_delete = set()

    for media in media_rows:
        if media.meta and media.meta.get("chart_code"):
            c = str(media.meta.get("chart_code")).replace("$$", "").upper()
            codes_to_soft_delete.add(f"$${c}$$")

    # Nota: no se descarga el Excel en este endpoint síncrono para evitar I/O async aquí.

    if codes_to_soft_delete:
        code_rows = db.execute(
            select(TemplateCode).where(
                (TemplateCode.deleted_at.is_(None))
                & (TemplateCode.code.in_(list(codes_to_soft_delete)))
            )
        ).scalars().all()
        for code_row in code_rows:
            code_row.deleted_at = datetime.utcnow()

    obj.deleted_at = datetime.utcnow()
    db.commit()
    return None


# === UPLOAD + AUTO EXTRACT CODES (AUTOMATIC PROCESS) ==========================
@router.post("/{template_id}/upload")
async def upload_and_extract_codes(
    template_id: int,
    file: UploadFile = File(...),
    folder: Folder = Form("plantillas_maestras"),
    db: Session = Depends(get_db),
):
    """
    Sube un archivo Excel a OneDrive y extrae automáticamente los Template Codes.
    
    El proceso es TOTALMENTE AUTOMÁTICO:
    1. Sube el archivo a OneDrive
    2. Extrae códigos de hojas ("Plantilla Usuario" -> VALORA, "WACC" -> KAPITAL)
    3. Guarda los códigos en BD
    4. Obtiene imágenes de gráficos desde Microsoft Graph API y las convierte a JPG
    5. Retorna los códigos extraídos + estadísticas
    
    El frontend solo presenta un modal con loader mientras se procesa.
    
    Form parameters:
      - file: archivo Excel .xlsx (máximo 10MB)
      - folder: plantillas_maestras | kapital | valora
    """
    # Validar tipo de archivo
    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo debe ser un Excel (.xlsx o .xls)"
        )
    
    # Validar tamaño del archivo (máximo 10MB)
    file_size = 0
    content = await file.read()
    file_size = len(content)
    
    if file_size > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El archivo no puede exceder 10MB"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo está vacío"
        )

    env: Environment = settings.ENVIRONMENT
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )

    # 1. SUBIR ARCHIVO A ONEDRIVE
    filename = file.filename or f"plantilla_{template_id}.xlsx"

    try:
        item = await service.upload_file(
            content=content,
            filename=filename,
            env=env,
            folder=folder,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al subir a OneDrive: {e}")

    # Actualizar metadatos OneDrive en la plantilla
    obj.onedrive_env = env
    obj.onedrive_folder = folder
    obj.onedrive_item_id = item.get("id")
    obj.onedrive_filename = filename
    obj.onedrive_path = service.build_path(env, folder, filename)
    db.commit()
    db.refresh(obj)

    # 2. EXTRAER CÓDIGOS AUTOMÁTICAMENTE
    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content, extract_images=False)

    # 4. GUARDAR TEMPLATE CODES (CÉLULAS $$XXX$$) EN BD
    created_codes = {"valora": [], "kapital": []}
    
    for template_type in ["valora", "kapital"]:
        codes_data = extraction_result.get(template_type, [])
        logger.info(f"[Upload] Processing {template_type} codes: {len(codes_data)} found")

        for code_data in codes_data:
            try:
                code_enum = CalculationType(template_type)
                
                existing = db.execute(
                    select(TemplateCode).where(
                        (TemplateCode.code == code_data["code"]) &
                        (TemplateCode.type == code_enum) &
                        (TemplateCode.deleted_at.is_(None))
                    )
                ).scalars().first()

                if existing:
                    tc = existing
                    # ACTUALIZAR el nombre si es diferente (puede haber cambiado en el nuevo archivo)
                    new_nombre = code_data.get("nombre", "Sin nombre")
                    if tc.nombre != new_nombre:
                        logger.info(f"[Upload] Updating code {tc.code}: '{tc.nombre}' -> '{new_nombre}'")
                        tc.nombre = new_nombre
                else:
                    tc = TemplateCode(
                        code=code_data["code"],
                        nombre=code_data.get("nombre", "Sin nombre"),
                        type=code_enum,
                        hoja=code_data.get("hoja"),
                    )
                    db.add(tc)

                db.commit()
                db.refresh(tc)
                
                code_data_response = {
                    "id": tc.id,
                    "code": tc.code,
                    "nombre": tc.nombre,
                    "hoja": tc.hoja,
                    "type": tc.type.value if hasattr(tc.type, 'value') else str(tc.type),
                    "template_code_image_id": tc.template_code_image_id,
                }
                created_codes[template_type].append(code_data_response)
                logger.debug(f"[Upload] Saved template code: {code_data['code']}")
            except Exception as e:
                logger.error(f"[Upload] Error saving template code: {e}")
                continue

    
    # 3. NO EXTRAER GRÁFICOS COMO TEMPLATE CODES
    # Los gráficos se procesan SOLO COMO MEDIA (imágenes) con LibreOffice
    # Los Template Codes deben ser SOLO códigos explícitos en celdas ($$CODIGO$$)
    created_chart_codes = {"valora": [], "kapital": []}

    
    # 4. EXTRAER GRÁFICOS USANDO LIBREOFFICE (desde bytes en memoria)
    extracted_chart_images = {"valora": [], "kapital": []}
    chart_extraction_stats = {
        "total": 0,
        "valora": 0,
        "kapital": 0,
        "errors": []
    }
    
    # Crear mapa de códigos de gráficos para determinar tipo fácilmente
    chart_codes_map = {}
    for template_type in ["valora", "kapital"]:
        for chart_code_data in created_chart_codes.get(template_type, []):
            # El código ya tiene $$ de la BD
            code_key = chart_code_data["code"].replace("$$", "").upper()
            chart_codes_map[code_key] = template_type
    
    try:
        logger.info(f"[Upload] Starting LibreOffice chart extraction from {len(content)} bytes")
        logger.info(f"[Upload] Chart codes map: {chart_codes_map}")
        
        # Usar LibreOffice para extraer gráficos directamente del archivo en memoria
        libreoffice_service = get_libreoffice_chart_extractor()
        chart_result = libreoffice_service.extract_charts_from_bytes(content)
        
        logger.info(
            f"[Upload] LibreOffice extraction complete: "
            f"{chart_result['total_charts']} charts found, "
            f"Success: {chart_result['success']}"
        )
        
        if chart_result.get("errors"):
            chart_extraction_stats["errors"].extend(chart_result["errors"])

        template_prefix = re.sub(r"[^A-Za-z0-9]+", "_", (obj.nombre or "template")).strip("_").upper() or "TEMPLATE"
        
        # Procesar los gráficos extraídos y guardarlos en Media y TemplateCode
        for chart in chart_result.get("charts", []):
            if chart.get("error"):
                logger.warning(f"[Upload] Chart {chart['index']} has error: {chart['error']}")
                continue
            
            try:
                chart_filename = chart.get("filename")
                chart_index = chart.get("index", 0)
                chart_title = chart.get("original_name", f"Chart {chart_index}")
                
                if not chart_filename:
                    continue
                
                # ✅ USAR DIRECTAMENTE el template_type que viene del servicio LibreOffice
                # Ya está mapeado correctamente por sheet ("Plantilla Usuario" = valora, "WACC" = kapital)
                template_type = chart.get("template_type", "valora")
                
                # Normalizar el código de gráfico con $$
                # normalize_code retorna $$XXXXX$$, así que extraemos el código interno
                normalized = normalize_code(chart_title) if chart_title else None
                if not normalized:
                    normalized = normalize_code(chart_filename.replace(".jpg", "").replace(".png", ""))
                
                if not normalized:
                    logger.warning(f"[Upload] Could not normalize chart title: {chart_title}")
                    continue
                
                # normalized ya tiene $$, así que úsalo directamente
                chart_code_normalized = normalized
                
                # ========== GUARDAR COMO TEMPLATE CODE EN BD ==========
                # Los códigos de gráficos deben guardarse como TemplateCode para que se retornen correctamente
                try:
                    code_enum = CalculationType(template_type)
                    
                    existing_template_code = db.execute(
                        select(TemplateCode).where(
                            (TemplateCode.code == chart_code_normalized) &
                            (TemplateCode.type == code_enum) &
                            (TemplateCode.deleted_at.is_(None))
                        )
                    ).scalars().first()
                    
                    if not existing_template_code:
                        template_code = TemplateCode(
                            code=chart_code_normalized,
                            nombre=chart_title,
                            type=code_enum,
                            hoja=chart.get("sheet", None),
                        )
                        db.add(template_code)
                        db.commit()
                        db.refresh(template_code)
                        logger.info(f"[Upload] Saved chart code as TemplateCode: {chart_code_normalized}")
                        
                        created_chart_codes[template_type].append({
                            "id": template_code.id,
                            "code": template_code.code,
                            "nombre": template_code.nombre,
                            "hoja": template_code.hoja,
                            "type": template_type,
                        })
                    else:
                        logger.info(f"[Upload] Chart code already exists: {chart_code_normalized}")
                        created_chart_codes[template_type].append({
                            "id": existing_template_code.id,
                            "code": existing_template_code.code,
                            "nombre": existing_template_code.nombre,
                            "hoja": existing_template_code.hoja,
                            "type": template_type,
                        })
                        
                except Exception as e:
                    logger.error(f"[Upload] Error saving chart code as TemplateCode: {e}")
                
                # ========== GUARDAR EN MEDIA (BD) PARA LAS IMÁGENES ==========
                code_without_dollars = chart_code_normalized.replace("$$", "")
                prefixed_filename = f"{template_prefix}-{template_type.upper()}-{code_without_dollars}.jpg"
                prefixed_stem = prefixed_filename.replace('.jpg', '').replace('.png', '')


                # Determinar file_url y object_key (de subida o de chart existente)
                file_url = chart.get("url")
                object_key = chart.get("path")
                # Si la subida a S3 fue exitosa, sobreescribir con los nuevos valores
                if chart.get("_s3_upload_result"):
                    file_url = chart["_s3_upload_result"].get("file_url", file_url)
                    object_key = chart["_s3_upload_result"].get("object_key", object_key)

                # Eliminar imagen anterior en S3 si existe y el object_key es diferente
                chart_object_key = chart.get("path", None)
                if chart_object_key and chart_object_key != object_key:
                    try:
                        s3_service.delete_file(chart_object_key)
                        logger.info(f"[Upload] Deleted old chart from S3: {chart_object_key}")
                    except Exception as exc:
                        logger.warning(f"[Upload] Could not delete old chart from S3: {exc}")

                stored_size = chart.get("size", 0)


                existing_media = db.execute(
                    select(Media).where(
                        (Media.filename == prefixed_filename) &
                        (Media.folder.like(f"%master-templates/{template_id}%")) &
                        (Media.deleted_at.is_(None))
                    )
                ).scalars().first()

                if not existing_media:
                    media = Media(
                        filename=prefixed_filename,
                        original_name=chart_title,
                        mime_type="image/jpeg",
                        size=stored_size,
                        url=file_url,
                        storage_path=object_key,
                        folder=f"master-templates/{template_id}/{template_type}",
                        meta={
                            "chart_code": chart_code_normalized,
                            "chart_title": chart_title,
                            "template_id": template_id,
                            "template_type": template_type,
                            "template_name": obj.nombre,
                            "size": stored_size,
                        },
                    )
                    db.add(media)
                    db.commit()
                    logger.info(f"[Upload] Saved chart image to Media: {prefixed_filename} (code: {chart_code_normalized})")
                
                # Crear entrada para respuesta con código envuelto en $$
                chart_entry = {
                    "code": chart_code_normalized,
                    "filename": prefixed_filename,
                    "original_name": chart_title,
                    "url": f"/api/v1/main/master-templates/chart-file/{prefixed_stem}",
                    "size": stored_size,
                    "type": template_type,
                    "error": None
                }
                
                extracted_chart_images[template_type].append(chart_entry)
                logger.info(f"[Upload] Processed chart: {prefixed_filename} -> type: {template_type}")
                
            except Exception as e:
                logger.error(f"[Upload] Error processing chart {chart.get('index')}: {e}")
                continue
        
        chart_extraction_stats["total"] = chart_result.get("total_charts", 0)
        chart_extraction_stats["valora"] = len(extracted_chart_images.get("valora", []))
        chart_extraction_stats["kapital"] = len(extracted_chart_images.get("kapital", []))
            
    except Exception as e:
        error_msg = f"Error in LibreOffice chart extraction: {str(e)}"
        logger.error(f"[Upload] {error_msg}")
        chart_extraction_stats["errors"].append(error_msg)

    # También obtener todas las imágenes desde la BD para asegurar consistencia
    media_query = select(Media).where(
        (Media.deleted_at.is_(None)) &
        (Media.folder.like(f"%master-templates/{template_id}%"))
    )
    all_media_in_db = db.execute(media_query).scalars().all()
    logger.info(f"[Upload] Total Media records in DB for template {template_id}: {len(all_media_in_db)}")
    
    # Agregar todos losMedia records a la respuesta si no se encontraron vía LibreOffice
    if not extracted_chart_images.get("valora") and not extracted_chart_images.get("kapital") and all_media_in_db:
        for media in all_media_in_db:
            template_type = "valora"  # default
            if media.meta and "template_type" in media.meta:
                template_type = media.meta["template_type"]
            elif "kapital" in media.folder.lower():
                template_type = "kapital"
            
            chart_entry = {
                "code": media.meta.get("chart_code", media.filename) if media.meta else media.filename,
                "filename": media.filename,
                "title": media.meta.get("chart_title", media.original_name) if media.meta else media.original_name,
                "url": media.url or f"/api/v1/main/master-templates/chart-file/{media.filename.replace('.jpg', '')}",
                "size": media.meta.get("size", 0) if media.meta else 0,
                "type": template_type,
                "error": None
            }
            
            if template_type not in extracted_chart_images:
                extracted_chart_images[template_type] = []
            extracted_chart_images[template_type].append(chart_entry)
        
        chart_extraction_stats["total"] = sum(len(v) for v in extracted_chart_images.values())
        chart_extraction_stats["valora"] = len(extracted_chart_images.get("valora", []))
        chart_extraction_stats["kapital"] = len(extracted_chart_images.get("kapital", []))
        logger.info(f"[Upload] Added images from DB: total={chart_extraction_stats['total']}")

    return {
        "template": MasterTemplateResponse.model_validate(obj),
        "extracted_codes": created_codes,
        "extracted_chart_codes": created_chart_codes,
        "extracted_chart_images": extracted_chart_images,
        "chart_extraction_stats": {
            "total": chart_extraction_stats["total"],
            "valora": chart_extraction_stats["valora"],
            "kapital": chart_extraction_stats["kapital"],
            "errors": chart_extraction_stats["errors"]
        },
        "statistics": extractor.get_statistics(extraction_result),
        "processed_sheets": extraction_result.get("processed_sheets", []),
    }



# === RE-UPLOAD + AUTO EXTRACT (for updating existing masterplatforms) =======================
@router.post("/{template_id}/re-upload")
async def re_upload_and_extract_codes(
    template_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Reemplaza completamente el Excel de la plantilla maestra.
    - Soft-delete de códigos e imágenes anteriores de esta plantilla.
    - Subida de nuevo archivo a OneDrive (el anterior se elimina).
    - Inserta/rehabilita códigos e imágenes nuevos.
    - Retorna SOLO los códigos/imágenes efectivamente nuevos (diff contra el estado anterior).
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo se permiten archivos Excel (.xlsx, .xls)",
        )

    content = await file.read()
    file_size = len(content)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El archivo excede el tamaño máximo de 10MB",
        )
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo está vacío",
        )

    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    # ====== Snapshot previo para calcular diff ======
    old_code_sets = {"valora": set(), "kapital": set()}
    old_image_sets = {"valora": set(), "kapital": set()}

    old_media_rows = db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None))
            & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all()

    for media in old_media_rows:
        mt = "valora"
        if media.meta and media.meta.get("template_type") in ("valora", "kapital"):
            mt = media.meta.get("template_type")
        elif "kapital" in (media.folder or "").lower():
            mt = "kapital"

        code_raw = ""
        if media.meta and media.meta.get("chart_code"):
            code_raw = str(media.meta.get("chart_code"))
        else:
            code_raw = media.filename.replace(".jpg", "").replace(".png", "")

        code_norm = f"$${code_raw.replace('$$', '').upper()}$$"
        old_code_sets[mt].add(code_norm)
        old_image_sets[mt].add(media.filename)

    # códigos de celdas del archivo anterior
    if obj.onedrive_item_id:
        try:
            service_prev = get_onedrive_service()
            config_prev = OneDriveConfig()
            if config_prev.is_configured():
                old_content = await service_prev.download_file(obj.onedrive_item_id)
                old_extractor = get_template_code_extractor()
                old_result = old_extractor.extract_from_bytes(old_content, extract_images=False)
                for t in ["valora", "kapital"]:
                    for item in old_result.get(t, []):
                        c = str(item.get("code", "")).replace("$$", "").upper()
                        if c:
                            old_code_sets[t].add(f"$${c}$$")
        except Exception as e:
            logger.warning(f"[ReUpload] Could not read old file codes: {e}")

    # ====== Soft-delete estado anterior (media + codes conocidos de esta plantilla) ======
    now = datetime.utcnow()

    for media in old_media_rows:
        media.deleted_at = now

    codes_to_delete = old_code_sets["valora"].union(old_code_sets["kapital"])
    if codes_to_delete:
        old_code_rows = db.execute(
            select(TemplateCode).where(
                (TemplateCode.deleted_at.is_(None))
                & (TemplateCode.code.in_(list(codes_to_delete)))
            )
        ).scalars().all()
        for code_row in old_code_rows:
            code_row.deleted_at = now

    db.commit()

    # ====== Reemplazar archivo en OneDrive ======
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )

    if obj.onedrive_item_id:
        try:
            await service.delete_file(obj.onedrive_item_id)
            logger.info(f"[ReUpload] Deleted old OneDrive file for template {template_id}")
        except Exception as e:
            logger.warning(f"[ReUpload] Could not delete old OneDrive file: {e}")

    filename = file.filename or f"plantilla_{template_id}.xlsx"
    env: Environment = settings.ENVIRONMENT
    try:
        item = await service.upload_file(
            content=content,
            filename=filename,
            env=env,
            folder=obj.onedrive_folder or "plantillas_maestras",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al subir a OneDrive: {e}",
        )

    obj.onedrive_item_id = item.get("id")
    obj.onedrive_filename = filename
    obj.onedrive_path = service.build_path(env, obj.onedrive_folder or "plantillas_maestras", filename)
    db.commit()

    # ====== Extraer e insertar nuevos códigos ======
    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content, extract_images=False)

    new_codes = {"valora": [], "kapital": []}
    restored_or_inserted_codes = {"valora": set(), "kapital": set()}

    for template_type in ["valora", "kapital"]:
        code_enum = CalculationType(template_type)
        for code_data in extraction_result.get(template_type, []):
            raw = str(code_data.get("code", "")).replace("$$", "").upper()
            if not raw:
                continue
            code_norm = f"$${raw}$$"

            existing_any = db.execute(
                select(TemplateCode).where(
                    (TemplateCode.code == code_norm)
                    & (TemplateCode.type == code_enum)
                )
            ).scalars().first()

            if existing_any:
                existing_any.deleted_at = None
                existing_any.nombre = code_data.get("nombre", existing_any.nombre)
                existing_any.hoja = code_data.get("hoja", existing_any.hoja)
            else:
                tc = TemplateCode(
                    code=code_norm,
                    nombre=code_data.get("nombre", "Sin nombre"),
                    type=code_enum,
                    hoja=code_data.get("hoja"),
                )
                db.add(tc)

            restored_or_inserted_codes[template_type].add(code_norm)

            if code_norm not in old_code_sets[template_type]:
                new_codes[template_type].append(code_norm)

    db.commit()

    # ====== Extraer e insertar imágenes/códigos de gráficos ======
    chart_errors = []
    new_images = {"valora": [], "kapital": []}

    try:
        libreoffice_service = get_libreoffice_chart_extractor()
        chart_result = libreoffice_service.extract_charts_from_bytes(content)

        template_prefix = re.sub(r"[^A-Za-z0-9]+", "_", (obj.nombre or "template")).strip("_").upper() or "TEMPLATE"

        for chart in chart_result.get("charts", []):
            if chart.get("error"):
                continue

            template_type = chart.get("template_type", "valora")
            chart_title = chart.get("original_name", "Chart")

            normalized = normalize_code(chart_title)
            if not normalized:
                continue

            code_norm = normalized
            code_without_dollars = code_norm.replace("$$", "")

            # Guardar/rehabilitar TemplateCode del gráfico
            code_enum = CalculationType(template_type)
            existing_chart_code = db.execute(
                select(TemplateCode).where(
                    (TemplateCode.code == code_norm)
                    & (TemplateCode.type == code_enum)
                )
            ).scalars().first()
            if existing_chart_code:
                existing_chart_code.deleted_at = None
                existing_chart_code.nombre = chart_title
                existing_chart_code.hoja = chart.get("sheet")
            else:
                db.add(
                    TemplateCode(
                        code=code_norm,
                        nombre=chart_title,
                        type=code_enum,
                        hoja=chart.get("sheet"),
                    )
                )

            restored_or_inserted_codes[template_type].add(code_norm)
            if code_norm not in old_code_sets[template_type] and code_norm not in new_codes[template_type]:
                new_codes[template_type].append(code_norm)

            # Guardar Media del gráfico
            prefixed_filename = f"{template_prefix}-{template_type.upper()}-{code_without_dollars}.jpg"
            prefixed_stem = prefixed_filename.replace(".jpg", "")

            chart_path = chart.get("path", "")

            # Determinar file_url y object_key (de subida o de chart existente)
            file_url = chart.get("url")
            object_key = chart.get("path")
            if chart.get("_s3_upload_result"):
                file_url = chart["_s3_upload_result"].get("file_url", file_url)
                object_key = chart["_s3_upload_result"].get("object_key", object_key)

            # Eliminar imagen anterior en S3 si existe y el object_key es diferente
            chart_object_key = chart.get("path", None)
            if chart_object_key and chart_object_key != object_key:
                try:
                    s3_service.delete_file(chart_object_key)
                    logger.info(f"[ReUpload] Deleted old chart from S3: {chart_object_key}")
                except Exception as exc:
                    logger.warning(f"[ReUpload] Could not delete old chart from S3: {exc}")

            stored_size = chart.get("size", 0)

            existing_media_any = db.execute(
                select(Media).where(
                    (Media.filename == prefixed_filename)
                    & (Media.folder.like(f"%master-templates/{template_id}%"))
                )
            ).scalars().first()

            if existing_media_any:
                existing_media_any.deleted_at = None
                existing_media_any.original_name = chart_title
                existing_media_any.mime_type = "image/jpeg"
                existing_media_any.size = stored_size
                existing_media_any.url = file_url
                existing_media_any.storage_path = object_key
                existing_media_any.folder = f"master-templates/{template_id}/{template_type}"
                existing_media_any.meta = {
                    "chart_code": code_norm,
                    "chart_title": chart_title,
                    "template_id": template_id,
                    "template_type": template_type,
                    "template_name": obj.nombre,
                    "size": stored_size,
                }
            else:
                db.add(
                    Media(
                        filename=prefixed_filename,
                        original_name=chart_title,
                        mime_type="image/jpeg",
                        size=stored_size,
                        url=file_url,
                        storage_path=object_key,
                        folder=f"master-templates/{template_id}/{template_type}",
                        meta={
                            "chart_code": code_norm,
                            "chart_title": chart_title,
                            "template_id": template_id,
                            "template_type": template_type,
                            "template_name": obj.nombre,
                            "size": stored_size,
                        },
                    )
                )

            if prefixed_filename not in old_image_sets[template_type]:
                new_images[template_type].append(prefixed_filename)

        db.commit()

    except Exception as e:
        logger.error(f"[ReUpload] Chart extraction error: {e}")
        chart_errors.append(str(e))

    return {
        "template_id": template_id,
        "template": MasterTemplateResponse.model_validate(obj),
        "comparison": {
            "new_codes": new_codes,
            "new_images": new_images,
            "total_new_codes": sum(len(v) for v in new_codes.values()),
            "total_new_images": sum(len(v) for v in new_images.values()),
        },
        "errors": chart_errors,
    }


# === EXTRACT CODES FROM ALREADY UPLOADED FILE ================================
@router.post("/{template_id}/extract-codes")
async def extract_template_codes(
    template_id: int,
    db: Session = Depends(get_db),
):
    """
    Extrae Template Codes del archivo Excel ya subido a OneDrive.
    
    Útil para:
    - Re-extraer códigos sin re-subir el archivo
    - Actualizar códigos si el archivo cambió
    
    Retorna códigos extraídos + estadísticas.
    """
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=404, detail="Master template not found")

    # Verificar que tenga archivo en OneDrive
    if not obj.onedrive_item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta plantilla no tiene archivo subido a OneDrive. Use POST /upload primero.",
        )

    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )

    # Descargar archivo de OneDrive
    try:
        content = await service.download_file(obj.onedrive_item_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al descargar de OneDrive: {e}",
        )

    try:
        # Extraer códigos y gráficos automáticamente
        extractor = get_template_code_extractor()
        extraction_result = extractor.extract_from_bytes(content, extract_images=False)

        logger.info(f"[ExtractCodes] Extraction result keys: {extraction_result.keys()}")
        logger.info(f"[ExtractCodes] Valora codes count: {len(extraction_result.get('valora', []))}")
        logger.info(f"[ExtractCodes] Kapital codes count: {len(extraction_result.get('kapital', []))}")

        # Guardar códigos en BD
        created_codes = {"valora": [], "kapital": []}

        # Procesar Template Codes (células con $$XXX$$)
        for template_type in ["valora", "kapital"]:
            codes_data = extraction_result.get(template_type, [])
            logger.info(f"[ExtractCodes] Processing {template_type} codes: {len(codes_data)} codes found")

            for code_data in codes_data:
                logger.debug(f"[ExtractCodes] Code data: {code_data}")
                try:
                    # Buscar si ya existe
                    code_enum = CalculationType(template_type)
                    logger.debug(f"[ExtractCodes] Created enum: {code_enum}")

                    existing = db.execute(
                        select(TemplateCode).where(
                            (TemplateCode.code == code_data["code"])
                            & (TemplateCode.type == code_enum)
                            & (TemplateCode.deleted_at.is_(None))
                        )
                    ).scalars().first()

                    if existing:
                        tc = existing
                        # ACTUALIZAR el nombre si es diferente (puede haber cambiado en el nuevo archivo)
                        new_nombre = code_data.get("nombre", "Sin nombre")
                        if tc.nombre != new_nombre:
                            logger.info(f"[ExtractCodes] Updating code {tc.code}: '{tc.nombre}' -> '{new_nombre}'")
                            tc.nombre = new_nombre
                        logger.debug(f"[ExtractCodes] Code {code_data['code']} already exists")
                    else:
                        tc = TemplateCode(
                            code=code_data["code"],
                            nombre=code_data.get("nombre", "Sin nombre"),
                            type=code_enum,
                            hoja=code_data.get("hoja"),
                        )
                        db.add(tc)
                        logger.debug(f"[ExtractCodes] Created new code: {code_data['code']}")

                    # Commit
                    db.commit()

                    # Obtener el ID del objeto
                    result = db.execute(
                        select(TemplateCode.id, TemplateCode.code, TemplateCode.nombre, TemplateCode.type, TemplateCode.hoja).where(
                            TemplateCode.code == code_data["code"], 
                            TemplateCode.type == code_enum
                        )
                    ).first()

                    if result:
                        code_id, code_val, nombre, code_type, hoja = result
                        code_response = {
                            "id": code_id,
                            "code": code_val,
                            "nombre": nombre,
                            "type": code_type.value if hasattr(code_type, 'value') else str(code_type),
                            "hoja": hoja,
                        }
                        created_codes[template_type].append(code_response)
                        logger.debug(f"[ExtractCodes] Added code {code_data['code']} to response")
                except Exception as e:
                    logger.error(f"[ExtractCodes] Error processing code {code_data.get('code')}: {e}")
                    continue

        # Procesar gráficos con LibreOffice desde el archivo descargado
        chart_extraction_result = {}
        try:
            logger.info(f"[ExtractCodes] Extracting charts using LibreOffice from file: {len(content)} bytes")
            
            libreoffice_service = get_libreoffice_chart_extractor()
            chart_result = libreoffice_service.extract_charts_from_bytes(content)
            
            logger.info(
                f"[ExtractCodes] LibreOffice extraction complete: "
                f"{chart_result['total_charts']} charts found, "
                f"Success: {chart_result['success']}"
            )
            
            # NOTA: Los gráficos se guardan SOLO como Media (imágenes)
            # NO se crean TemplateCode desde gráficos
            # Los TemplateCode deben ser SOLO códigos explícitos en celdas ($$CODIGO$$)
            
        except Exception as e:
            logger.error(f"[ExtractCodes] Error in LibreOffice chart extraction: {e}")

        return {
            "template_id": template_id,
            "template_name": obj.nombre,
            "template_version": obj.onedrive_filename,
            "codes": created_codes,
            "chart_stats": {
                "total": chart_extraction_result.get("total_processed", 0),
                "valora": len(chart_extraction_result.get("valora", [])),
                "kapital": len(chart_extraction_result.get("kapital", [])),
                "errors": chart_extraction_result.get("errors", [])
            },
            "statistics": extractor.get_statistics(extraction_result),
            "success": True,
        }
    except Exception as e:
        logger.error(f"[ExtractCodes] Error in extract_template_codes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# === DOWNLOAD FROM ONEDRIVE ===================================================
@router.get("/{template_id}/download")
async def download_from_onedrive(template_id: int, db: Session = Depends(get_db)):
    """Descarga el Excel desde OneDrive y lo retorna como archivo."""
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    if not obj.onedrive_item_id:
        raise HTTPException(404, "Esta plantilla no tiene archivo subido a OneDrive.")

    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no está configurado.")

    try:
        content = await service.download_file(obj.onedrive_item_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al descargar de OneDrive: {e}")

    filename = obj.onedrive_filename or f"plantilla_{obj.id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# === GET EXTRACTED CODES =====================================================
@router.get("/{template_id}/codes")
async def get_template_codes(template_id: int, db: Session = Depends(get_db)):
    """
    Obtiene los Template Codes asociados con una plantilla maestra.
    Retorna códigos agrupados por tipo (valora, kapital).
    """
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    # 1) Códigos de gráficos asociados a ESTA plantilla (via Media.meta.chart_code)
    media_query = select(Media).where(
        (Media.deleted_at.is_(None)) &
        (Media.folder.like(f"%master-templates/{template_id}%"))
    )
    media_files = db.execute(media_query).scalars().all()

    chart_codes = set()
    expected_name_by_code = {}
    for media in media_files:
        if media.meta and media.meta.get("chart_code"):
            raw_code = media.meta.get("chart_code")
            norm_code = f"$${raw_code.replace('$$', '').upper()}$$"
            chart_codes.add(norm_code)
            if media.meta.get("chart_title"):
                expected_name_by_code[norm_code] = media.meta.get("chart_title")

    # 2) Códigos normales de celdas ($$...$$) del archivo actual de esta plantilla
    normal_codes = set()
    try:
        if obj.onedrive_item_id:
            service = get_onedrive_service()
            config = OneDriveConfig()
            if config.is_configured():
                content = await service.download_file(obj.onedrive_item_id)
                extractor = get_template_code_extractor()
                extraction_result = extractor.extract_from_bytes(content, extract_images=False)

                for t in ["valora", "kapital"]:
                    for item in extraction_result.get(t, []):
                        raw_code = item.get("code", "")
                        if raw_code:
                            norm_code = f"$${raw_code.replace('$$', '').upper()}$$"
                            normal_codes.add(norm_code)
                            if item.get("nombre"):
                                expected_name_by_code.setdefault(norm_code, item.get("nombre"))
    except Exception as e:
        logger.warning(f"[Codes] Could not extract normal codes from OneDrive file for template {template_id}: {e}")

    allowed_codes = normal_codes.union(chart_codes)

    if not allowed_codes:
        return {
            "template_id": template_id,
            "template_name": obj.nombre,
            "codes": {"valora": [], "kapital": []},
            "statistics": {"total": 0, "valora": 0, "kapital": 0},
        }

    query = select(TemplateCode).where(
        (TemplateCode.deleted_at.is_(None)) &
        (TemplateCode.code.in_(list(allowed_codes)))
    )

    all_codes = db.execute(query).scalars().all()

    # Resolver colisiones por collation case-insensitive en MySQL:
    # quedarse con 1 registro por código, priorizando coincidencia por título de esta plantilla.
    code_candidates = {}
    for code in all_codes:
        norm_code = f"$${str(code.code).replace('$$', '').upper()}$$"
        code_candidates.setdefault(norm_code, []).append(code)

    selected_codes = []
    for norm_code, candidates in code_candidates.items():
        expected_title = expected_name_by_code.get(norm_code)

        preferred = None
        if expected_title:
            preferred = next((c for c in candidates if (c.nombre or "").strip() == expected_title), None)

        if not preferred:
            preferred = next((c for c in candidates if str(c.code).replace('$$', '').upper() == norm_code.replace('$$', '')), None)

        if not preferred:
            preferred = sorted(candidates, key=lambda c: c.created_at or datetime.min, reverse=True)[0]

        selected_codes.append(preferred)

    valora_codes = []
    kapital_codes = []

    for code in selected_codes:
        normalized_code = f"$${str(code.code).replace('$$', '').upper()}$$"
        # Convertir enum a string para Pydantic
        code_data = {
            "id": code.id,
            "template_code_image_id": code.template_code_image_id,
            "type": code.type.value if hasattr(code.type, 'value') else str(code.type),
            "hoja": code.hoja,
            "nombre": code.nombre,
            "code": normalized_code,
            "template_ids": [t.id for t in code.templates] if hasattr(code, 'templates') else [],
            "created_at": code.created_at,
            "updated_at": code.updated_at,
            "deleted_at": code.deleted_at,
        }
        code_response = TemplateCodeResponse.model_validate(code_data)
        if code.type == CalculationType.VALORA:
            valora_codes.append(code_response)
        elif code.type == CalculationType.KAPITAL:
            kapital_codes.append(code_response)

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "codes": {
            "valora": valora_codes,
            "kapital": kapital_codes,
        },
        "statistics": {
            "total": len(valora_codes) + len(kapital_codes),
            "valora": len(valora_codes),
            "kapital": len(kapital_codes),
        }
    }


# === GET CHART IMAGES FOR TEMPLATE ==========================================
@router.get("/{template_id}/chart-images")
def get_template_chart_images(template_id: int, db: Session = Depends(get_db)):
    """
    Obtiene todas las imágenes de gráficos extraídas para una plantilla.
    Agrupa por tipo (valora, kapital).
    
    Retorna imágenes desde BD (Media), con fallback a disco si es necesario.
    """
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=404, detail="Master template not found")
    
    # Buscar Media que pertenecen a esta plantilla
    query = select(Media).where(
        (Media.deleted_at.is_(None)) &
        (Media.folder.like(f"%master-templates/{template_id}%"))
    ).order_by(Media.created_at.desc())
    
    media_files = db.execute(query).scalars().all()
    
    valora_images = []
    kapital_images = []
    # PRIMERO: Procesar media desde BD
    for media in media_files:
        # Extraer el chart_code del meta (ya viene con $$ desde la BD)
        chart_code = media.meta.get("chart_code", media.filename.replace(".jpg", "").replace(".png", "")) if media.meta else media.filename.replace(".jpg", "").replace(".png", "")
        
        # Asegurar que el código tenga el formato correcto $$CODE$$
        if not chart_code.startswith("$$"):
            chart_code = f"$${chart_code}$$"
        
        # Preparar metadata con template_name incluido
        meta = media.meta.copy() if media.meta else {}
        meta["template_id"] = template_id
        meta["template_name"] = obj.nombre  # Agregar nombre de la plantilla
        
        chart_info = {
            "code": chart_code,
            "filename": media.filename,
            "original_name": media.original_name,
            "url": media.url,
            "size": media.size or 0,
            "created_at": media.created_at.isoformat() if media.created_at else None,
            "meta": meta,
        }
        
        # Determinar si es valora o kapital basado en folder o meta
        template_type = "valora"  # default
        if media.meta and "template_type" in media.meta:
            template_type = media.meta["template_type"]
        elif "kapital" in media.folder.lower():
            template_type = "kapital"
        elif "valora" in media.folder.lower():
            template_type = "valora"
        
        if template_type == "kapital":
            kapital_images.append(chart_info)
        else:
            valora_images.append(chart_info)
    
    if not media_files:
        logger.warning(
            f"[GetChartImages] No Media records found for template {template_id}. "
            "No disk fallback is used to avoid mixing charts from other templates."
        )
    
    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "valora": valora_images,
        "kapital": kapital_images,
        "total": len(valora_images) + len(kapital_images),
    }


# === EXTRACT CHARTS FROM TEMPLATE =============================================
@router.post("/{template_id}/extract-charts")
async def extract_template_charts(
    template_id: int,
    db: Session = Depends(get_db),
):
    """
    Extrae gráficos del archivo Excel ya subido a OneDrive.
    
    Útil para:
    - Re-extraer gráficos sin re-subir el archivo
    - Actualizar gráficos si el archivo cambió
    
    Retorna gráficos extraídos + estadísticas.
    """
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=404, detail="Master template not found")
    
    # Verificar que tenga archivo en OneDrive
    if not obj.onedrive_item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta plantilla no tiene archivo subido a OneDrive. Use POST /upload primero.",
        )
    
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )
    
    # Descargar archivo de OneDrive
    try:
        content = await service.download_file(obj.onedrive_item_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al descargar de OneDrive: {e}",
        )
    
    try:
        # Extractar gráficos con LibreOffice
        logger.info(f"[ExtractCharts] Starting chart extraction for template {template_id}")
        
        libreoffice_service = get_libreoffice_chart_extractor()
        chart_result = libreoffice_service.extract_charts_from_bytes(content)
        
        logger.info(
            f"[ExtractCharts] LibreOffice extraction complete: "
            f"{chart_result['total_charts']} charts found, "
            f"Success: {chart_result['success']}"
        )
        
        extracted_charts = {"valora": [], "kapital": []}
        errors = chart_result.get("errors", [])
        
        # Procesar cada gráfico extraído
        for chart in chart_result.get("charts", []):
            if chart.get("error"):
                logger.warning(f"[ExtractCharts] Chart error: {chart['error']}")
                continue
            
            # Por defecto asignar a valora
            template_type = "valora"
            filename = chart.get("filename")
            
            if not filename:
                continue
            
            try:
                # Crear o actualizar registro Media con nueva convención
                chart_code_with_dollars = chart.get("code")
                chart_code = chart_code_with_dollars.replace("$$", "") if chart_code_with_dollars else filename.replace(".jpg", "").replace("CHART", "")
                chart_title = chart.get("original_name", f"Chart {chart.get('index')}")
                template_type = chart.get("template_type", "valora")
                
                # Generar nombre final: TEMPLATE-TYPE-CODE.jpg
                normalized_template = _normalize_template_name(obj.nombre)
                new_filename = f"{normalized_template}-{template_type.upper()}-{chart_code}.jpg"
                
                # Intentar renombrar el archivo
                old_path = Path(chart.get("path", f"/app/public/master-templates-graphs/{filename}"))
                new_path = libreoffice_service.get_storage_path() / new_filename
                
                try:
                    if old_path.exists():
                        old_path.rename(new_path)
                        logger.info(f"[ExtractCharts] Renamed chart: {old_path.name} -> {new_filename}")
                except Exception as rename_err:
                    logger.warning(f"[ExtractCharts] Could not rename file: {rename_err}")
                    # Continuar incluso si no se puede renombrar
                
                # Buscar si ya existe
                existing_media = db.execute(
                    select(Media).where(
                        (Media.filename == new_filename) &
                        (Media.folder.like(f"%master-templates/{template_id}%")) &
                        (Media.deleted_at.is_(None))
                    )
                ).scalars().first()
                
                if existing_media:
                    media = existing_media
                else:
                    media = Media(
                        filename=new_filename,
                        original_name=chart_title,
                        mime_type="image/jpeg",
                        url=f"/api/v1/main/master-templates/chart-file/{new_filename.replace('.jpg', '').replace('.png', '')}",
                        storage_path=str(new_path),
                        folder=f"master-templates/{template_id}/{template_type}",
                        meta={
                            "chart_code": chart_code,
                            "chart_title": chart_title,
                            "template_id": template_id,
                            "template_type": template_type,
                        },
                    )
                    db.add(media)
                    db.flush()
                
                db.commit()
                
                chart_entry = {
                    "filename": new_filename,
                    "original_name": chart_title,
                    "url": f"/api/v1/main/master-templates/chart-file/{new_filename.replace('.jpg', '').replace('.png', '')}",
                    "size": chart.get("size", 0),
                }
                extracted_charts[template_type].append(chart_entry)
                logger.info(f"[ExtractCharts] Saved chart image: {new_filename}")
                
            except Exception as e:
                logger.error(f"[ExtractCharts] Error processing chart {filename}: {e}")
                errors.append(f"Error processing {filename}: {str(e)}")
                continue
        
        return {
            "template_id": template_id,
            "template_name": obj.nombre,
            "valora": extracted_charts.get("valora", []),
            "kapital": extracted_charts.get("kapital", []),
            "total": len(extracted_charts.get("valora", [])) + len(extracted_charts.get("kapital", [])),
            "statistics": {
                "total": chart_result.get("total_charts", 0),
                "extracted_valora": len(extracted_charts.get("valora", [])),
                "extracted_kapital": len(extracted_charts.get("kapital", [])),
                "errors": errors,
            },
        }
        
    except Exception as e:
        logger.error(f"[ExtractCharts] Error in extract_template_charts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
