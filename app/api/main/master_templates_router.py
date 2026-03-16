# app/api/main/master_templates_router.py
"""
CRUD de Plantillas Maestras + integración OneDrive.
Cada plantilla maestra es un archivo Excel (version-XX.XX.XX.xlsx) que
define el modelo financiero. Se sube a OneDrive y se gestiona desde aquí.
"""
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional, Literal

from app.db.database import get_db
from app.models.main import MasterTemplate
from app.schemas.main import (
    MasterTemplateCreate, MasterTemplateUpdate, MasterTemplateResponse,
)
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig
from app.core.config import settings

router = APIRouter(prefix="/main/master-templates", tags=["Master Templates"])

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]


# === LIST =====================================================================
@router.get("", response_model=List[MasterTemplateResponse])
def list_master_templates(
    template_type: Optional[Literal["valora", "kapital"]] = None,
    db: Session = Depends(get_db),
):
    query = select(MasterTemplate).where(MasterTemplate.deleted_at.is_(None))
    if template_type:
        query = query.where(MasterTemplate.type == template_type)
    query = query.order_by(MasterTemplate.created_at.desc())
    results = db.execute(query).scalars().all()
    return [MasterTemplateResponse.model_validate(r) for r in results]


# === GET ONE ==================================================================
@router.get("/{template_id}", response_model=MasterTemplateResponse)
def get_master_template(template_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    return MasterTemplateResponse.model_validate(obj)


# === CREATE ===================================================================
@router.post("", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_master_template(payload: MasterTemplateCreate, db: Session = Depends(get_db)):
    """
    Crea una nueva plantilla maestra (sin subir archivo).
    Para subir archivo, usar POST /{template_id}/upload después.
    """
    obj = MasterTemplate(
        nombre=payload.nombre,
        version=payload.version,
        description=payload.description,
        type=payload.type,
        is_active=payload.is_active,
        hojas_config=payload.hojas_config,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


# === CREATE + UPLOAD ==========================================================
@router.post("/create-and-upload", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_and_upload_master_template(
    nombre: str = Form(..., description="Nombre de la plantilla"),
    version: str = Form(..., description="Versión (ej: v2.1.0)"),
    template_type: Literal["valora", "kapital"] = Form(..., description="Tipo de plantilla"),
    file: UploadFile = File(..., description="Archivo Excel"),
    folder: Folder = Form("plantillas_maestras", description="Carpeta de destino"),
    description: str = Form("", description="Descripción opcional"),
    hojas_config: str = Form("{}", description="Metadata de hojas en JSON"),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
):
    """
    Crea una plantilla maestra Y sube el archivo a OneDrive en una sola petición.
    El ambiente se toma automáticamente de la variable ENVIRONMENT del servidor.
    
    Multipart request con:
      - nombre, version, template_type, description, etc
      - file: Excel a subir
      - folder: plantillas_maestras | kapital | valora
    
    Retorna la plantilla con OneDrive metadata.
    """
    env: Environment = settings.ENVIRONMENT

    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )

    # 1. Subir archivo a OneDrive
    content = await file.read()
    filename = file.filename or f"plantilla_{version}.xlsx"

    try:
        item = await service.upload_file(
            content=content,
            filename=filename,
            env=env,
            folder=folder,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al subir a OneDrive: {e}"
        )
    
    # 2. Parsear hojas_config JSON
    try:
        hojas_config_dict = json.loads(hojas_config) if hojas_config and hojas_config != "{}" else {}
    except json.JSONDecodeError:
        hojas_config_dict = {}
    
    # 3. Crear plantilla maestra en BD
    obj = MasterTemplate(
        nombre=nombre,
        version=version,
        description=description or "",
        type=template_type,
        is_active=is_active,
        hojas_config=hojas_config_dict,
        # OneDrive metadata
        onedrive_env=env,
        onedrive_folder=folder,
        onedrive_item_id=item.get("id"),
        onedrive_filename=filename,
        onedrive_path=service.build_path(env, folder, filename),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
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
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")
    obj.deleted_at = datetime.utcnow()
    db.commit()
    return None


# === UPLOAD TO ONEDRIVE =======================================================
@router.post("/{template_id}/upload", response_model=MasterTemplateResponse)
async def upload_to_onedrive(
    template_id: int,
    file: UploadFile = File(...),
    folder: Folder = Form("plantillas_maestras"),
    db: Session = Depends(get_db),
):
    """
    Sube el archivo Excel a OneDrive y guarda el item_id en la plantilla.
    El ambiente se toma automáticamente de la variable ENVIRONMENT del servidor.
    El frontend envía:
      - file: el .xlsx
      - folder: plantillas_maestras | kapital | valora
    """
    env: Environment = settings.ENVIRONMENT
    obj = db.get(MasterTemplate, template_id)
    if not obj or obj.deleted_at:
        raise HTTPException(404, "Master template not found")

    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "OneDrive no está configurado. Agrega AZURE_CLIENT_ID, "
                "AZURE_CLIENT_SECRET, AZURE_TENANT_ID y ONEDRIVE_USER_EMAIL "
                "en las variables de entorno."
            ),
        )

    content = await file.read()
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

    # Persiste metadatos OneDrive en la plantilla
    obj.onedrive_env = env
    obj.onedrive_folder = folder
    obj.onedrive_item_id = item.get("id")
    obj.onedrive_filename = filename
    obj.onedrive_path = service.build_path(env, folder, filename)
    db.commit()
    db.refresh(obj)
    return MasterTemplateResponse.model_validate(obj)


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


# === LIST ONEDRIVE FILES ======================================================
@router.get("/onedrive/files")
async def list_onedrive_files(
    folder: Folder = "plantillas_maestras",
):
    """Lista los archivos en OneDrive (sin filtrar por BD). El ambiente se toma del servidor."""
    env: Environment = settings.ENVIRONMENT
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        files = await service.list_files(env=env, folder=folder)
        return {"env": env, "folder": folder, "files": files}
    except Exception as e:
        raise HTTPException(502, f"Error al listar archivos en OneDrive: {e}")


# === DELETE ONEDRIVE FILE =====================================================
@router.delete("/onedrive/files/{item_id}")
async def delete_onedrive_file(item_id: str):
    """Elimina un archivo de OneDrive por su item_id."""
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        await service.delete_file(item_id)
        return {"status": "ok", "message": f"Archivo {item_id} eliminado de OneDrive."}
    except Exception as e:
        raise HTTPException(502, f"Error al eliminar archivo de OneDrive: {e}")


# ==== SETUP ONEDRIVE STRUCTURE ==================
@router.post("/onedrive/setup")
async def setup_onedrive():
    """Crea la estructura de carpetas en OneDrive si no existe."""
    service = get_onedrive_service()
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(503, "OneDrive no está configurado.")
    try:
        await service.ensure_folder_structure(structure={"development": ["plantillas_maestras", "kapital", "valora"], "production": ["plantillas_maestras", "kapital", "valora"], "test": ["plantillas_maestras", "kapital", "valora"]})
        return {"status": "ok", "message": "Estructura de carpetas creada en OneDrive."}
    except Exception as e:
        raise HTTPException(502, f"Error al crear estructura: {e}")
