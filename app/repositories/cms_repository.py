

# app/repositories/cms_repository.py
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..models.cms import (
    Page, Section, Menu, MenuItem, 
    Media, ContactMessage,
    PageStatus, MessageStatus, Site, SectionContent, Content
)


class CMSRepository:
    """Repositorio unificado para el CMS"""
    
    def __init__(self, db: Session):
        self.db = db

    def get_site_settings(self, site_key: str = "main"):
        return (
            self.db.query(Site)
            .filter(Site.site_key == site_key)
            .first()
        )
    
    def get_contents_by_page_id(self, page_id: int) -> List[Content]:
        """Obtiene los contenidos asociados a una página específica"""
        result = self.db.execute(
            select(Content)
            .where(
                and_(
                    Content.page_id == page_id,
                    Content.deleted_at.is_(None)
                )
            )
        )
        return list(result.scalars().all())

    def get_sections_with_contents_by_page_id(self, page_id: int):
        return (
            self.db.execute(
                select(Section)
                .options(
                    selectinload(Section.contents)
                    .selectinload(SectionContent.content)
                )
                .where(
                    Section.page_id == page_id,
                    Section.deleted_at.is_(None),
                    Section.is_visible == True
                )
                .order_by(Section.order)
            )
            .scalars()
            .all()
        )
        
    # ==================== PAGES ====================
    def get_homepage_new(self) -> Optional[Page]:
        """Obtiene la página de inicio"""
        result = self.db.execute(
            select(Page)
            .options(selectinload(Page.sections))
            .where(
                and_(
                    Page.is_homepage == True,
                    Page.status == PageStatus.PUBLISHED,
                    Page.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def get_homepage(self) -> Optional[Page]:
        """Obtiene la página de inicio"""
        result = self.db.execute(
            select(Page)
            .options(selectinload(Page.sections))
            .where(
                and_(
                    Page.is_homepage == True,
                    Page.status == PageStatus.PUBLISHED,
                    Page.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def get_page_by_id(self, page_id: int, include_sections: bool = True) -> Optional[Page]:
        """Obtiene página por ID"""
        query = select(Page).where(
            and_(
                Page.id == page_id,
                Page.deleted_at.is_(None)
            )
        )
        
        if include_sections:
            query = query.options(selectinload(Page.sections))
        
        result = self.db.execute(query)
        return result.scalar_one_or_none()
    


    def get_page_by_slug(self, slug: str, include_sections: bool = True) -> Optional[Page]:
        """Obtiene página por slug con sus secciones"""
        query = select(Page).where(
            and_(
                Page.slug == slug,
                Page.deleted_at.is_(None)
            )
        )
        
        if include_sections:
            query = query.options(selectinload(Page.sections))
        
        result = self.db.execute(query)
        return result.scalar_one_or_none()
    
    

    
    
    
    def get_all_pages(self, status: Optional[str] = None) -> List[Page]:
        """Obtiene todas las páginas"""
        query = select(Page).where(Page.deleted_at.is_(None))
        
        if status:
            query = query.where(Page.status == status)
        
        query = query.order_by(Page.order)
        result = self.db.execute(query)
        return list(result.scalars().all())
    
    def create_page(self, page_data: dict) -> Page:
        """Crea una nueva página"""
        page = Page(**page_data)
        self.db.add(page)
        self.db.flush()
        self.db.refresh(page)
        return page
    
    def update_page(self, page_id: int, update_data: dict) -> Optional[Page]:
        """Actualiza una página"""
        page = self.get_page_by_id(page_id, include_sections=False)
        if page:
            for key, value in update_data.items():
                if hasattr(page, key) and value is not None:
                    setattr(page, key, value)
            self.db.flush()
            self.db.refresh(page)
        return page
    
    def delete_page(self, page_id: int) -> bool:
        """Soft delete de página"""
        page = self.get_page_by_id(page_id, include_sections=False)
        if page:
            page.deleted_at = datetime.utcnow()
            self.db.flush()
            return True
        return False
    
    # ==================== MENUS ====================
    
    def get_menu_by_name(self, menu_name: str) -> Optional[Menu]:
        """Obtiene menú por nombre con sus items"""
        result = self.db.execute(
            select(Menu)
            .options(selectinload(Menu.items))
            .where(Menu.name == menu_name)
        )
        return result.scalar_one_or_none()
    
    def get_all_menus(self) -> List[Menu]:
        """Obtiene todos los menús con sus items"""
        result = self.db.execute(
            select(Menu)
            .options(selectinload(Menu.items))
        )
        return list(result.scalars().all())
    
    def get_visible_menu_items(self, menu_id: int) -> List[MenuItem]:
        """Obtiene items visibles de un menú"""
        result = self.db.execute(
            select(MenuItem)
            .where(
                and_(
                    MenuItem.menu_id == menu_id,
                    MenuItem.is_visible == True
                )
            )
            .order_by(MenuItem.order)
        )
        return list(result.scalars().all())
    
    # ==================== MEDIA ====================
    
    def get_media_by_id(self, media_id: int) -> Optional[Media]:
        """Obtiene media por ID"""
        result = self.db.execute(
            select(Media)
            .where(
                and_(
                    Media.id == media_id,
                    Media.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def get_all_media(
        self, 
        folder: Optional[str] = None,
        mime_type: Optional[str] = None
    ) -> List[Media]:
        """Obtiene todos los archivos media con filtros opcionales"""
        query = select(Media).where(Media.deleted_at.is_(None))
        
        if folder:
            query = query.where(Media.folder == folder)
        
        if mime_type:
            query = query.where(Media.mime_type.like(f"{mime_type}%"))
        
        query = query.order_by(desc(Media.created_at))
        result = self.db.execute(query)
        return list(result.scalars().all())
    
    def create_media(self, media_data: dict) -> Media:
        """Crea un nuevo archivo media"""
        media = Media(**media_data)
        self.db.add(media)
        self.db.flush()
        self.db.refresh(media)
        return media
    
    # app/repositories/cms_repository.py

    # Agregar este método a la clase CMSRepository:

    def get_section_with_contents(self, section_id: int) -> Optional[Section]:
        """Obtiene una sección con todos sus contenidos ordenados"""
        result = self.db.execute(
            select(Section)
            .options(
                selectinload(Section.contents)
                .selectinload(SectionContent.content)
            )
            .where(
                and_(
                    Section.id == section_id,
                    Section.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()

    def get_contents_by_section(self, section_id: int) -> List[SectionContent]:
        """Obtiene los contenidos de una sección ordenados"""
        result = self.db.execute(
            select(SectionContent)
            .options(selectinload(SectionContent.content))
            .where(SectionContent.section_id == section_id)
            .order_by(SectionContent.order)
        )
        return list(result.scalars().all())
    
    def get_content_by_id(self, content_id: int) -> Optional[Content]:
        """Obtiene contenido por ID"""
        result = self.db.execute(
            select(Content)
            .where(
                and_(
                    Content.id == content_id,
                    Content.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()

    def update_content(self, content_id: int, update_data: dict) -> Optional[Content]:
        """Actualiza un contenido"""
        content = self.get_content_by_id(content_id)
        if content:
            for key, value in update_data.items():
                if hasattr(content, key) and value is not None:
                    setattr(content, key, value)
            content.updated_at = datetime.utcnow()
            self.db.flush()
            self.db.refresh(content)
        return content