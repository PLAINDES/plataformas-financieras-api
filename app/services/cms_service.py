from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
from ..models.user import User
from ..models.cms import Content, Page, Section, Media, ContactMessage, Auditory
from ..schemas.cms import (ContentUpdate,PageWithContents, ContentResponse,LandingDataResponse)
from ..repositories.cms_repository import CMSRepository
from ..repositories.auditory_repository import AuditoryRepository

class CMSService:

    def __init__(self, db: Session):
        self.db = db
        self.repository = CMSRepository(db)
        self.auditory_repository = AuditoryRepository(db)

    def get_landing_page(self, slug: str = None) -> LandingDataResponse:
        page = self.repository.get_homepage()
    
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

        page.contents = contents

        return LandingDataResponse(
            page=self._page_to_response_with_contents(page),
            site=site
        )

    def get_section_for_editing(self, section_id: int):
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

    def update_content_data(self, content_id: int, content_update: ContentUpdate, author_id: Optional[int] = None):
        content = self.repository.get_content_by_id(content_id)

        if not content:
            raise ValueError(f"Content with id {content_id} not found")

        update_payload = {"data": content_update.data}
        if content_update.status:
            update_payload["status"] = content_update.status

        updated_content = self.repository.update_content(content_id, update_payload)

        #Auditoría
        self.auditory_repository.create_log(
            content_id=content_id,
            data_snapshot=updated_content.data,
            author_id=author_id,
            title=f"Contenido Actualizado: {updated_content.slug}",
        )

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
    
    def get_content_history(self, content_id: int) -> List[dict]:
        """Devuelve el historial."""
        content = self.repository.get_content_by_id(content_id)
        if not content:
            raise ValueError(f"Content with id {content_id} not found")

        logs = self.auditory_repository.get_by_content_id(content_id)
        return [self._auditory_to_dict(log) for log in logs]

    

    def get_content_history_entry(self, content_id: int, log_id: int) -> dict:
        """Devuelve un registro de auditoría específico de un contenido."""
        content = self.repository.get_content_by_id(content_id)
        if not content:
            raise ValueError(f"Content with id {content_id} not found")

        log = self.auditory_repository.get_by_id(log_id)
        if not log or log.content_id != content_id:
            raise ValueError(f"Audit log {log_id} not found for content {content_id}")

        return self._auditory_to_dict(log)

    #Serializadores

    def _auditory_to_dict(self, log: Auditory) -> dict:
        return {
            "id": log.id,
            "content_id": log.content_id,
            "title": log.title,
            "author_id": log.author_id,
            "data": log.data,
            "is_visible": log.is_visible,
            "created_at": log.created_at,
            "updated_at": log.updated_at,
        }

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
    
    def _page_to_response_with_contents(self, page: Page) -> PageWithContents:
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
                for content in sorted(page.contents, key=lambda c: c.sort_order or 0)
                if content.is_visible
            ]
        )


       