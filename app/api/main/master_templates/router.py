# app/api/main/master_templates_router.py
"""
CRUD de Plantillas Maestras almacenadas en S3 y procesadas con Excel COM.
"""

import asyncio
import io
import logging
import time
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.api.main.master_templates.services import (
    _chart_candidate_dirs,
    _clear_user_default_templates,
    _ensure_user_has_default_template,
    _extract_and_save_charts_via_com,
    _process_and_save_cell_codes,
)
from app.core.config import settings
from app.db.database import get_db
from app.models.cms import Media
from app.models.main import CalculationType, TemplateCode
from app.models.templates import MasterTemplate
from app.models.user import User
from app.schemas.templates import (
    MasterTemplateCreate,
    MasterTemplateResponse,
    MasterTemplateUpdate,
    PaginatedMasterTemplateResponse,
    TemplateCodeResponse,
)
from app.services.aws_service import s3_service
from app.services.template_code_extractor import get_template_code_extractor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main/master-templates",
    tags=["Master Templates"],
    dependencies=[Depends(get_current_admin)],
)
public_media_router = APIRouter(prefix="/main/master-templates/media", tags=["Media"])

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]
MASTER_TEMPLATE_S3_FOLDER = settings.MASTER_TEMPLATE_FOLDER

# =============================
# RESTO DE RUTAS GENERALES
# =============================


class ValoraCopyListItem(BaseModel):
    id: str
    name: str
    size: Optional[int] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    web_url: Optional[str] = None
    download_url: Optional[str] = None
    env: str
    folder: Optional[str] = None


class ValoraCopyListResponse(BaseModel):
    items: list[ValoraCopyListItem]
    env: str


