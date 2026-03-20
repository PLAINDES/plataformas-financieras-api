import hashlib
import enum
from sqlalchemy import Column, String, DateTime, Numeric, Enum as SQLEnum, Boolean, JSON, ForeignKey, Text
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

