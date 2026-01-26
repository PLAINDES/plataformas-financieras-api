
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
    metadata: Optional[Dict[str, Any]]

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


# ==================== SECTION SCHEMAS ====================
class SectionBase(BaseModel):
    name: str = Field(..., max_length=255)
    component: str = Field(..., max_length=100)
    data: Optional[Dict[str, Any]] = None
    order: int = 0
    is_visible: bool = True


class SectionCreate(SectionBase):
    page_id: int


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    component: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    order: Optional[int] = None
    is_visible: Optional[bool] = None


class SectionResponse(SectionBase):
    id: int
    page_id: int
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


# ==================== CONTACT MESSAGE SCHEMAS ====================
class ContactMessageCreate(BaseModel):
    name: str = Field(..., max_length=255)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    subject: Optional[str] = Field(None, max_length=255)
    message: str


class ContactMessageUpdate(BaseModel):
    status: Literal["unread", "read", "replied"]


class ContactMessageResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    subject: Optional[str]
    message: str
    status: str
    replied_at: Optional[datetime]
    replied_by: Optional[int]
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ==================== LANDING PAGE SCHEMAS ====================
class LandingDataResponse(BaseModel):
    """Respuesta completa para renderizar la landing page"""
    page: PageWithSections
    menus: Dict[str, MenuWithItems]  # key = menu name (header, footer, etc)
    seo: Dict[str, Optional[str]]
    site: Optional[SiteResponse] = None
    
    model_config = ConfigDict(from_attributes=True)


class AdminDashboardStats(BaseModel):
    """Estadísticas para el dashboard admin"""
    total_pages: int
    published_pages: int
    draft_pages: int
    total_messages: int
    unread_messages: int
    total_media: int
    recent_messages: List[ContactMessageResponse]