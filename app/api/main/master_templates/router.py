# app/api/main/master_templates_router.py
"""
CRUD de Plantillas Maestras + integración OneDrive + Extracción nativa de gráficos vía Microsoft Graph.
"""
import io
import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from urllib.parse import quote
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import httpx
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
from app.services.template_code_extractor import normalize_code
from app.services.aws_service import s3_service
from app.core.config import settings
from app.core.constants import TEMPLATE_SHEET_TO_TYPE

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main/master-templates",
    tags=["Master Templates"],
    dependencies=[Depends(get_current_admin)],
)

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]

# === UTILIDADES GENERALES =====================================================

class SimpleUploadFile:
    """Simula el objeto UploadFile de FastAPI para el s3_service."""
    def __init__(self, filename: str, file_bytes: io.BytesIO):
        self.filename = filename
        self.file = file_bytes
        self.content_type = "image/png"


def _normalize_template_name(template_name: str) -> str:
    normalized = (template_name or "TEMPLATE").upper()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^A-Z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_") or "TEMPLATE"


def _chart_candidate_dirs() -> list[Path]:
    return [
        Path("/app/public/master-templates-graphs"),
        Path("/app/public/chart-images"),
        Path("./public/master-templates-graphs"),
        Path("./public/chart-images"),
    ]


def _link_code_to_master_template(master_template: MasterTemplate, code: TemplateCode) -> None:
    if code not in master_template.template_codes:
        master_template.template_codes.append(code)


def _resolve_media_fields(
    template_id: int, prefixed_stem: str, prefixed_filename: str, file_url: Optional[str], object_key: Optional[str],
) -> tuple[str, str]:
    fallback_url = f"/api/v1/main/master-templates/chart-file/{prefixed_stem}"
    fallback_storage_path = object_key or f"master-templates/{template_id}/{prefixed_filename}"
    return (file_url or fallback_url, fallback_storage_path)


def _clear_user_default_templates(db: Session, user_id: int, exclude_template_id: Optional[int] = None) -> None:
    query = select(MasterTemplate).where(
        (MasterTemplate.deleted_at.is_(None))
        & (MasterTemplate.created_by_user_id == user_id)
        & (MasterTemplate.is_default.is_(True))
    )
    if exclude_template_id is not None:
        query = query.where(MasterTemplate.id != exclude_template_id)

    rows = db.execute(query).scalars().all()
    for row in rows:
        row.is_default = False


def _ensure_user_has_default_template(db: Session, user_id: Optional[int]) -> None:
    if not user_id:
        return
    active_templates = db.execute(
        select(MasterTemplate).where(
            (MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.created_by_user_id == user_id)
        ).order_by(MasterTemplate.created_at.desc())
    ).scalars().all()

    if not active_templates or any(t.is_default for t in active_templates):
        return
    active_templates[0].is_default = True


def _process_and_save_cell_codes(db: Session, obj: MasterTemplate, extraction_result: dict, old_code_sets: dict = None) -> tuple[dict, dict]:
    """
    Helper unificado para guardar los TemplateCodes extraídos de celdas.
    Retorna (created_codes, new_codes_only) para las lógicas de upload y re-upload.
    """
    created_codes = {"valora": [], "kapital": []}
    new_codes_only = {"valora": [], "kapital": []}
    old_sets = old_code_sets or {"valora": set(), "kapital": set()}

    for template_type in ["valora", "kapital"]:
        code_enum = CalculationType(template_type)
        for data in extraction_result.get(template_type, []):
            if not data.get("code"):
                continue

            cn = f"$${str(data['code']).replace('$$', '').upper()}$$"
            existing = db.execute(
                select(TemplateCode).where((TemplateCode.code == cn) & (TemplateCode.type == code_enum))
            ).scalars().first()

            if existing:
                existing.deleted_at = None
                existing.nombre = data.get("nombre", "Sin nombre")
                existing.hoja = data.get("hoja")
                tc = existing
            else:
                tc = TemplateCode(code=cn, nombre=data.get("nombre", "Sin nombre"), type=code_enum, hoja=data.get("hoja"))
                db.add(tc)

            _link_code_to_master_template(obj, tc)
            db.commit()
            db.refresh(tc)

            code_resp = {"id": tc.id, "code": tc.code, "nombre": tc.nombre, "hoja": tc.hoja, "type": template_type}
            created_codes[template_type].append(code_resp)

            if cn not in old_sets.get(template_type, set()):
                new_codes_only[template_type].append(cn)

    return created_codes, new_codes_only