@router.get("/valora-copies", response_model=ValoraCopyListResponse)
async def list_valora_copies(
    env: Optional[Environment] = None,
    include_kapital: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Lista las copias de trabajo de cálculos Valora (y opcionalmente Kapital)
    que existen en S3 bajo templates/tmps/. Solo muestra lo generado
    desde la versión actual basada en S3.
    """
    target_env = env or settings.ENVIRONMENT or "development"
    folders_to_list = ["valora"]
    if include_kapital:
        folders_to_list.append("kapital")

    base_prefix = s3_service.base_prefix  # ej: plataformas_financieras
    enriched = []
    for folder in folders_to_list:
        prefix = f"{base_prefix}/templates/tmps/{folder}/"
        logger.info(f"[VALORA COPIES S3] Listando prefix={prefix}")
        try:
            files = await asyncio.to_thread(s3_service.list_files, prefix)
        except Exception as exc:
            logger.exception(f"Error listando copias {folder} en S3")
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo listar copias de {folder}: {exc}",
            ) from exc

        logger.info(f"[VALORA COPIES S3] Folder={folder} files={len(files)}")
        for f in files:
            object_key = f.get("object_key") or ""
            filename = object_key.rsplit("/", 1)[-1] if object_key else ""
            last_modified = f.get("last_modified")
            if hasattr(last_modified, "isoformat"):
                modified_at = last_modified.isoformat()
            else:
                modified_at = str(last_modified) if last_modified else None
            download_url = ""
            try:
                download_url = await asyncio.to_thread(
                    s3_service.generate_presigned_url, object_key
                )
            except Exception:
                logger.warning(f"No se pudo generar download_url para {object_key}")

            enriched.append(
                {
                    "id": object_key,
                    "name": f"[{folder.upper()}] {filename}",
                    "size": f.get("size"),
                    "created_at": modified_at,
                    "modified_at": modified_at,
                    "web_url": download_url,
                    "download_url": download_url,
                    "env": target_env,
                    "folder": folder,
                }
            )

    def _sort_key(x):
        try:
            if x.get("modified_at"):
                return datetime.fromisoformat(
                    x["modified_at"].replace("Z", "+00:00")
                )
        except Exception:
            pass
        return datetime.min.replace(tzinfo=None)

    # Ordenar: más reciente primero, fallback por nombre si no hay fecha
    enriched.sort(key=_sort_key, reverse=True)

    return {"items": enriched, "env": target_env}


def _validate_tmps_key(object_key: str) -> str:
    """Solo permite borrar/descargar copias de templates/tmps/valora|kapital."""
    base_prefix = s3_service.base_prefix
    allowed = (
        f"{base_prefix}/templates/tmps/valora/",
        f"{base_prefix}/templates/tmps/kapital/",
    )
    if not object_key or not object_key.startswith(allowed):
        raise HTTPException(status_code=400, detail="Object key no permitido")
    if ".." in object_key or object_key.endswith("/"):
        raise HTTPException(status_code=400, detail="Object key no válido")
    return object_key


@router.delete("/valora-copies/{item_id:path}")
async def delete_valora_copy(
    item_id: str,
    env: Optional[Environment] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Elimina una copia de trabajo Valora/Kapital de S3."""
    from urllib.parse import unquote

    object_key = _validate_tmps_key(unquote(item_id))

    try:
        ok = await asyncio.to_thread(s3_service.delete_file, object_key)
    except Exception as exc:
        logger.exception(f"Error eliminando copia S3 {object_key}")
        raise HTTPException(
            status_code=502, detail=f"No se pudo eliminar la copia: {exc}"
        ) from exc

    if not ok:
        raise HTTPException(status_code=502, detail="No se pudo eliminar la copia en S3")

    return {"success": True, "deleted_id": object_key}


@router.post("/valora-copies/delete-batch")
async def delete_valora_copies_batch(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Elimina múltiples copias de trabajo Valora/Kapital de S3.
    Body: {"ids": ["object_key_1", "object_key_2", ...]}
    """
    from urllib.parse import unquote

    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="No se enviaron IDs")

    deleted = []
    failed = []

    for raw_id in ids:
        try:
            object_key = _validate_tmps_key(unquote(str(raw_id)))
            ok = await asyncio.to_thread(s3_service.delete_file, object_key)
            if not ok:
                raise RuntimeError("S3 devolvió False al eliminar")
            deleted.append(object_key)
        except HTTPException as exc:
            failed.append({"id": str(raw_id), "error": exc.detail})
        except Exception as exc:
            logger.warning(f"Error eliminando copia {raw_id}: {exc}")
            failed.append({"id": str(raw_id), "error": str(exc)})

    return {"success": len(failed) == 0, "deleted": deleted, "failed": failed}


@router.get("/valora-copies/{item_id:path}/download-url")
async def get_valora_copy_download_url(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Devuelve una URL temporal (presigned S3) para descargar una copia."""
    from urllib.parse import unquote

    object_key = _validate_tmps_key(unquote(item_id))

    try:
        url = await asyncio.to_thread(s3_service.generate_presigned_url, object_key)
    except Exception as exc:
        logger.exception(f"Error obteniendo URL de copia S3 {object_key}")
        raise HTTPException(
            status_code=502, detail=f"No se pudo obtener URL: {exc}"
        ) from exc

    return {"download_url": url, "item_id": object_key}


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
                matches = sorted(
                    base_dir.glob(f"*-{chart_filename}.{ext}"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if matches:
                    chart_path = matches[0]
                    break
            if chart_path:
                break

    if not chart_path or not chart_path.exists():
        raise HTTPException(404, f"Chart image not found: {chart_filename}")
    return StreamingResponse(
        open(chart_path, "rb"),
        media_type="image/png" if chart_path.suffix.lower() == ".png" else "image/jpeg",
        headers={"Content-Disposition": f'inline; filename="{chart_path.name}"'},
    )


@router.get("/media/{media_id}")
def get_template_media(media_id: int, db: Session = Depends(get_db)):
    """Serve a template image through the API so browsers need no S3 CORS."""
    media = db.get(Media, media_id)
    if not media or media.deleted_at or not media.storage_path:
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        content = s3_service.download_file_bytes(media.storage_path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Media unavailable") from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{media.filename}"'},
    )


@public_media_router.get("/{media_id}")
def get_public_template_media(media_id: int, db: Session = Depends(get_db)):
    return get_template_media(media_id, db)


@router.post(
    "", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED
)
def create_master_template(
    payload: MasterTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):

    if not payload.nombre or len(payload.nombre) < 3:
        raise HTTPException(422, "Nombre requiere >= 3 caracteres")

    user_templates_count = db.execute(
        select(MasterTemplate.id).where(
            (MasterTemplate.deleted_at.is_(None))
            & (MasterTemplate.created_by_user_id == current_user.id)
        )
    ).all()
    should_be_default = payload.is_default or len(user_templates_count) == 0
    if should_be_default:
        _clear_user_default_templates(db, current_user.id)

    obj = MasterTemplate(
        nombre=payload.nombre.strip(),
        description=payload.description.strip() if payload.description else None,
        is_default=should_be_default,
        created_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


@router.get("", response_model=PaginatedMasterTemplateResponse)
def list_master_templates(
    limit: int = 10,
    offset: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    query = select(MasterTemplate).where(
        (MasterTemplate.deleted_at.is_(None))
        & (MasterTemplate.created_by_user_id == current_user.id)
    )
    if search:
        query = query.where(
            or_(
                MasterTemplate.nombre.ilike(f"%{search}%"),
                MasterTemplate.description.ilike(f"%{search}%"),
            )
        )

    total_query = select(MasterTemplate.id).where(
        (MasterTemplate.deleted_at.is_(None))
        & (MasterTemplate.created_by_user_id == current_user.id)
    )
    if search:
        total_query = total_query.where(
            or_(
                MasterTemplate.nombre.ilike(f"%{search}%"),
                MasterTemplate.description.ilike(f"%{search}%"),
            )
        )

    total_count = len(db.execute(total_query).all())
    pages = (total_count + limit - 1) // limit if limit > 0 else 1
    page = (offset // limit) + 1 if limit > 0 else 1

    templates = (
        db.execute(
            query.order_by(MasterTemplate.created_at.desc()).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "items": [MasterTemplateResponse.model_validate(t) for t in templates],
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.get("/{template_id}", response_model=MasterTemplateResponse)
def get_master_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
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
def delete_master_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Not found")

    _name = getattr(obj, "nombre", f"id={template_id}")
    _s3_key = getattr(obj, "s3_object_key", None)
    logger.info('[S3 MASTER TEMPLATE] 🗑️ Solicitud borrar plantilla "%s" template_id=%s s3_key=%s', _name, template_id, _s3_key)
    print(f'[S3 MASTER TEMPLATE] 🗑️ Solicitud borrar plantilla "{_name}" template_id={template_id} s3_key={_s3_key}', flush=True)

    media_rows = (
        db.execute(
            select(Media).where(
                (Media.deleted_at.is_(None))
                & (Media.folder.like(f"%master-templates/{template_id}%"))
            )
        )
        .scalars()
        .all()
    )
    codes_to_soft_delete = {
        f"$${str(m.meta.get('chart_code')).replace('$$', '').upper()}$$"
        for m in media_rows
        if m.meta and m.meta.get("chart_code")
    }
    for m in media_rows:
        m.deleted_at = datetime.utcnow()

    if codes_to_soft_delete:
        for code_row in (
            db.execute(
                select(TemplateCode).where(
                    (TemplateCode.deleted_at.is_(None))
                    & (TemplateCode.code.in_(list(codes_to_soft_delete)))
                )
            )
            .scalars()
            .all()
        ):
            code_row.deleted_at = datetime.utcnow()

    obj.template_codes = []
    obj.deleted_at = datetime.utcnow()
    obj.is_default = False
    _ensure_user_has_default_template(db, current_user.id)

    # Eliminar archivo principal de S3 si existe (Templates/masters)
    if _s3_key:
        try:
            ok = s3_service.delete_file(_s3_key)
            if ok:
                logger.info('[S3 MASTER TEMPLATE] 🗑️ S3 eliminó el archivo "%s" template_id=%s key=%s', _name, template_id, _s3_key)
                print(f'[S3 MASTER TEMPLATE] 🗑️ S3 eliminó el archivo "{_name}" template_id={template_id} key={_s3_key}', flush=True)
            else:
                logger.warning('[S3 MASTER TEMPLATE] ⚠️ S3 no pudo eliminar "%s" key=%s', _name, _s3_key)
                print(f'[S3 MASTER TEMPLATE] ⚠️ S3 no pudo eliminar "{_name}" key={_s3_key}', flush=True)
        except Exception as exc:
            logger.warning('[S3 MASTER TEMPLATE] ⚠️ Error borrando S3 "%s" key=%s: %s', _name, _s3_key, exc)
            print(f'[S3 MASTER TEMPLATE] ⚠️ Error borrando S3 "{_name}" key={_s3_key}: {exc}', flush=True)
    else:
        logger.info('[S3 MASTER TEMPLATE] 🗑️ Plantilla "%s" template_id=%s borrada (sin archivo S3 asociado)', _name, template_id)
        print(f'[S3 MASTER TEMPLATE] 🗑️ Plantilla "{_name}" template_id={template_id} borrada (sin archivo S3 asociado)', flush=True)

    db.commit()
    return None


# ==============================================================================
# RUTAS DE PROCESAMIENTO REFACTORIZADAS
# ==============================================================================


@router.post("/{template_id}/upload")
async def upload_and_extract_codes(
    template_id: int,
    file: UploadFile = File(...),
    folder: Folder = Form("plantillas_maestras"),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
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
    old_media_rows = (
        db.execute(
            select(Media).where(
                (Media.deleted_at.is_(None))
                & (Media.folder.like(f"%master-templates/{template_id}%"))
            )
        )
        .scalars()
        .all()
    )

    for media in old_media_rows:
        mt = (
            media.meta.get("template_type", "valora")
            if media.meta
            else ("kapital" if "kapital" in (media.folder or "").lower() else "valora")
        )
        c = (
            str(
                media.meta.get(
                    "chart_code", media.filename.replace(".png", "").replace(".jpg", "")
                )
            )
            .replace("$$", "")
            .upper()
        )
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

    # S3 is the canonical storage for new master templates.
    original_name = file.filename or f"plantilla_{template_id}.xlsx"
    storage_name = f"{template_id}-{original_name}"
    obj.original_filename = original_name
    try:
        s3_result = await asyncio.to_thread(
            s3_service.upload_bytes,
            content,
            storage_name,
            f"{MASTER_TEMPLATE_S3_FOLDER}/{template_id}",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        obj.s3_object_key = s3_result["object_key"]
        logger.info('[S3 MASTER TEMPLATE] ✅ S3 recibió el archivo "%s" template_id=%s key=%s bytes=%s', obj.nombre, template_id, obj.s3_object_key, len(content))
        print(f'[S3 MASTER TEMPLATE] ✅ S3 recibió el archivo "{obj.nombre}" template_id={template_id} key={obj.s3_object_key} bytes={len(content)}', flush=True)
    except Exception as exc:
        logger.exception('[S3 MASTER TEMPLATE] ❌ Error S3 al recibir "%s" template_id=%s: %s', obj.nombre, template_id, exc)
        print(f'[S3 MASTER TEMPLATE] ❌ Error S3 al recibir "{obj.nombre}" template_id={template_id}: {exc}', flush=True)
        raise HTTPException(502, f"Error S3: {exc}") from exc

    db.commit()
    db.refresh(obj)

    # 2. EXTRAER TEXT CODES
    extractor = get_template_code_extractor()
    extraction_result = await asyncio.to_thread(extractor.extract_from_bytes, content)

    new_codes, _ = _process_and_save_cell_codes(
        db, obj, extraction_result, old_code_sets
    )

    # 3. EXTRAER GRÁFICOS (GRAPH API)
    (
        extracted_chart_images,
        total_charts,
        chart_errors,
    ) = await _extract_and_save_charts_via_com(db, template_id, obj, content)
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
            "errors": chart_errors,
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
    template_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
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
    t0 = time.perf_counter()  # time
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
    old_media_rows = (
        db.execute(
            select(Media).where(
                (Media.deleted_at.is_(None))
                & (Media.folder.like(f"%master-templates/{template_id}%"))
            )
        )
        .scalars()
        .all()
    )

    for m in old_media_rows:
        mt = (
            m.meta.get("template_type", "valora")
            if m.meta
            else ("kapital" if "kapital" in (m.folder or "").lower() else "valora")
        )
        c = (
            str(
                m.meta.get(
                    "chart_code", m.filename.replace(".png", "").replace(".jpg", "")
                )
            )
            .replace("$$", "")
            .upper()
        )
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

    media_to_delete = (
        db.execute(
            select(Media).where(
                (Media.deleted_at.is_(None))
                & (Media.folder.like(f"%master-templates/{template_id}%"))
            )
        )
        .scalars()
        .all()
    )

    # 2. Hard-delete de Media (eliminar completamente los gráficos viejos BD + S3)
    async def delete_s3_file(path):
        try:
            await asyncio.to_thread(s3_service.delete_file, path)
        except Exception as e:
            logger.warning(f"Error eliminando archivo S3 {path}: {e}")

    s3_delete_tasks = [
        delete_s3_file(m.storage_path) for m in media_to_delete if m.storage_path
    ]
    if s3_delete_tasks:
        await asyncio.gather(*s3_delete_tasks)

    # Eliminar registro de BD
    for m in media_to_delete:
        db.delete(m)

    db.commit()

    print(
        f"[TIMER] 2. Hard-Delete (BD + S3 asincrono): {time.perf_counter() - t0:.2f}s"
    )
    # ====== 3. Reemplazar archivo en S3 ======
    t0 = time.perf_counter()
    if obj.s3_object_key:
        _old_key = obj.s3_object_key
        logger.info('[S3 MASTER TEMPLATE] 🔄 Reemplazando archivo "%s" template_id=%s old_key=%s', obj.nombre, template_id, _old_key)
        print(f'[S3 MASTER TEMPLATE] 🔄 Reemplazando archivo "{obj.nombre}" template_id={template_id} old_key={_old_key}', flush=True)
        await asyncio.to_thread(s3_service.delete_file, _old_key)

    original_name = file.filename or f"plantilla_{template_id}.xlsx"
    storage_name = f"{template_id}-{original_name}"
    obj.original_filename = original_name

    try:
        s3_result = await asyncio.to_thread(
            s3_service.upload_bytes,
            content,
            storage_name,
            f"{MASTER_TEMPLATE_S3_FOLDER}/{template_id}",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        obj.s3_object_key = s3_result["object_key"]
        logger.info('[S3 MASTER TEMPLATE] ✅ S3 recibió el archivo "%s" template_id=%s key=%s bytes=%s (re-upload)', obj.nombre, template_id, obj.s3_object_key, len(content))
        print(f'[S3 MASTER TEMPLATE] ✅ S3 recibió el archivo "{obj.nombre}" template_id={template_id} key={obj.s3_object_key} bytes={len(content)} (re-upload)', flush=True)
    except Exception as exc:
        logger.exception('[S3 MASTER TEMPLATE] ❌ Error S3 al recibir "%s" template_id=%s (re-upload): %s', obj.nombre, template_id, exc)
        print(f'[S3 MASTER TEMPLATE] ❌ Error S3 al recibir "{obj.nombre}" template_id={template_id} (re-upload): {exc}', flush=True)
        raise HTTPException(502, f"Error S3: {exc}") from exc

    db.commit()
    print(f"[TIMER] 3. Upload a S3: {time.perf_counter() - t0:.2f}s")

    # ====== 4. Extraer e insertar NUEVOS códigos de celdas ======
    t0 = time.perf_counter()
    extractor = get_template_code_extractor()
    extraction_result = await asyncio.to_thread(extractor.extract_from_bytes, content)

    _, new_codes = _process_and_save_cell_codes(
        db, obj, extraction_result, old_code_sets
    )
    print(
        f"[TIMER] 4. Extracción Celdas (Openpyxl + BD): {time.perf_counter() - t0:.2f}s"
    )

    # ====== 5. Extraer e insertar gráficos (Excel COM + S3) ======
    t0 = time.perf_counter()
    extracted_charts, _, chart_errors = await _extract_and_save_charts_via_com(
        db, template_id, obj, content
    )
    new_images = {"valora": [], "kapital": []}

    for template_type, charts in extracted_charts.items():
        for chart in charts:
            if chart["filename"] not in old_image_sets[template_type]:
                new_images[template_type].append(chart["filename"])

    print(
        f"[TIMER] 5. Extracción Gráficos (Excel COM + S3): {time.perf_counter() - t0:.2f}s"
    )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Master template not found"
        )

    if not obj.s3_object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta plantilla no tiene archivo subido a S3. Use POST /upload primero.",
        )

    try:
        content = await asyncio.to_thread(
            s3_service.download_file_bytes, obj.s3_object_key
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al descargar de S3: {e}",
        )

    extractor = get_template_code_extractor()
    extraction_result = extractor.extract_from_bytes(content)

    created_codes, _ = _process_and_save_cell_codes(db, obj, extraction_result)

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "template_version": obj.original_filename,
        "codes": created_codes,
        "chart_stats": {
            "total": 0,
            "valora": 0,
            "kapital": 0,
            "errors": ["La extracción de gráficos requiere migración a S3/COM."],
        },
        "statistics": extractor.get_statistics(extraction_result),
        "success": True,
    }


@router.post("/{template_id}/extract-charts")
async def extract_template_charts(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Master template not found"
        )
    if not obj.s3_object_key:
        raise HTTPException(400, "Esta plantilla no tiene archivo disponible en S3.")
    content = await asyncio.to_thread(s3_service.download_file_bytes, obj.s3_object_key)
    (
        extracted_charts,
        total_charts,
        chart_errors,
    ) = await _extract_and_save_charts_via_com(db, template_id, obj, content)

    return {
        "template_id": template_id,
        "template_name": obj.nombre,
        "valora": extracted_charts.get("valora", []),
        "kapital": extracted_charts.get("kapital", []),
        "total": len(extracted_charts.get("valora", []))
        + len(extracted_charts.get("kapital", [])),
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

    selected_codes = [
        code for code in obj.template_codes if code and code.deleted_at is None
    ]

    if not selected_codes:
        logger.info(
            "[Codes] No linked codes found for template %s, using backward-compatible fallback",
            template_id,
        )

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
            if obj.s3_object_key:
                content = await asyncio.to_thread(
                    s3_service.download_file_bytes, obj.s3_object_key
                )
                extractor = get_template_code_extractor()
                extraction_result = extractor.extract_from_bytes(content)

                for t in ["valora", "kapital"]:
                    for item in extraction_result.get(t, []):
                        raw_code = item.get("code", "")
                        if raw_code:
                            allowed_codes.add(
                                f"$${raw_code.replace('$$', '').upper()}$$"
                            )
        except Exception as exc:
            logger.warning(
                "[Codes] Could not extract fallback codes from S3 file for template %s: %s",
                template_id,
                exc,
            )

        if allowed_codes:
            selected_codes = (
                db.execute(
                    select(TemplateCode).where(
                        (TemplateCode.deleted_at.is_(None))
                        & (TemplateCode.code.in_(list(allowed_codes)))
                    )
                )
                .scalars()
                .all()
            )

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
            image_url = (
                f"/api/v1/main/master-templates/media/{code.template_code_image.id}"
            )
            if not image_url and code.template_code_image.filename:
                image_stem = code.template_code_image.filename.replace(
                    ".jpg", ""
                ).replace(".png", "")
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
            "coordinate": code.coordinate,
            "source_path": code.source_path,
            "source_format": code.source_format,
            "template_ids": [t.id for t in code.master_templates]
            if hasattr(code, "master_templates")
            else [],
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
        },
    }


@router.get("/{template_id}/chart-images")
def get_template_chart_images(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUNDt, detail="Master template not found"
        )

    query = (
        select(Media)
        .where(
            (Media.deleted_at.is_(None))
            & (Media.folder.like(f"%master-templates/{template_id}%"))
        )
        .order_by(Media.created_at.desc())
    )

    media_files = db.execute(query).scalars().all()

    valora_images = []
    kapital_images = []
    for media in media_files:
        chart_code = (
            media.meta.get(
                "chart_code", media.filename.replace(".jpg", "").replace(".png", "")
            )
            if media.meta
            else media.filename.replace(".jpg", "").replace(".png", "")
        )

        if not chart_code.startswith("$$"):
            chart_code = f"$${chart_code}$$"

        meta = media.meta.copy() if media.meta else {}
        meta["template_id"] = template_id
        meta["template_name"] = obj.nombre

        chart_info = {
            "code": chart_code,
            "filename": media.filename,
            "original_name": media.original_name,
            "url": f"/api/v1/main/master-templates/media/{media.id}",
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
async def download_master_template(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    if obj.s3_object_key:
        try:
            content = await asyncio.to_thread(
                s3_service.download_file_bytes, obj.s3_object_key
            )
            filename = obj.original_filename or f"plantilla_{obj.id}.xlsx"
            return StreamingResponse(
                io.BytesIO(content),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as exc:
            logger.warning("S3 no disponible para plantilla %s: %s", template_id, exc)

    raise HTTPException(404, "Esta plantilla no tiene archivo disponible en S3.")
