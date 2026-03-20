import enum
from sqlalchemy import Column, String, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.dialects.mysql import BIGINT as MySQLBigInt
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


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
    description = Column(Text, nullable=True)
    
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

    created_at = Column(DateTime, default=func.now(), nullable=False)  # pylint: disable=not-callable
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)  # pylint: disable=not-callable
    deleted_at = Column(DateTime, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<MasterTemplate {self.nombre}>"
