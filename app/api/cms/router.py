# app/api/cms/router.py
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.cms import Media
from app.schemas.cms import ContentUpdate, LandingDataResponse
from app.services.aws_service import s3_service
from app.services.cms_service import CMSService

router = APIRouter(prefix="/cms", tags=["CMS"])


@router.get("/landing", response_model=LandingDataResponse)
def get_landing_page(slug: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Obtiene todos los datos para renderizar la landing page

    - Sin slug: retorna la homepage
    - Con slug: retorna la página específica

    Endpoint público
    """
    try:
        cms_service = CMSService(db)
        return cms_service.get_landing_page(slug)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# app/api/v1/cms.py
@router.get("/sections/{section_id}/contents")
def get_section_contents(section_id: int, db: Session = Depends(get_db)):
    """Obtiene todos los contenidos de una sección para edición"""
    try:
        cms_service = CMSService(db)
        return cms_service.get_section_for_editing(section_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


def _create_cms_media_from_upload(
    db: Session, file: UploadFile, folder_path: str
) -> dict:
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="Invalid file template")

    try:
        s3_result = s3_service.upload_image(file, folder=folder_path)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error subiendo archivo a AWS S3: {str(e)}"
        )

    media = Media(
        filename=s3_result["object_key"].split("/")[-1],
        original_name=file.filename,
        mime_type="image/webp",
        url=s3_result["file_url"],
        storage_path=s3_result["object_key"],
        folder=f"/{folder_path}",
    )
    db.add(media)
    db.flush()

    return {
        "id": media.id,
        "url": media.url,
        "filename": media.filename,
        "original_name": media.original_name,
    }


@router.post("/contents/upload-image", status_code=status.HTTP_201_CREATED)
def upload_cms_image(
    file: UploadFile = File(...),
    old_url: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Sube una imagen de uso general para el CMS a AWS S3
    dentro del directorio 'covers/enterprises'.
    """
    if old_url and old_url != "https://via.placeholder.com/140x40?text=Logo":
        try:
            old_key = s3_service.extract_key_from_url(old_url)
            s3_service.delete_file(old_key)
        except Exception:
            pass

    target_folder = "covers/enterprises"
    media_data = _create_cms_media_from_upload(db, file, target_folder)
    db.commit()
    return {"success": True, "media": media_data}


# app/api/v1/cms.py
@router.put("/contents/{content_id}")
def update_content(
    content_id: int,
    content_update: ContentUpdate,
    db: Session = Depends(get_db),
    author_id: Optional[int] = Query(
        None, description="ID del usuario que realiza el cambio"
    ),
):
    """
        Actualiza el contenido de una sección

        Ejemplo para Hero:
    ```json
        {
          "data": {
            "title": "Nuevo Título",
            "description": "Nueva descripción",
            "ctaText": "Ver más",
            "ctaUrl": "/contacto"
          },
          "status": "published"
        }
    ```
    """
    try:
        return CMSService(db).update_content_data(
            content_id, content_update, author_id=author_id
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/contents/{content_id}/history")
def get_content_history(
    content_id: int,
    db: Session = Depends(get_db),
):
    """
    Historial
    """
    try:
        return CMSService(db).get_content_history(content_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/contents/{content_id}/history/{log_id}")
def get_content_history_entry(
    content_id: int,
    log_id: int,
    db: Session = Depends(get_db),
):
    """
    Detalle de un registro de auditoría
    """
    try:
        return CMSService(db).get_content_history_entry(content_id, log_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/contents/media", status_code=status.HTTP_204_NO_CONTENT)
def delete_cms_media(
    url: str = Query(..., description="URL de la imagen a eliminar de S3"),
    db: Session = Depends(get_db),
):
    """
    Elimina una imagen de S3 y su registro en BD a partir de su URL.
    """
    if not url or "via.placeholder.com" in url:
        return None

    try:
        # Buscar el registro exacto
        media_to_delete = db.execute(
            select(Media).where(Media.url == url)
        ).scalar_one_or_none()

        if media_to_delete:
            s3_service.delete_file(media_to_delete.storage_path)
            db.delete(media_to_delete)
        else:
            # Fallback por si la imagen está en S3 pero no en la BD
            key = s3_service.extract_key_from_url(url)
            s3_service.delete_file(key)

        db.commit()
    except Exception as e:
        print(f"Error eliminando media huérfana: {e}")

    return None
