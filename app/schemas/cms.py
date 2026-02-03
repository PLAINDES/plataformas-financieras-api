
# app/schemas/cms.py
from pydantic import BaseModel, Field, ConfigDict, HttpUrl
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


class PageCreate(PageBase):
    pass


class PageUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=255)
    template: Optional[str] = None
    status: Optional[Literal["draft", "published"]] = None
    order: Optional[int] = None
    is_homepage: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None
    seo_title: Optional[str] = None
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

class PageWithContents(PageResponse):
    contents: List[ContentResponse] = []


# ==================== SECTION SCHEMAS ====================
class SectionBase(BaseModel):
    name: str = Field(..., max_length=255)
    component: str = Field(..., max_length=100)
    order: int = 0
    is_visible: bool = True

class SectionCreate(SectionBase):
    page_id: int
    content_id: int

class ContentUpdate(BaseModel):
    """Schema para actualizar contenido"""
    data: Dict[str, Any]
    status: Optional[str] = None

class SectionContentUpdate(BaseModel):
    """Schema para actualizar una relación section-content"""
    order: Optional[int] = None
    is_visible: Optional[bool] = None
    content: Optional[ContentUpdate] = None

class SectionUpdate(BaseModel):
    name: Optional[str] = None
    component: Optional[str] = None
    order: Optional[int] = None
    is_visible: Optional[bool] = None
    contents: Optional[list[SectionContentUpdate]] = None



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

class SectionResponse(SectionBase):
    id: int
    page_id: int
    contents: list[SectionContentResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)




class PageWithSections(PageResponse):
    sections: List[SectionResponse] = []



# ==================== MENU SCHEMAS ====================
class MenuBase(BaseModel):
    name: str = Field(..., max_length=100)
    label: str = Field(..., max_length=255)


class MenuCreate(MenuBase):
    pass


class MenuResponse(MenuBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class MenuItemBase(BaseModel):
    title: str = Field(..., max_length=255)
    url: Optional[str] = Field(None, max_length=500)
    page_id: Optional[int] = None
    parent_id: Optional[int] = None
    target: Literal["_self", "_blank"] = "_self"
    icon: Optional[str] = None
    order: int = 0
    is_visible: bool = True


class MenuItemCreate(MenuItemBase):
    menu_id: int


class MenuItemUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    page_id: Optional[int] = None
    target: Optional[Literal["_self", "_blank"]] = None
    icon: Optional[str] = None
    order: Optional[int] = None
    is_visible: Optional[bool] = None


class MenuItemResponse(MenuItemBase):
    id: int
    menu_id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class MenuWithItems(MenuResponse):
    items: List[MenuItemResponse] = []


# ==================== MEDIA SCHEMAS ====================
class MediaBase(BaseModel):
    filename: str
    original_name: str
    mime_type: str
    size: Optional[int] = None
    url: str
    storage_path: str
    alt_text: Optional[str] = None
    caption: Optional[str] = None
    folder: str = "/"
    meta: Optional[Dict[str, Any]] = None


class MediaCreate(MediaBase):
    uploaded_by: Optional[int] = None


class MediaResponse(MediaBase):
    id: int
    uploaded_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)





# ==================== LANDING PAGE SCHEMAS ====================
class LandingDataResponse(BaseModel):
    """Respuesta completa para renderizar la landing page"""
    page: PageWithContents
    menus: Dict[str, MenuWithItems]  # key = menu name (header, footer, etc)
    site: Optional[SiteResponse] = None
    meta: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)
