
# app/api/cms/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from ...db.database import get_db
from ...schemas.cms import (
    LandingDataResponse,
    PageCreate, PageUpdate, PageResponse, PageWithSections,
    SectionCreate, SectionUpdate, SectionResponse,
    ContactMessageCreate, ContactMessageUpdate, ContactMessageResponse,
    MediaCreate, MediaResponse,
    AdminDashboardStats
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


# ==================== CONTACT MESSAGES ====================

@router.post("/contact", response_model=ContactMessageResponse, status_code=status.HTTP_201_CREATED)
def create_contact_message(
    message_data: ContactMessageCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Crea un mensaje de contacto
    
    Endpoint público - no requiere autenticación
    """
    cms_service = CMSService(db)
    
    # Capturar IP y user agent
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    return cms_service.create_contact_message(
        message_data,
        ip_address=ip_address,
        user_agent=user_agent
    )


@router.get("/contact", response_model=List[ContactMessageResponse])
def get_contact_messages(
    status_filter: Optional[str] = None,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Lista mensajes de contacto (solo admin)
    
    - **status_filter**: 'unread', 'read', o 'replied'
    - **limit**: Número máximo de mensajes
    """
    cms_service = CMSService(db)
    return cms_service.get_all_messages(status_filter, limit)


@router.patch("/contact/{message_id}", response_model=ContactMessageResponse)
def update_message_status(
    message_id: int,
    status_data: ContactMessageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Actualiza el estado de un mensaje (solo admin)
    """
    try:
        cms_service = CMSService(db)
        return cms_service.update_message_status(
            message_id,
            status_data,
            current_user.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


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


# ==================== DASHBOARD (ADMIN) ====================

@router.get("/dashboard/stats", response_model=AdminDashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Obtiene estadísticas para el dashboard admin
    """
    cms_service = CMSService(db)
    return cms_service.get_dashboard_stats()


