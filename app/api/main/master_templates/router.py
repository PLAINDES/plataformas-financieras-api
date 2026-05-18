# app/api/main/master_templates_router.py
"""
CRUD de Plantillas Maestras + integración OneDrive + Extracción nativa de gráficos vía Microsoft Graph.
"""
import asyncio
import io
import time
import logging
from datetime import datetime
from typing import Optional, Literal
from urllib.parse import quote
import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse

from app.db.database import get_db
from app.api.deps import get_current_admin
from app.models.user import User
from app.models.templates import MasterTemplate
from app.models.main import TemplateCode, CalculationType
from app.models.cms import Media
from app.schemas.templates import (
    MasterTemplateCreate, MasterTemplateUpdate, MasterTemplateResponse,
    TemplateCodeResponse,
)
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig
from app.services.template_code_extractor import get_template_code_extractor
from app.services.aws_service import s3_service
from app.core.config import settings

from app.api.main.master_templates.services import (
    _chart_candidate_dirs, _clear_user_default_templates, _ensure_user_has_default_template,
    _process_and_save_cell_codes, _extract_and_save_charts_via_graph
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main/master-templates",
    tags=["Master Templates"],
    dependencies=[Depends(get_current_admin)],
)

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]

# =============================
# RESTO DE RUTAS GENERALES
# =============================


@router.get("/chart-file/{chart_filename}")
async def get_chart_image(chart_filename: str):
    chart_path = None
    for base_dir in _chart_candidate_dirs():
        if not base_dir.exists():
            continue
        for ext in ["jpg", "png", "jpeg"]:
            p = base_dir / f"{chart_filename}.{ext}"
            if p.exists():
                chart_path = p
                break
        if chart_path:
            break

    if not chart_path:
        for base_dir in _chart_candidate_dirs():
            if not base_dir.exists():
                continue
            for ext in ["jpg", "png", "jpeg"]:
                matches = sorted(base_dir.glob(f"*-{chart_filename}.{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
                if matches:
                    chart_path = matches[0]
                    break
            if chart_path:
                break

    if not chart_path or not chart_path.exists():
        raise HTTPException(404, f"Chart image not found: {chart_filename}")
    return StreamingResponse(open(chart_path, "rb"), media_type="image/png" if chart_path.suffix.lower() == ".png" else "image/jpeg", headers={"Content-Disposition": f'inline; filename="{chart_path.name}"'})



@router.post("", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_master_template(payload: MasterTemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):

    if not payload.nombre or len(payload.nombre) < 3:
        raise HTTPException(422, "Nombre requiere >= 3 caracteres")

    user_templates_count = db.execute(select(MasterTemplate.id).where((MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.created_by_user_id == current_user.id))).all()
    should_be_default = payload.is_default or len(user_templates_count) == 0
    if should_be_default:
        _clear_user_default_templates(db, current_user.id)

    obj = MasterTemplate(nombre=payload.nombre.strip(), description=payload.description.strip() if payload.description else None, is_default=should_be_default, created_by_user_id=current_user.id)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


@router.get("", response_model=list[MasterTemplateResponse])
def list_master_templates(limit: int = 10, offset: int = 0, search: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    query = select(MasterTemplate).where((MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.created_by_user_id == current_user.id))
    if search:
        query = query.where(or_(MasterTemplate.nombre.ilike(f"%{search}%"), MasterTemplate.description.ilike(f"%{search}%")))

    templates = db.execute(query.order_by(MasterTemplate.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    return [MasterTemplateResponse.model_validate(t) for t in templates]


@router.get("/{template_id}", response_model=MasterTemplateResponse)
def get_master_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")
    if obj.created_by_user_id != current_user.id:
        raise HTTPException(403, "Forbidden")
    return MasterTemplateResponse.model_validate(obj)


@router.put("/{template_id}", response_model=MasterTemplateResponse)
def update_master_template(
    template_id: int,
    payload: MasterTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    if obj.created_by_user_id != current_user.id:
        raise HTTPException(403, "No tiene permisos para actualizar esta plantilla")

    update_data = payload.model_dump(exclude_unset=True)
    new_default = update_data.pop("is_default", None)

    if new_default is True:
        _clear_user_default_templates(db, current_user.id, exclude_template_id=obj.id)
        obj.is_default = True
    elif new_default is False:
        obj.is_default = False

    for key, value in update_data.items():
        setattr(obj, key, value)

    _ensure_user_has_default_template(db, current_user.id)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


@router.post("/{template_id}/set-default", response_model=MasterTemplateResponse)
def set_default_master_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    if obj.created_by_user_id != current_user.id:
        raise HTTPException(403, "No tiene permisos para establecer esta plantilla")

    _clear_user_default_templates(db, current_user.id, exclude_template_id=obj.id)
    obj.is_default = True
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)

@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_master_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")

    media_rows = db.execute(select(Media).where((Media.deleted_at.is_(None)) & (Media.folder.like(f"%master-templates/{template_id}%")))).scalars().all()
    codes_to_soft_delete = {f"$${str(m.meta.get('chart_code')).replace('$$', '').upper()}$$" for m in media_rows if m.meta and m.meta.get("chart_code")}
    for m in media_rows:
        m.deleted_at = datetime.utcnow()

    if codes_to_soft_delete:
        for code_row in db.execute(select(TemplateCode).where((TemplateCode.deleted_at.is_(None)) & (TemplateCode.code.in_(list(codes_to_soft_delete))))).scalars().all():
            code_row.deleted_at = datetime.utcnow()

    obj.template_codes = []
    obj.deleted_at = datetime.utcnow()
    obj.is_default = False
    _ensure_user_has_default_template(db, current_user.id)
    db.commit()
    return None

# ==============================================================================
# RUTAS DE PROCESAMIENTO REFACTORIZADAS
# ==============================================================================

@router.post("/{template_id}/upload")
async def upload_and_extract_codes(
    template_id: int, file: UploadFile = File(...), folder: Folder = Form("plantillas_maestras"), db: Session = Depends(get_db)
):
    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls')):
        raise HTTPException(422, "Debe ser .xlsx/.xls")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Excede 10MB")
    if len(content) == 0:
        raise HTTPException(422, "Archivo vacío")

    env: Environment = settings.ENVIRONMENT
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")

    # ====== SNAPSHOT PREVIO - Capturar códigos EXISTENTES DE ESTA PLANTILLA ======
    old_code_sets = {"valora": set(), "kapital": set()}
    old_image_sets = {"valora": set(), "kapital": set()}

    # Capturar códigos de TemplateCode que están ACTIVOS Y VINCULADOS A ESTA PLANTILLA
    for code in obj.template_codes:
        if code and code.deleted_at is None:
            if code.type == CalculationType.VALORA:
                old_code_sets["valora"].add(code.code)
            elif code.type == CalculationType.KAPITAL:
                old_code_sets["kapital"].add(code.code)

    # Capturar Media (gráficos) que están ACTIVOS para esta plantilla
    old_media_rows = db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None))
            & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all()

    for media in old_media_rows:
        mt = media.meta.get("template_type", "valora") if media.meta else ("kapital" if "kapital" in (media.folder or "").lower() else "valora")
        c = str(media.meta.get("chart_code", media.filename.replace(".png", "").replace(".jpg", ""))).replace("$$", "").upper()
        old_code_sets[mt].add(f"$${c}$$")
        old_image_sets[mt].add(media.filename)

    # ====== HARD-DELETE PREVIO ======
    # 1. Desvincularse: Soft-delete de TemplateCode y desvincularse de Media
    for code in obj.template_codes:
        if code:
            code.template_code_image_id = None  # Desvincularse de Media
            code.deleted_at = datetime.utcnow()

    obj.template_codes = []
    db.commit()  # Commit para guardar desvinculos antes de borrar Media

    # 2. Hard-delete de Media (eliminar completamente BD + S3)
    for m in old_media_rows:
        # Eliminar archivo de S3 si existe
        if m.storage_path:
            try:
                s3_service.delete_file(m.storage_path)
            except Exception as e:
                logger.warning(f"Error eliminando archivo S3 {m.storage_path}: {e}")
        # Eliminar registro de BD
        db.delete(m)

    db.commit()

    service = get_onedrive_service()
    if not OneDriveConfig().is_configured():
        raise HTTPException(503, "OneDrive no configurado")

    # 1. SUBIR A ONEDRIVE
    original_name = file.filename or f"plantilla_{template_id}.xlsx"
    unique_onedrive_name = f"{template_id}-{original_name}"

    try:
        item = await service.upload_file(content=content, filename=unique_onedrive_name, env=env, folder=folder)
    except Exception as e:
        raise HTTPException(502, f"Error OneDrive: {e}")

    obj.onedrive_env, obj.onedrive_folder, obj.onedrive_item_id = env, folder, item.get("id")

    obj.onedrive_filename = unique_onedrive_name
    obj.original_filename = original_name
    obj.onedrive_path = service.build_path(env, folder, unique_onedrive_name)

    db.commit()
    db.refresh(obj)

    # 2. EXTRAER TEXT CODES
    extractor = get_template_code_extractor()
    extraction_result = await asyncio.to_thread(extractor.extract_from_bytes, content)

    new_codes, _ = _process_and_save_cell_codes(db, obj, extraction_result, old_code_sets)

    # 3. EXTRAER GRÁFICOS (GRAPH API)
    extracted_chart_images, total_charts, chart_errors = await _extract_and_save_charts_via_graph(db, template_id, obj, service)
    new_images = {"valora": [], "kapital": []}

    for template_type, charts in extracted_chart_images.items():
        for chart in charts:
            if chart["filename"] not in old_image_sets[template_type]:
                new_images[template_type].append(chart["filename"])

    return {
        "template": MasterTemplateResponse.model_validate(obj),
        "extracted_codes": new_codes,
        "extracted_chart_codes": {"valora": [], "kapital": []},
        "extracted_chart_images": extracted_chart_images,
        "chart_extraction_stats": {
            "total": total_charts,
            "valora": len(extracted_chart_images.get("valora", [])),
            "kapital": len(extracted_chart_images.get("kapital", [])),
            "errors": chart_errors
        },
        "comparison": {
            "new_codes": new_codes,
            "new_images": new_images,
            "total_new_codes": sum(len(v) for v in new_codes.values()),
            "total_new_images": sum(len(v) for v in new_images.values()),
        },
        "statistics": extractor.get_statistics(extraction_result),
        "processed_sheets": extraction_result.get("processed_sheets", []),
    }


@router.post("/{template_id}/re-upload")
async def re_upload_and_extract_codes(
    template_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)
):
    start_total = time.perf_counter()

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(422, "Solo Excel")
    content = await file.read()
    if not content:
        raise HTTPException(422, "Vacío")

    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")

    # ====== 1. SNAPSHOT PREVIO - Capturar códigos EXISTENTES DE ESTA PLANTILLA ======
    t0 = time.perf_counter() # time
    old_code_sets = {"valora": set(), "kapital": set()}
    old_image_sets = {"valora": set(), "kapital": set()}

    # Capturar códigos de TemplateCode que están ACTIVOS Y VINCULADOS A ESTA PLANTILLA
    for code in obj.template_codes:
        if code and code.deleted_at is None:
            if code.type == CalculationType.VALORA:
                old_code_sets["valora"].add(code.code)
            elif code.type == CalculationType.KAPITAL:
                old_code_sets["kapital"].add(code.code)

    # Capturar Media (gráficos) que están ACTIVOS para esta plantilla
    old_media_rows = db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None)) & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all()

    for m in old_media_rows:
        mt = m.meta.get("template_type", "valora") if m.meta else ("kapital" if "kapital" in (m.folder or "").lower() else "valora")
        c = str(m.meta.get("chart_code", m.filename.replace(".png", "").replace(".jpg", ""))).replace("$$", "").upper()
        old_code_sets[mt].add(f"$${c}$$")
        old_image_sets[mt].add(m.filename)

    print(f"[TIMER] 1. Snapshot previo: {time.perf_counter() - t0:.2f}s")

    # ====== 2. HARD-DELETE del estado anterior ======
    # 1. Desvincularse: Soft-delete de TemplateCode y desvincularse de Media
    t0 = time.perf_counter()
    for code in obj.template_codes:
        if code:
            code.template_code_image_id = None  # Desvincularse de Media
            code.deleted_at = datetime.utcnow()

    obj.template_codes = []
    db.commit()  # Commit para guardar desvinculos antes de borrar Media

    media_to_delete = db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None)) & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all()

    # 2. Hard-delete de Media (eliminar completamente los gráficos viejos BD + S3)
    async def delete_s3_file(path):
        try:
            await asyncio.to_thread(s3_service.delete_file, path)
        except Exception as e:
            logger.warning(f"Error eliminando archivo S3 {path}: {e}")

    s3_delete_tasks = [delete_s3_file(m.storage_path) for m in media_to_delete if m.storage_path]
    if s3_delete_tasks:
        await asyncio.gather(*s3_delete_tasks)

    # Eliminar registro de BD
    for m in media_to_delete:
        db.delete(m)

    db.commit()

    print(f"[TIMER] 2. Hard-Delete (BD + S3 asincrono): {time.perf_counter() - t0:.2f}s")
    # ====== 3. Reemplazar archivo en OneDrive ======
    t0 = time.perf_counter()
    service = get_onedrive_service()
    if obj.onedrive_item_id:
        try:
            await service.delete_file(obj.onedrive_item_id)
        except Exception:
            pass

    original_name = file.filename or f"plantilla_{template_id}.xlsx"
    unique_onedrive_name = f"{template_id}-{original_name}"

    env: Environment = settings.ENVIRONMENT
    try:
        item = await service.upload_file(content=content, filename=unique_onedrive_name, env=env, folder=obj.onedrive_folder or "plantillas_maestras")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 423:
            raise HTTPException(
                status_code=400, 
                detail="La plantilla está actualmente en uso por un cálculo activo. Espere a que las sesiones expiren e intente de nuevo."
            )
        raise HTTPException(status_code=e.response.status_code, detail=str(e))

    obj.onedrive_item_id = item.get("id")
    obj.onedrive_filename = unique_onedrive_name
    obj.original_filename = original_name
    obj.onedrive_path = service.build_path(env, obj.onedrive_folder or "plantillas_maestras", unique_onedrive_name)

    db.commit()
    print(f"[TIMER] 3. Upload a OneDrive: {time.perf_counter() - t0:.2f}s")

    # ====== 4. Extraer e insertar NUEVOS códigos de celdas ======
    t0 = time.perf_counter()
    extractor = get_template_code_extractor()
    extraction_result = await asyncio.to_thread(extractor.extract_from_bytes, content)

    _, new_codes = _process_and_save_cell_codes(db, obj, extraction_result, old_code_sets)
    print(f"[TIMER] 4. Extracción Celdas (Openpyxl + BD): {time.perf_counter() - t0:.2f}s")

    # ====== 5. Extraer e insertar gráficos (Motor Graph API) ======
    t0 = time.perf_counter()
    extracted_charts, _, chart_errors = await _extract_and_save_charts_via_graph(db, template_id, obj, service)
    new_images = {"valora": [], "kapital": []}

    for template_type, charts in extracted_charts.items():
        for chart in charts:
            if chart["filename"] not in old_image_sets[template_type]:
                new_images[template_type].append(chart["filename"])

    print(f"[TIMER] 5. Extracción Gráficos (Graph API + S3): {time.perf_counter() - t0:.2f}s")
    print(f"[TIMER] TOTAL RE-UPLOAD: {time.perf_counter() - start_total:.2f}s")
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


@router.post("/{template_id}/extract-codes")
async def extract_template_codes(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master template not found")

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

    try:
        content = await service.download_file(obj.onedrive_item_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al descargar de OneDrive: {e}",
        )

    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content)

    created_codes, _ = _process_and_save_cell_codes(db, obj, extraction_result)

    extracted_charts, total_charts, chart_errors = await _extract_and_save_charts_via_graph(db, template_id, obj, service)

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "template_version": obj.onedrive_filename,
        "codes": created_codes,
        "chart_stats": {
            "total": total_charts,
            "valora": len(extracted_charts.get("valora", [])),
            "kapital": len(extracted_charts.get("kapital", [])),
            "errors": chart_errors,
        },
        "statistics": extractor.get_statistics(extraction_result),
        "success": True,
    }


@router.post("/{template_id}/extract-charts")
async def extract_template_charts(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master template not found")
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

    extracted_charts, total_charts, chart_errors = await _extract_and_save_charts_via_graph(db, template_id, obj, service)

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "valora": extracted_charts.get("valora", []),
        "kapital": extracted_charts.get("kapital", []),
        "total": len(extracted_charts.get("valora", [])) + len(extracted_charts.get("kapital", [])),
        "statistics": {
            "total": total_charts,
            "extracted_valora": len(extracted_charts.get("valora", [])),
            "extracted_kapital": len(extracted_charts.get("kapital", [])),
            "errors": chart_errors,
        },
    }

