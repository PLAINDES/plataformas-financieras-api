from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional, Dict, Any
from datetime import datetime


class SiteBranding(BaseModel):
    logo_url: Optional[str]
    logo_alt: Optional[str]
    favicon_url: Optional[str]


class SiteTheme(BaseModel):
    primary_color: Optional[str]
    theme: Optional[str]


class SiteResponse(BaseModel):
    site_key: str
    name: Optional[str]
    branding: SiteBranding
    theme: SiteTheme
    model_config = ConfigDict(from_attributes=True)


# ==================== PAGE SCHEMAS ====================
class PageBase(BaseModel):
    title: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=255)
    template: str = Field(default="default", max_length=100)
    parent_id: Optional[int] = None
    status: Literal["draft", "published"] = "draft"
    order: int = 0
    is_homepage: bool = False
    settings: Optional[Dict[str, Any]] = None
    seo_title: Optional[str] = Field(None, max_length=255)
    seo_description: Optional[str] = None
    seo_image: Optional[str] = None


class PageResponse(PageBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContentBase(BaseModel):
    slug: str
    data: Dict[str, Any]
    status: Literal["draft", "published"] = "draft"


class ContentResponse(ContentBase):
    id: int
    page_id: Optional[int] = None
    content_type_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContentUpdate(BaseModel):
    data: Dict[str, Any]
    status: Optional[str] = None


class PageWithContents(PageResponse):
    contents: List[ContentResponse] = []


# ==================== SECTION SCHEMAS ====================
class SectionBase(BaseModel):
    name: str = Field(..., max_length=255)
    component: str = Field(..., max_length=100)
    order: int = 0
    is_visible: bool = True


class SectionContentResponse(BaseModel):
    id: int
    order: int
    is_visible: bool
    content: ContentResponse

    model_config = ConfigDict(from_attributes=True)


class SectionResponse(SectionBase):
    id: int
    page_id: int
    contents: list[SectionContentResponse]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ==================== LANDING PAGE SCHEMAS ====================
class LandingDataResponse(BaseModel):
    page: PageWithContents
    site: Optional[SiteResponse] = None
    meta: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)