# === HELPER NATIVO PARA GRÁFICOS (GRAPH API) ==================================

async def _extract_and_save_charts_via_graph(db: Session, template_id: int, obj: MasterTemplate, service):
    """
    1. Llama a Graph API para extraer los gráficos de Excel Online.
    2. Sube a AWS S3.
    3. Guarda los registros en BD (Media y TemplateCode).
    """
    extracted_charts = {"valora": [], "kapital": []}
    errors = []
    total_charts = 0

    token = await service._get_token()
    base_url = f"https://graph.microsoft.com/v1.0/users/{service.config.user_email}/drive/items/{obj.onedrive_item_id}/workbook"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    target_sheets = TEMPLATE_SHEET_TO_TYPE
    template_prefix = _normalize_template_name(obj.nombre)

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            # 1. Crear sesión de trabajo en Excel Online (RAM)
            session_resp = await client.post(f"{base_url}/createSession", headers=headers, json={"persistChanges": False})
            session_resp.raise_for_status()
            headers["workbook-session-id"] = session_resp.json()["id"]

            for sheet_name, template_type in target_sheets.items():
                encoded_sheet = quote(sheet_name)
                charts_url = f"{base_url}/worksheets('{encoded_sheet}')/charts"
                charts_resp = await client.get(charts_url, headers=headers)

                if charts_resp.status_code != 200:
                    errors.append(f"No se pudo acceder a la hoja '{sheet_name}'")
                    continue

                charts_data = charts_resp.json().get("value", [])
                for chart in charts_data:
                    chart_title = chart.get("name")
                    if not chart_title:
                        continue
                    total_charts += 1

                    # 2. Descargar imagen PNG del gráfico
                    try:
                        encoded_chart = quote(chart_title)
                        image_url = f"{base_url}/worksheets('{encoded_sheet}')/charts('{encoded_chart}')/image"
                        image_resp = await client.get(image_url, headers=headers)
                        image_resp.raise_for_status()

                        b64_str = image_resp.json().get("value")
                        if not b64_str:
                            continue
                        image_bytes = base64.b64decode(b64_str)
                    except Exception as e:
                        errors.append(f"Error descargando gráfico '{chart_title}': {e}")
                        continue

                    # 3. Normalizar código y preparar nombres
                    normalized_code = normalize_code(chart_title)
                    if not normalized_code:
                        continue

                    code_without_dollars = normalized_code.replace("$$", "")
                    prefixed_filename = f"{template_prefix}-{template_type.upper()}-{code_without_dollars}.png"

                    # 4. Subir a S3
                    file_url, object_key = None, None
                    stored_size = len(image_bytes)
                    try:
                        upload_file = SimpleUploadFile(prefixed_filename, io.BytesIO(image_bytes))
                        s3_result = s3_service.upload_file(upload_file, folder="graphs")
                        file_url = s3_result["file_url"]
                        object_key = s3_result["object_key"]
                    except Exception as e:
                        errors.append(f"Error subiendo a S3 '{prefixed_filename}': {e}")

                    resolved_url, resolved_storage_path = _resolve_media_fields(
                        template_id, prefixed_filename.replace('.png', ''), prefixed_filename, file_url, object_key
                    )

                    # 5. Guardar/Actualizar en tabla Media
                    existing_media = db.execute(
                        select(Media).where(
                            (Media.filename == prefixed_filename) &
                            (Media.folder.like(f"%master-templates/{template_id}%")) &
                            (Media.deleted_at.is_(None))
                        )
                    ).scalars().first()

                    media_meta = {
                        "chart_code": normalized_code,
                        "chart_title": chart_title,
                        "template_id": template_id,
                        "template_type": template_type,
                        "template_name": obj.nombre,
                        "size": stored_size,
                    }

                    if existing_media:
                        media_obj = existing_media
                        media_obj.original_name = chart_title
                        media_obj.mime_type = "image/png"
                        media_obj.size = stored_size
                        media_obj.url = resolved_url
                        media_obj.storage_path = resolved_storage_path
                        media_obj.folder = f"master-templates/{template_id}/{template_type}"
                        media_obj.meta = media_meta
                    else:
                        media_obj = Media(
                            filename=prefixed_filename, original_name=chart_title, mime_type="image/png",
                            size=stored_size, url=resolved_url, storage_path=resolved_storage_path,
                            folder=f"master-templates/{template_id}/{template_type}", meta=media_meta
                        )
                        db.add(media_obj)

                    db.flush()

                    # 6. Guardar/Actualizar en tabla TemplateCode
                    code_enum = CalculationType(template_type)
                    existing_tc = db.execute(
                        select(TemplateCode).where(
                            (TemplateCode.code == normalized_code) &
                            (TemplateCode.type == code_enum) & (TemplateCode.deleted_at.is_(None))
                        )
                    ).scalars().first()

                    if existing_tc:
                        tc = existing_tc
                        tc.nombre = chart_title
                        tc.hoja = sheet_name
                    else:
                        tc = TemplateCode(code=normalized_code, nombre=chart_title, type=code_enum, hoja=sheet_name)
                        db.add(tc)

                    _link_code_to_master_template(obj, tc)
                    tc.template_code_image_id = media_obj.id
                    db.commit()

                    # Guardar respuesta final para el frontend
                    extracted_charts[template_type].append({
                        "code": normalized_code,
                        "filename": prefixed_filename,
                        "original_name": chart_title,
                        "url": resolved_url,
                        "size": stored_size,
                        "type": template_type,
                        "error": None if file_url else "S3 upload failed"
                    })

        except Exception as e:
            logger.error(f"[GraphAPI] Error general en extracción: {e}", exc_info=True)
            errors.append(str(e))
        finally:
            if "workbook-session-id" in headers:
                try:
                    await client.post(f"{base_url}/closeSession", headers=headers)
                except Exception:
                    pass

    return extracted_charts, total_charts, errors


