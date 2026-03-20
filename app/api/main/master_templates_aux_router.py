import logging
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.deps import get_current_admin
from app.db.database import get_db
from app.models.templates.master_templates import MasterTemplate
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/main/master-templates",
    tags=["Master Templates"],
    dependencies=[Depends(get_current_admin)],
)


def _chart_candidate_dirs() -> list[Path]:
    return [
        Path("/app/public/master-templates-graphs"),
        Path("/app/public/chart-images"),
        Path("./public/master-templates-graphs"),
        Path("./public/chart-images"),
    ]


@router.get("/uploaded-files")
def list_uploaded_files(db: Session = Depends(get_db)):
    query = select(MasterTemplate).where(
        (MasterTemplate.deleted_at.is_(None))
        & (MasterTemplate.onedrive_item_id.isnot(None))
    ).order_by(MasterTemplate.created_at.desc())

    templates = db.execute(query).scalars().all()
    files = []
    for template in templates:
        files.append(
            {
                "id": template.id,
                "filename": template.onedrive_filename or f"plantilla_{template.id}.xlsx",
                "template_id": template.id,
                "template_name": template.nombre,
                "size": 0,
                "uploaded_at": template.updated_at.isoformat() if template.updated_at else template.created_at.isoformat(),
                "onedrive_item_id": template.onedrive_item_id,
            }
        )
    return files


@router.delete("/uploaded-files/{file_id}")
async def delete_uploaded_file(file_id: int, db: Session = Depends(get_db)):
    obj = db.get(MasterTemplate, file_id)
    if not obj or obj.deleted_at:
        raise HTTPException(status_code=404, detail="Master template not found")

    if not obj.onedrive_item_id:
        raise HTTPException(
            status_code=400,
            detail="Este template no tiene archivo en OneDrive",
        )

    service = get_onedrive_service()
    config = OneDriveConfig()

    try:
        if config.is_configured():
            await service.delete_file(obj.onedrive_item_id)
    except Exception as exc:
        logger.warning("[DeleteFile] Error deleting from OneDrive: %s", exc)

    try:
        obj.onedrive_item_id = None
        obj.onedrive_filename = None
        obj.onedrive_path = None
        obj.onedrive_env = None
        obj.onedrive_folder = None
        db.commit()
        return {"status": "deleted", "message": "Archivo eliminado correctamente"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/chart-file/{chart_filename}")
async def get_chart_image(chart_filename: str):
    chart_path = None
    for base_dir in _chart_candidate_dirs():
        if not base_dir.exists():
            continue
        for ext in ["jpg", "png", "jpeg"]:
            potential_path = base_dir / f"{chart_filename}.{ext}"
            if potential_path.exists():
                chart_path = potential_path
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chart image not found: {chart_filename}",
        )

    try:
        return StreamingResponse(
            content=open(chart_path, "rb"),
            media_type="image/jpeg",
            headers={"Content-Disposition": f'inline; filename="{chart_path.name}"'},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error serving chart image",
        ) from exc


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
        return {"status": "ok", "message": f"Archivo {item_id} eliminado."}
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
        return {"status": "ok", "message": "Estructura de carpetas creada."}
    except Exception as exc:
        raise HTTPException(502, f"Error al crear estructura: {exc}") from exc
