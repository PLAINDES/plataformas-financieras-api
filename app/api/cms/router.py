
# app/api/cms/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from ...db.database import get_db
from ...schemas.cms import (
    ContentUpdate,
    LandingDataResponse
)
from ...services.cms_service import CMSService

router = APIRouter(prefix="/cms", tags=["CMS"])



#landing
#SIRVE

@router.get("/landing", response_model=LandingDataResponse)
def get_landing_page(
    slug: Optional[str] = None,
    db: Session = Depends(get_db)
):
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


# app/api/v1/cms.py
#SIRVE
@router.get("/sections/{section_id}/contents")
def get_section_contents(
    section_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene todos los contenidos de una sección para edición"""
    try:
        cms_service = CMSService(db)
        return cms_service.get_section_for_editing(section_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    
# app/api/v1/cms.py
#SIRVE
@router.put("/contents/{content_id}")
def update_content(
    content_id: int,
    content_update: ContentUpdate,
    db: Session = Depends(get_db),
    author_id: Optional[int] = Query(None, description="ID del usuario que realiza el cambio")
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
        return CMSService(db).update_content_data(content_id, content_update, author_id=author_id)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

#Auditoría

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