# ==============================================================================
# RESTO DE RUTAS GENERALES
# ==============================================================================

@router.get("/uploaded-files")
def list_uploaded_files(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    query = select(MasterTemplate).where(
        (MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.onedrive_item_id.isnot(None)) & (MasterTemplate.created_by_user_id == current_user.id)
    ).order_by(MasterTemplate.created_at.desc())

    return [{"id": t.id, "filename": t.onedrive_filename or f"plantilla_{t.id}.xlsx", "template_id": t.id, "template_name": t.nombre, "size": 0, "uploaded_at": t.updated_at.isoformat() if t.updated_at else t.created_at.isoformat(), "onedrive_item_id": t.onedrive_item_id} for t in db.execute(query).scalars().all()]


@router.delete("/uploaded-files/{file_id}")
async def delete_uploaded_file(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    obj = db.get(MasterTemplate, file_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    if obj.created_by_user_id != current_user.id:
        raise HTTPException(403, "Sin permisos")
    if not obj.onedrive_item_id:
        raise HTTPException(400, "No tiene archivo en OneDrive")

    service = get_onedrive_service()
    if OneDriveConfig().is_configured():
        try: await service.delete_file(obj.onedrive_item_id)
        except Exception as exc:
            logger.warning(f"Error OneDrive: {exc}")

    try:
        obj.onedrive_item_id, obj.onedrive_filename, obj.onedrive_path, obj.onedrive_env, obj.onedrive_folder = None, None, None, None, None
        obj.template_codes = []
        db.commit()
        return {"status": "deleted", "message": "Archivo eliminado correctamente"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, str(exc)) from exc


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
            if chart_path: break

    if not chart_path or not chart_path.exists(): raise HTTPException(404, f"Chart image not found: {chart_filename}")
    return StreamingResponse(open(chart_path, "rb"), media_type="image/png" if chart_path.suffix.lower() == ".png" else "image/jpeg", headers={"Content-Disposition": f'inline; filename="{chart_path.name}"'})


@router.get("/onedrive/files")
async def list_onedrive_files(folder: str = "plantillas_maestras"):
    env = settings.ENVIRONMENT
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        files = await service.list_files(env=env, folder=folder)
        return {"env": env, "folder": folder, "files": files}
    except Exception as exc:
        raise HTTPException(502, f"Error al listar archivos: {exc}") from exc


@router.delete("/onedrive/files/{item_id}")
async def delete_onedrive_file(item_id: str):
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        await service.delete_file(item_id)
        return {"status": status.HTTP_200_OK, "message": f"Archivo {item_id} eliminado."}
    except Exception as exc:
        raise HTTPException(502, f"Error al eliminar: {exc}") from exc


@router.post("/onedrive/setup")
async def setup_onedrive():
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        structure = {
            "PLATAFORMAS_FINANCIERAS": {
                "development": ["plantillas_maestras", "kapital", "valora"],
                "production": ["plantillas_maestras", "kapital", "valora"],
                "test": ["plantillas_maestras", "kapital", "valora"],
            }
        }
        await service.ensure_folder_structure(structure=structure)
        return {"status": status.HTTP_200_OK, "message": "Estructura de carpetas creada."}
    except Exception as exc:
        raise HTTPException(502, f"Error al crear estructura: {exc}") from exc


@router.post("", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_master_template(payload: MasterTemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):

    if not payload.nombre or len(payload.nombre) < 3:
        raise HTTPException(422, "Nombre requiere >= 3 caracteres")

    user_templates_count = db.execute(select(MasterTemplate.id).where((MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.created_by_user_id == current_user.id))).all()
    should_be_default = payload.is_default or len(user_templates_count) == 0
    if should_be_default: 
        _clear_user_default_templates(db, current_user.id)

    obj = MasterTemplate(nombre=payload.nombre.strip(), description=payload.description.strip() if payload.description else None, is_active=payload.is_active, is_default=should_be_default, hojas_config=payload.hojas_config, created_by_user_id=current_user.id)
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
    filename = file.filename or f"plantilla_{template_id}.xlsx"
    try:
        item = await service.upload_file(content=content, filename=filename, env=env, folder=folder)
    except Exception as e:
        raise HTTPException(502, f"Error OneDrive: {e}")

    obj.onedrive_env, obj.onedrive_folder, obj.onedrive_item_id = env, folder, item.get("id")
    obj.onedrive_filename, obj.onedrive_path = filename, service.build_path(env, folder, filename)
    db.commit()
    db.refresh(obj)

    # 2. EXTRAER TEXT CODES
    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content)

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
async def re_upload_and_extract_codes(template_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")): 
        raise HTTPException(422, "Solo Excel")
    content = await file.read()
    if not content:
        raise HTTPException(422, "Vacío")

    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")

    # ====== 1. SNAPSHOT PREVIO - Capturar códigos EXISTENTES DE ESTA PLANTILLA ======
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

    # ====== 2. HARD-DELETE del estado anterior ======
    # 1. Desvincularse: Soft-delete de TemplateCode y desvincularse de Media
    for code in obj.template_codes:
        if code:
            code.template_code_image_id = None  # Desvincularse de Media
            code.deleted_at = datetime.utcnow()

    obj.template_codes = []
    db.commit()  # Commit para guardar desvinculos antes de borrar Media

    # 2. Hard-delete de Media (eliminar completamente los gráficos viejos BD + S3)
    for m in db.execute(
        select(Media).where(
            (Media.deleted_at.is_(None)) & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
    ).scalars().all():
        # Eliminar archivo de S3 si existe
        if m.storage_path:
            try:
                s3_service.delete_file(m.storage_path)
            except Exception as e:
                logger.warning(f"Error eliminando archivo S3 {m.storage_path}: {e}")
        # Eliminar registro de BD
        db.delete(m)

    db.commit()

    # ====== 3. Reemplazar archivo en OneDrive ======
    service = get_onedrive_service()
    if obj.onedrive_item_id:
        try: 
            await service.delete_file(obj.onedrive_item_id)
        except Exception:
            pass

    filename = file.filename or f"plantilla_{template_id}.xlsx"
    env: Environment = settings.ENVIRONMENT
    item = await service.upload_file(content=content, filename=filename, env=env, folder=obj.onedrive_folder or "plantillas_maestras")
    obj.onedrive_item_id, obj.onedrive_filename, obj.onedrive_path = item.get("id"), filename, service.build_path(env, obj.onedrive_folder or "plantillas_maestras", filename)
    db.commit()

    # ====== 4. Extraer e insertar NUEVOS códigos de celdas ======
    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content)

    _, new_codes = _process_and_save_cell_codes(db, obj, extraction_result, old_code_sets)

    # ====== 5. Extraer e insertar gráficos (Motor Graph API) ======
    extracted_charts, _, chart_errors = await _extract_and_save_charts_via_graph(db, template_id, obj, service)
    new_images = {"valora": [], "kapital": []}

    for template_type, charts in extracted_charts.items():
        for chart in charts:
            if chart["filename"] not in old_image_sets[template_type]:
                new_images[template_type].append(chart["filename"])

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

    filename = obj.onedrive_filename or f"plantilla_{obj.id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
