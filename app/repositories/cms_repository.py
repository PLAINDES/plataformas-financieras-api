from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
from ..models.cms import ( Page, Section, Media, 
PageStatus, Site, SectionContent, Content)


class CMSRepository:

    def __init__(self, db: Session):
        self.db = db

    def get_site_settings(self, site_key: str = "main"):
        return (
            self.db.query(Site)
            .filter(Site.site_key == site_key)
            .first()
        )

    def get_contents_by_page_id(self, page_id: int) -> List[Content]:
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

    def get_homepage(self) -> Optional[Page]:
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

    def get_media_by_id(self, media_id: int) -> Optional[Media]:
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

    def get_section_with_contents(self, section_id: int) -> Optional[Section]:
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

    def get_content_by_id(self, content_id: int) -> Optional[Content]:
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
        content = self.get_content_by_id(content_id)
        if content:
            for key, value in update_data.items():
                if hasattr(content, key) and value is not None:
                    setattr(content, key, value)
            content.updated_at = datetime.utcnow()
            self.db.flush()
            self.db.refresh(content)
        return content