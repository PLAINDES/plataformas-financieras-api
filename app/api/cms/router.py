
# app/api/cms/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from ...db.database import get_db
from ...schemas.cms import (
    ContentUpdate,
    LandingDataResponse,
    PageCreate, PageUpdate, PageResponse, PageWithSections,
    SectionCreate, SectionUpdate, SectionResponse,
    MediaCreate, MediaResponse
    )
from ...models.user import User
from ...services.cms_service import CMSService
from ..deps import get_current_admin, get_optional_user

router = APIRouter(prefix="/cms", tags=["CMS"])

# ==================== LANDING PAGE (PUBLIC) ====================

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
    
@router.get("/landing2", response_model=LandingDataResponse)
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
        return cms_service.get_landing_page_new(slug)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/site", response_model=LandingDataResponse)
def get_site_page(
    slug: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Obtiene todos los datos para obtener el site page
    
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


# ==================== PAGES (ADMIN) ====================

@router.get("/pages", response_model=List[PageResponse])
def get_all_pages(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Lista todas las páginas (solo admin)
    
    - **status_filter**: Filtrar por 'draft' o 'published'
    """
    cms_service = CMSService(db)
    return cms_service.get_all_pages(status_filter)


@router.get("/pages/{page_id}", response_model=PageWithSections)
def get_page(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Obtiene una página con sus secciones (solo admin)
    """
    try:
        cms_service = CMSService(db)
        return cms_service.get_page(page_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/pages", response_model=PageResponse, status_code=status.HTTP_201_CREATED)
def create_page(
    page_data: PageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Crea una nueva página (solo admin)
    """
    cms_service = CMSService(db)
    return cms_service.create_page(page_data)


@router.put("/pages/{page_id}", response_model=PageResponse)
def update_page(
    page_id: int,
    page_data: PageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Actualiza una página (solo admin)
    """
    try:
        cms_service = CMSService(db)
        return cms_service.update_page(page_id, page_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.delete("/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Elimina una página (soft delete, solo admin)
    """
    cms_service = CMSService(db)
    success = cms_service.delete_page(page_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page not found"
        )
    
    return None


# ==================== SECTIONS (ADMIN) ====================

@router.post("/sections", response_model=SectionResponse, status_code=status.HTTP_201_CREATED)
def create_section(
    section_data: SectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Crea una nueva sección (solo admin)
    """
    cms_service = CMSService(db)
    return cms_service.create_section(section_data)


@router.put("/sections/{section_id}", response_model=SectionResponse)
def update_section(
    section_id: int,
    section_data: SectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Actualiza una sección (solo admin)
    """
    try:
        cms_service = CMSService(db)
        return cms_service.update_section(section_id, section_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.delete("/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    section_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Elimina una sección (soft delete, solo admin)
    """
    cms_service = CMSService(db)
    success = cms_service.delete_section(section_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Section not found"
        )
    
    return None


# ==================== MEDIA (ADMIN) ====================

@router.get("/media", response_model=List[MediaResponse])
def get_media(
    folder: Optional[str] = None,
    mime_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Lista archivos media (solo admin)
    
    - **folder**: Filtrar por carpeta
    - **mime_type**: Filtrar por tipo (ej: 'image', 'video')
    """
    cms_service = CMSService(db)
    return cms_service.get_all_media(folder, mime_type)


@router.post("/media", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
def create_media(
    media_data: MediaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Registra un nuevo archivo media (solo admin)
    
    Nota: El upload del archivo debe manejarse por separado
    Este endpoint solo registra la metadata en la BD
    """
    cms_service = CMSService(db)
    return cms_service.create_media(media_data)


# app/api/v1/cms.py

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

@router.put("/contents/{content_id}")
def update_content(
    content_id: int,
    content_update: ContentUpdate,
    db: Session = Depends(get_db),
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
        cms_service = CMSService(db)
        result = cms_service.update_content_data(content_id, content_update)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )