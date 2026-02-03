

# app/services/cms_service.py
from importlib.resources import contents
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
from ..models.user import User
from ..models.cms import Content , Page, Section, Menu, MenuItem, Media, ContactMessage
from ..schemas.cms import (
    ContentUpdate, PageCreate, PageUpdate, PageResponse, PageWithContents, ContentResponse,ContentBase, SectionContentResponse,
    SectionCreate, SectionUpdate, SectionResponse,
    MenuItemCreate, MenuItemUpdate, MenuItemResponse, PageWithSections,
    MediaCreate, MediaResponse,
    LandingDataResponse,
    MenuWithItems
)
from ..repositories.cms_repository import CMSRepository


class CMSService:
    """Servicio para manejar la lógica de negocio del CMS"""
    
    def __init__(self, db: Session):
        self.db = db
        self.repository = CMSRepository(db)

    def get_landing_page_new(self, slug: str = None) -> LandingDataResponse:
        """
        Obtiene todos los datos para renderizar la landing page
        
        Args:
            slug: Slug de la página (si no se pasa, obtiene la homepage)
            
        Returns:
            LandingDataResponse con toda la data necesaria
        """
        # Obtener página

        page = self.repository.get_homepage_new()

        contents = self.repository.get_contents_by_page_id(page.id)


        site_settings = self.repository.get_site_settings("main")
        site = None

        if site_settings:
            logo = self.repository.get_media_by_id(site_settings.header_logo_id)
            favicon = self.repository.get_media_by_id(site_settings.favicon_id)

            site = {
                "site_key": site_settings.site_key,
                "name": site_settings.meta.get("site_name") if site_settings.meta else None,
                "branding": {
                    "logo_url": logo.url if logo else None,
                    "logo_alt": logo.alt_text if logo else None,
                    "favicon_url": favicon.url if favicon else None
                },
                "theme": {
                    "primary_color": site_settings.meta.get("primary_color"),
                    "theme": site_settings.meta.get("theme")
                },
                "meta": site_settings.meta
            }
        if not page:
            raise ValueError("Page not found")
        
        # Obtener todos los menús
        all_menus = self.repository.get_all_menus()
        menus_dict = {}
        
        for menu in all_menus:
            visible_items = [
                item for item in menu.items 
                if item.is_visible
            ]
            menus_dict[menu.name] = MenuWithItems(
                id=menu.id,
                name=menu.name,
                label=menu.label,
                created_at=menu.created_at,
                updated_at=menu.updated_at,
                items=[self._menuitem_to_response(item) for item in visible_items]
            )
        
        page.contents = contents

        return LandingDataResponse(
            page=self._page_to_response_with_contents(page),
            menus=menus_dict,
            site=site
        )

    def get_landing_page(self, slug: str = None) -> LandingDataResponse:
        """
        Obtiene todos los datos para renderizar la landing page
        
        Args:
            slug: Slug de la página (si no se pasa, obtiene la homepage)
            
        Returns:
            LandingDataResponse con toda la data necesaria
        """
        # Obtener página
        if slug:
            page = self.repository.get_page_by_slug(slug)
        else:
            page = self.repository.get_homepage()

        sections = self.repository.get_sections_with_contents_by_page_id(page.id)
   


        site_settings = self.repository.get_site_settings("main")
        site = None

        if site_settings:
            logo = self.repository.get_media_by_id(site_settings.header_logo_id)
            favicon = self.repository.get_media_by_id(site_settings.favicon_id)

            site = {
                "site_key": site_settings.site_key,
                "name": site_settings.meta.get("site_name") if site_settings.meta else None,
                "branding": {
                    "logo_url": logo.url if logo else None,
                    "logo_alt": logo.alt_text if logo else None,
                    "favicon_url": favicon.url if favicon else None
                },
                "theme": {
                    "primary_color": site_settings.meta.get("primary_color"),
                    "theme": site_settings.meta.get("theme")
                },
                "meta": site_settings.meta
            }

        
        if not page:
            raise ValueError("Page not found")
        
        # Obtener todos los menús
        all_menus = self.repository.get_all_menus()
        menus_dict = {}
        
        for menu in all_menus:
            visible_items = [
                item for item in menu.items 
                if item.is_visible
            ]
            menus_dict[menu.name] = MenuWithItems(
                id=menu.id,
                name=menu.name,
                label=menu.label,
                created_at=menu.created_at,
                updated_at=menu.updated_at,
                items=[self._menuitem_to_response(item) for item in visible_items]
            )
        
        page.sections = sections
    
        return LandingDataResponse(
            page=self._page_to_response_with_sections(page),
            menus=menus_dict,
            site=site
        )
    
    


    # app/services/cms_service.py
    def get_section_for_editing(self, section_id: int):
        """Obtiene una sección completa con sus contenidos para edición"""
        section = self.repository.get_section_with_contents(section_id)
        
        if not section:
            raise ValueError(f"Section {section_id} not found")
        
        return {
            "section": {
                "id": section.id,
                "name": section.name,
                "component": section.component,
                "order": section.order,
                "is_visible": section.is_visible,
                "page_id": section.page_id
            },
            "contents": [
                {
                    "section_content_id": sc.id,
                    "order": sc.order,
                    "is_visible": sc.is_visible,
                    "content": {
                        "id": sc.content.id,
                        "slug": sc.content.slug,
                        "data": sc.content.data,
                        "status": sc.content.status,
                        "content_type_id": sc.content.content_type_id
                    }
                }
                for sc in section.contents
            ]
        }
    
    # app/services/cms_service.py
    def update_content_data(self, content_id: int, content_update: ContentUpdate):
        """Actualiza los datos JSON de un contenido"""
        content = self.repository.get_content_by_id(content_id)
        
        if not content:
            raise ValueError(f"Content with id {content_id} not found")
        
        # Preparar datos para actualizar
        update_payload = {"data": content_update.data}
        if content_update.status:
            update_payload["status"] = content_update.status
        
        # Actualizar
        updated_content = self.repository.update_content(content_id, update_payload)
        self.repository.db.commit()
        
        return {
            "success": True,
            "message": "Content updated successfully",
            "content": {
                "id": updated_content.id,
                "slug": updated_content.slug,
                "data": updated_content.data,
                "status": updated_content.status,
                "updated_at": updated_content.updated_at
            }
        }

    # ==================== LANDING PAGE ====================
    def get_landing_page(self, slug: str = None) -> LandingDataResponse:
        """
        Obtiene todos los datos para renderizar la landing page
        
        Args:
            slug: Slug de la página (si no se pasa, obtiene la homepage)
            
        Returns:
            LandingDataResponse con toda la data necesaria
        """
        # Obtener página
        if slug:
            page = self.repository.get_page_by_slug(slug)
        else:
            page = self.repository.get_homepage()

        sections = self.repository.get_sections_with_contents_by_page_id(page.id)
   


        site_settings = self.repository.get_site_settings("main")
        site = None

        if site_settings:
            logo = self.repository.get_media_by_id(site_settings.header_logo_id)
            favicon = self.repository.get_media_by_id(site_settings.favicon_id)

            site = {
                "site_key": site_settings.site_key,
                "name": site_settings.meta.get("site_name") if site_settings.meta else None,
                "branding": {
                    "logo_url": logo.url if logo else None,
                    "logo_alt": logo.alt_text if logo else None,
                    "favicon_url": favicon.url if favicon else None
                },
                "theme": {
                    "primary_color": site_settings.meta.get("primary_color"),
                    "theme": site_settings.meta.get("theme")
                },
                "meta": site_settings.meta
            }

        
        if not page:
            raise ValueError("Page not found")
        
        # Obtener todos los menús
        all_menus = self.repository.get_all_menus()
        menus_dict = {}
        
        for menu in all_menus:
            visible_items = [
                item for item in menu.items 
                if item.is_visible
            ]
            menus_dict[menu.name] = MenuWithItems(
                id=menu.id,
                name=menu.name,
                label=menu.label,
                created_at=menu.created_at,
                updated_at=menu.updated_at,
                items=[self._menuitem_to_response(item) for item in visible_items]
            )
        
        page.sections = sections
    
        return LandingDataResponse(
            page=self._page_to_response_with_sections(page),
            menus=menus_dict,
            site=site
        )
    
    # ==================== PAGES ====================
    def get_page(self, page_id: int) -> PageWithSections:
        """Obtiene una página con sus secciones"""
        page = self.repository.get_page_by_id(page_id)
        if not page:
            raise ValueError("Page not found")
        return self._page_to_response_with_sections(page)
    
    def get_all_pages(self, status: Optional[str] = None) -> List[PageResponse]:
        """Obtiene todas las páginas"""
        pages = self.repository.get_all_pages(status)
        return [self._page_to_response(page) for page in pages]
    
    def create_page(self, page_data: PageCreate) -> PageResponse:
        """Crea una nueva página"""
        page = self.repository.create_page(page_data.model_dump())
        self.db.commit()
        return self._page_to_response(page)
    
    def update_page(self, page_id: int, page_data: PageUpdate) -> PageResponse:
        """Actualiza una página"""
        update_dict = page_data.model_dump(exclude_unset=True)
        page = self.repository.update_page(page_id, update_dict)
        
        if not page:
            raise ValueError("Page not found")
        
        self.db.commit()
        return self._page_to_response(page)
    
    def delete_page(self, page_id: int) -> bool:
        """Elimina una página (soft delete)"""
        result = self.repository.delete_page(page_id)
        if result:
            self.db.commit()
        return result
    
    # ==================== MEDIA ====================
    
    def get_all_media(
        self,
        folder: Optional[str] = None,
        mime_type: Optional[str] = None
    ) -> List[MediaResponse]:
        """Obtiene todos los archivos media"""
        media_list = self.repository.get_all_media(folder, mime_type)
        return [self._media_to_response(media) for media in media_list]
    
    def create_media(self, media_data: MediaCreate) -> MediaResponse:
        """Registra un nuevo archivo media"""
        media = self.repository.create_media(media_data.model_dump())
        self.db.commit()
        return self._media_to_response(media)
    
    # ==================== CONVERTERS ====================
    def _page_to_response(self, page: Page) -> PageResponse:
        """Convierte Page a PageResponse"""
        return PageResponse(
            id=page.id,
            title=page.title,
            slug=page.slug,
            template=page.template,
            parent_id=page.parent_id,
            status=page.status.value,
            order=page.order,
            is_homepage=page.is_homepage,
            settings=page.settings,
            seo_title=page.seo_title,
            seo_description=page.seo_description,
            seo_image=page.seo_image,
            created_at=page.created_at,
            updated_at=page.updated_at
        )
    
    def _page_to_response_with_sections(self, page: Page) -> PageWithSections:
        """Convierte Page a PageWithSections"""
        return PageWithSections(
            id=page.id,
            title=page.title,
            slug=page.slug,
            template=page.template,
            parent_id=page.parent_id,
            status=page.status.value,
            order=page.order,
            is_homepage=page.is_homepage,
            settings=page.settings,
            seo_title=page.seo_title,
            seo_description=page.seo_description,
            seo_image=page.seo_image,
            created_at=page.created_at,
            updated_at=page.updated_at,
            sections=[
                self._section_to_response(section) 
                for section in sorted(page.sections, key=lambda s: s.order)
                if section.is_visible
            ]
        )
    
    def _page_to_response_with_contents(self, page: Page) -> PageWithContents:
        """Convierte Page a PageWithContents"""
        return PageWithContents(
            id=page.id,
            title=page.title,
            slug=page.slug,
            template=page.template,
            parent_id=page.parent_id,
            status=page.status.value,
            order=page.order,
            is_homepage=page.is_homepage,
            settings=page.settings,
            seo_title=page.seo_title,
            seo_description=page.seo_description,
            seo_image=page.seo_image,
            created_at=page.created_at,
            updated_at=page.updated_at,
            contents=[
                self._content_to_response(content) 
                for content in sorted(page.contents, key=lambda c: c.sort_order)
                if content.is_visible
            ]
        )
    
    #Mapper
    def _content_to_response(self, content: Content) -> ContentResponse:
        return ContentResponse(
            id=content.id,
            page_id=content.page_id,
            content_type_id=content.content_type_id,
            slug=content.slug,
            data=content.data,
            status=content.status.value,  
    
            created_at=content.created_at,
            updated_at=content.updated_at
        )

        
    def _section_to_response(self, section: Section) -> SectionResponse:
        return SectionResponse(
            id=section.id,
            page_id=section.page_id,
            name=section.name,
            component=section.component,
            order=section.order,
            is_visible=section.is_visible,
            created_at=section.created_at,
            updated_at=section.updated_at,
            contents=[
                    SectionContentResponse(
                        id=sc.id,
                        order=sc.order,
                        is_visible=sc.is_visible,
                        content=self._content_to_response(sc.content)
                    )
                    for sc in section.contents
                    if sc.is_visible
                ]

        )

    
    def _menuitem_to_response(self, item: MenuItem) -> MenuItemResponse:
        """Convierte MenuItem a MenuItemResponse"""
        return MenuItemResponse(
            id=item.id,
            menu_id=item.menu_id,
            parent_id=item.parent_id,
            title=item.title,
            url=item.url,
            page_id=item.page_id,
            target=item.target.value,
            icon=item.icon,
            order=item.order,
            is_visible=item.is_visible,
            created_at=item.created_at,
            updated_at=item.updated_at
        )
    
    def _media_to_response(self, media: Media) -> MediaResponse:
        """Convierte Media a MediaResponse"""
        return MediaResponse(
            id=media.id,
            filename=media.filename,
            original_name=media.original_name,
            mime_type=media.mime_type,
            size=media.size,
            url=media.url,
            storage_path=media.storage_path,
            alt_text=media.alt_text,
            caption=media.caption,
            folder=media.folder,
            uploaded_by=media.uploaded_by,
            meta=media.meta,
            created_at=media.created_at,
            updated_at=media.updated_at
        )
    
