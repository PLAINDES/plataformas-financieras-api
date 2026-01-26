

# app/models/cms.py
from sqlalchemy import Column, BigInteger, String, DateTime, Enum as SQLEnum, Boolean, JSON, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from ..db.base import Base


class ContentStatus(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PageStatus(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class MessageStatus(enum.Enum):
    UNREAD = "unread"
    READ = "read"
    REPLIED = "replied"


class MenuTarget(enum.Enum):
    SELF = "_self"
    BLANK = "_blank"


class Page(Base):
    """Páginas del sitio web"""
    __tablename__ = "cms_pages"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    template = Column(String(100), default="default", comment="Template a usar")
    parent_id = Column(BigInteger, ForeignKey("cms_pages.id"), nullable=True)
    status = Column(SQLEnum(PageStatus), default=PageStatus.DRAFT, nullable=False)
    order = Column(Integer, default=0)
    is_homepage = Column(Boolean, default=False)
    settings = Column(JSON, nullable=True, comment="Configuración de página")
    
    seo_title = Column(String(255), nullable=True)
    seo_description = Column(Text, nullable=True)
    seo_image = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    
    # Relationships
    sections = relationship("Section", back_populates="page", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Page {self.slug}>"
    
class Site(Base):
    """Configuración del sitio web"""
    __tablename__ = "cms_site_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    site_key = Column(String(50), nullable=False)
    header_logo_id = Column(BigInteger, ForeignKey("cms_media.id"), nullable=True)
    header_logo_sticky_id = Column(BigInteger, nullable=True)
    favicon_id = Column(BigInteger, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Site {self.site_key}>"



class Section(Base):
    """Secciones dentro de páginas"""
    __tablename__ = "cms_sections"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    page_id = Column(BigInteger, ForeignKey("cms_pages.id"), nullable=False)
    name = Column(String(255), nullable=False)
    component = Column(String(100), nullable=False, comment="Componente React a renderizar")
    data = Column(JSON, nullable=True, comment="Props del componente")
    order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    
    # Relationships
    page = relationship("Page", back_populates="sections")
    
    def __repr__(self):
        return f"<Section {self.name} - Page {self.page_id}>"


class Menu(Base):
    """Menús del sitio"""
    __tablename__ = "cms_menus"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="header, footer, sidebar")
    label = Column(String(255), nullable=False)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    items = relationship("MenuItem", back_populates="menu", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Menu {self.name}>"


class MenuItem(Base):
    """Items de menú"""
    __tablename__ = "cms_menu_items"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    menu_id = Column(BigInteger, ForeignKey("cms_menus.id"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("cms_menu_items.id"), nullable=True)
    title = Column(String(255), nullable=False)
    url = Column(String(500), nullable=True)
    page_id = Column(BigInteger, ForeignKey("cms_pages.id"), nullable=True)
    target = Column(SQLEnum(MenuTarget), default=MenuTarget.SELF)
    icon = Column(String(50), nullable=True)
    order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    menu = relationship("Menu", back_populates="items")
    
    def __repr__(self):
        return f"<MenuItem {self.title}>"


class Media(Base):
    """Archivos y medios"""
    __tablename__ = "cms_media"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False, index=True)
    size = Column(BigInteger, nullable=True, comment="Tamaño en bytes")
    url = Column(String(500), nullable=False)
    storage_path = Column(String(500), nullable=False)
    alt_text = Column(String(255), nullable=True)
    caption = Column(Text, nullable=True)
    folder = Column(String(255), default="/", comment="Organización en carpetas")
    uploaded_by = Column(BigInteger, ForeignKey("sys_users.id"), nullable=True)
    meta = Column(JSON, nullable=True, comment="Dimensiones, duración, etc")
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Media {self.filename}>"


class ContactMessage(Base):
    """Mensajes de contacto"""
    __tablename__ = "cms_contact_messages"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    status = Column(SQLEnum(MessageStatus), default=MessageStatus.UNREAD, index=True)
    replied_at = Column(DateTime, nullable=True)
    replied_by = Column(BigInteger, ForeignKey("sys_users.id"), nullable=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ContactMessage {self.id} - {self.status.value}>"