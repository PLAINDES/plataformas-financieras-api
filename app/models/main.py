import hashlib
from unicodedata import numeric

import enum
from sqlalchemy import Column, String, DateTime, Numeric, Enum as SQLEnum, Boolean, JSON, ForeignKey, Table, Text
from sqlalchemy.dialects.mysql import BIGINT as MySQLBigInt
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class CoverType(enum.Enum):
    IMAGEN_ADJUNTADA = "imagen_adjuntada"
    PERSONALIZADA = "personalizada"
# pylint: disable=not-callable

class CalculationType(enum.Enum):
    VALORA = "valora"
    KAPITAL = "kapital"


class TemplateCodeType(enum.Enum):
    VALORA = "valora"
    KAPITAL = "kapital"


main_template_code_templates = Table(
    "main_template_codes_main_templates",
    Base.metadata,
    Column("template_code_id", MySQLBigInt(unsigned=True), ForeignKey("main_template_codes.id"), primary_key=True),
    Column("template_id", MySQLBigInt(unsigned=True), ForeignKey("main_templates.id"), primary_key=True),
)


class Template(Base):
    __tablename__ = "main_templates"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    template_file_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    template_file = relationship("Media")
    template_codes = relationship(
        "TemplateCode",
        secondary=main_template_code_templates,
        back_populates="templates",
    )

    def __repr__(self):
        return f"<Template {self.nombre}>"


class TemplateComplement(Base):
    __tablename__ = "main_template_complements"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    fecha = Column(DateTime, nullable=False)
    data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<TemplateComplement {self.nombre}>"


class Calculation(Base):
    __tablename__ = "main_calculations"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    calculation_file_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    user_id = Column(MySQLBigInt(unsigned=True), ForeignKey("sys_users.id"), nullable=False)
    code = Column(String(64), nullable=False, unique=True)
    type = Column(
        SQLEnum(
            CalculationType,
            name="calculationtype",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    calculation_file = relationship("Media")

    def set_code(self, raw_string: str) -> None:
        """Genera un hash SHA-256 truncado a 64 chars."""
        self.code = hashlib.sha256(raw_string.encode()).hexdigest()[:64]

    def __repr__(self):
        return f"<Calculation {self.id} - {self.type.value}>"


class TemplateCode(Base):
    __tablename__ = "main_template_codes"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    template_code_image_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    type = Column(
        SQLEnum(
            TemplateCodeType,
            name="templatecodetype",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    hoja = Column(String(255), nullable=True)
    nombre = Column(String(255), nullable=False)
    code = Column(String(255), nullable=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    template_code_image = relationship("Media")
    templates = relationship(
        "Template",
        secondary=main_template_code_templates,
        back_populates="template_codes",
    )

    def __repr__(self):
        return f"<TemplateCode {self.nombre}>"

class Report(Base):
    __tablename__ = "main_reports"
 
    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    template_id = Column(MySQLBigInt(unsigned=True), ForeignKey("main_templates.id"), nullable=False)
    file = Column(String(500), nullable=True)
    nombre = Column(String(255), nullable=False)
    precio = Column(Numeric(10, 2), nullable=True)
    moneda = Column(String(10), default="SOLES")
    sector_empresa = Column(String(50), nullable=True)
    bono_ajustado = Column(String(50), nullable=True)
    link_pago = Column(String(555), nullable=True)
    contenido = Column(String(255), nullable=True)
    portada_id = Column(MySQLBigInt(unsigned=True), ForeignKey("main_covers.id"), nullable=True)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    portada = relationship("Cover", foreign_keys=[portada_id])
    template = relationship("Template")
 
    
 
    def __repr__(self):
        return f"<Report {self.nombre}>"
 
    

class Cover(Base):
    __tablename__ = "main_covers"
 
    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    tipo = Column(
        SQLEnum(
            CoverType,
            name="covertype",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=CoverType.IMAGEN_ADJUNTADA,
    )
    portada_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    primer_imagen_footer_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    segundo_imagen_footer_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    logo_superior_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    imagen_central_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    logo_inferior_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    imagen_fondo_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    portada = relationship("Media", foreign_keys=[portada_id])
    primer_imagen_footer = relationship("Media", foreign_keys=[primer_imagen_footer_id])
    segundo_imagen_footer = relationship("Media", foreign_keys=[segundo_imagen_footer_id])
    logo_superior = relationship("Media", foreign_keys=[logo_superior_id])
    imagen_central = relationship("Media", foreign_keys=[imagen_central_id])
    logo_inferior = relationship("Media", foreign_keys=[logo_inferior_id])
    imagen_fondo = relationship("Media", foreign_keys=[imagen_fondo_id])
    
    def __repr__(self):
        return f"<Covers {self.nombre} ({self.tipo.value})>"


# ==================== MASTER TEMPLATES ====================

class MasterTemplateType(enum.Enum):
    """ Tipo de plantilla maestra, para segmentar lógicas o permisos si es necesario"""
    VALORA = "valora"
    KAPITAL = "kapital"


class MasterTemplateStatus(enum.Enum):
    """
    Estado del proceso de creación/actualización de la plantilla maestra.
    No es obligatorio pero puede ayudar a trackear el ciclo de vida del
    archivo en OneDrive y su disponibilidad para los usuarios
    """
    DRAFT = "borrador"
    IN_PROCESS = "en_proceso"
    COMPLETED = "completado"


class MasterTemplate(Base):
    """
    Define una versión del Excel maestro
    El archivo vive en OneDrive. Este registro guarda sus metadatos
    y la ruta/ID para descargarlo.
    """
    __tablename__ = "main_master_templates"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)          # ej: "WACC Colombia Q1 2026"
    version = Column(String(50), nullable=True)           # ej: "02.02.26"
    description = Column(Text, nullable=True)
    type = Column(
        SQLEnum(
            MasterTemplateType,
            name="mastertemplatetype",
            values_callable=lambda e: [x.value for x in e],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=MasterTemplateType.VALORA,
    )
    # OneDrive
    onedrive_env = Column(String(20), nullable=True)      # "development" | "production" | "test"
    onedrive_folder = Column(String(50), nullable=True)   # "plantillas_maestras"
    onedrive_item_id = Column(String(512), nullable=True) # ID en OneDrive para descarga directa
    onedrive_filename = Column(String(512), nullable=True)
    onedrive_path = Column(String(1024), nullable=True)   # path completo por referencia

    is_active = Column(Boolean, default=True, nullable=False)
    hojas_config = Column(JSON, nullable=True)            # metadatos de hojas relevantes
    created_by_user_id = Column(MySQLBigInt(unsigned=True),
                                ForeignKey("sys_users.id"), nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<MasterTemplate {self.nombre} v{self.version}>"