@router.get("/{template_id}/codes")
async def get_template_codes(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    selected_codes = [code for code in obj.template_codes if code and code.deleted_at is None]

    if not selected_codes:
        logger.info("[Codes] No linked codes found for template %s, using backward-compatible fallback", template_id)

        media_query = select(Media).where(
            (Media.deleted_at.is_(None))
            & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
        media_files = db.execute(media_query).scalars().all()

        allowed_codes = set()
        for media in media_files:
            if media.meta and media.meta.get("chart_code"):
                raw_code = str(media.meta.get("chart_code"))
                allowed_codes.add(f"$${raw_code.replace('$$', '').upper()}$$")

        try:
            if obj.onedrive_item_id:
                service = get_onedrive_service()
                config = OneDriveConfig()
                if config.is_configured():
                    content = await service.download_file(obj.onedrive_item_id)
                    extractor = get_template_code_extractor()
                    extraction_result = extractor.extract_from_bytes(content)

                    for t in ["valora", "kapital"]:
                        for item in extraction_result.get(t, []):
                            raw_code = item.get("code", "")
                            if raw_code:
                                allowed_codes.add(f"$${raw_code.replace('$$', '').upper()}$$")
        except Exception as exc:
            logger.warning(
                "[Codes] Could not extract fallback codes from OneDrive file for template %s: %s",
                template_id,
                exc,
            )

        if allowed_codes:
            selected_codes = db.execute(
                select(TemplateCode).where(
                    (TemplateCode.deleted_at.is_(None))
                    & (TemplateCode.code.in_(list(allowed_codes)))
                )
            ).scalars().all()

    if not selected_codes:
        return {
            "template_id": template_id,
            "template_name": obj.nombre,
            "codes": {"valora": [], "kapital": []},
            "statistics": {"total": 0, "valora": 0, "kapital": 0},
        }

    valora_codes = []
    kapital_codes = []

    for code in selected_codes:
        normalized_code = f"$${str(code.code).replace('$$', '').upper()}$$"
        image_url = None
        if code.template_code_image:
            image_url = code.template_code_image.url
            if not image_url and code.template_code_image.filename:
                image_stem = code.template_code_image.filename.replace(".jpg", "").replace(".png", "")
                image_url = f"/api/v1/main/master-templates/chart-file/{image_stem}"

        code_data = {
            "id": code.id,
            "template_code_image_id": code.template_code_image_id,
            "template_code_image_url": image_url,
            "type": code.type.value if hasattr(code.type, "value") else str(code.type),
            "hoja": code.hoja,
            "nombre": code.nombre,
            "code": normalized_code,
            "value": code.value,
            "template_ids": [t.id for t in code.master_templates] if hasattr(code, "master_templates") else [],
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


@router.get("/{template_id}/chart-images")
def get_template_chart_images(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUNDt, detail="Master template not found")

    query = select(Media).where(
        (Media.deleted_at.is_(None)) &
        (Media.folder.like(f"%master-templates/{template_id}%"))
    ).order_by(Media.created_at.desc())

    media_files = db.execute(query).scalars().all()

    valora_images = []
    kapital_images = []
    for media in media_files:
        chart_code = media.meta.get("chart_code", media.filename.replace(".jpg", "").replace(".png", "")) if media.meta else media.filename.replace(".jpg", "").replace(".png", "")

        if not chart_code.startswith("$$"):
            chart_code = f"$${chart_code}$$"

        meta = media.meta.copy() if media.meta else {}
        meta["template_id"] = template_id
        meta["template_name"] = obj.nombre

        chart_info = {
            "code": chart_code,
            "filename": media.filename,
            "original_name": media.original_name,
            "url": media.url,
            "size": media.size or 0,
            "created_at": media.created_at.isoformat() if media.created_at else None,
            "meta": meta,
        }

        template_type = "valora"
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
            f"[GetChartImages] No se encontraron registros multimedia para la plantilla. {template_id}. "
        )

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "valora": valora_images,
        "kapital": kapital_images,
        "total": len(valora_images) + len(kapital_images),
    }


@router.get("/{template_id}/download")
async def download_from_onedrive(template_id: int, db: Session = Depends(get_db)):
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

    filename = obj.original_filename or obj.onedrive_filename or f"plantilla_{obj.id}.xlsx"

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
