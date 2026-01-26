

# app/repositories/cms_repository.py
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..models.cms import (
    Page, Section, Menu, MenuItem, 
    Media, ContactMessage,
    PageStatus, MessageStatus, Site
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

        
    # ==================== PAGES ====================
    
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
    
    # ==================== SECTIONS ====================
    
    def get_section_by_id(self, section_id: int) -> Optional[Section]:
        """Obtiene una sección por ID"""
        result = self.db.execute(
            select(Section)
            .where(
                and_(
                    Section.id == section_id,
                    Section.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def get_sections_by_page(self, page_id: int) -> List[Section]:
        """Obtiene secciones de una página"""
        result = self.db.execute(
            select(Section)
            .where(
                and_(
                    Section.page_id == page_id,
                    Section.deleted_at.is_(None)
                )
            )
            .order_by(Section.order)
        )
        return list(result.scalars().all())
    
    def create_section(self, section_data: dict) -> Section:
        """Crea una nueva sección"""
        section = Section(**section_data)
        self.db.add(section)
        self.db.flush()
        self.db.refresh(section)
        return section
    
    def update_section(self, section_id: int, update_data: dict) -> Optional[Section]:
        """Actualiza una sección"""
        section = self.get_section_by_id(section_id)
        if section:
            for key, value in update_data.items():
                if hasattr(section, key) and value is not None:
                    setattr(section, key, value)
            self.db.flush()
            self.db.refresh(section)
        return section
    
    def delete_section(self, section_id: int) -> bool:
        """Soft delete de sección"""
        section = self.get_section_by_id(section_id)
        if section:
            section.deleted_at = datetime.utcnow()
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
    
    # ==================== CONTACT MESSAGES ====================
    
    def get_message_by_id(self, message_id: int) -> Optional[ContactMessage]:
        """Obtiene mensaje por ID"""
        result = self.db.execute(
            select(ContactMessage)
            .where(ContactMessage.id == message_id)
        )
        return result.scalar_one_or_none()
    
    def get_all_messages(
        self, 
        status: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[ContactMessage]:
        """Obtiene mensajes de contacto"""
        query = select(ContactMessage)
        
        if status:
            query = query.where(ContactMessage.status == status)
        
        query = query.order_by(desc(ContactMessage.created_at))
        
        if limit:
            query = query.limit(limit)
        
        result = self.db.execute(query)
        return list(result.scalars().all())
    
    def create_message(self, message_data: dict) -> ContactMessage:
        """Crea un nuevo mensaje de contacto"""
        message = ContactMessage(**message_data)
        self.db.add(message)
        self.db.flush()
        self.db.refresh(message)
        return message
    
    def update_message_status(
        self, 
        message_id: int, 
        status: str,
        replied_by: Optional[int] = None
    ) -> Optional[ContactMessage]:
        """Actualiza el estado de un mensaje"""
        message = self.get_message_by_id(message_id)
        if message:
            message.status = MessageStatus(status)
            if status == "replied" and replied_by:
                message.replied_at = datetime.utcnow()
                message.replied_by = replied_by
            self.db.flush()
            self.db.refresh(message)
        return message
    
    # ==================== STATS & DASHBOARD ====================
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas para el dashboard admin"""
        # Count pages
        total_pages = self.db.execute(
            select(func.count(Page.id))
            .where(Page.deleted_at.is_(None))
        ).scalar()
        
        published_pages = self.db.execute(
            select(func.count(Page.id))
            .where(
                and_(
                    Page.deleted_at.is_(None),
                    Page.status == PageStatus.PUBLISHED
                )
            )
        ).scalar()
        
        draft_pages = self.db.execute(
            select(func.count(Page.id))
            .where(
                and_(
                    Page.deleted_at.is_(None),
                    Page.status == PageStatus.DRAFT
                )
            )
        ).scalar()
        
        # Count messages
        total_messages = self.db.execute(
            select(func.count(ContactMessage.id))
        ).scalar()
        
        unread_messages = self.db.execute(
            select(func.count(ContactMessage.id))
            .where(ContactMessage.status == MessageStatus.UNREAD)
        ).scalar()
        
        # Count media
        total_media = self.db.execute(
            select(func.count(Media.id))
            .where(Media.deleted_at.is_(None))
        ).scalar()
        
        return {
            "total_pages": total_pages or 0,
            "published_pages": published_pages or 0,
            "draft_pages": draft_pages or 0,
            "total_messages": total_messages or 0,
            "unread_messages": unread_messages or 0,
            "total_media": total_media or 0,
        }