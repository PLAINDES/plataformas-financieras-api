import enum
from sqlalchemy import Column, String, DateTime, Boolean, JSON, ForeignKey, Table, Text
from sqlalchemy.dialects.mysql import BIGINT as MySQLBigInt
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
#pylint: disable=relative-beyond-top-level
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

    created_at = Column(DateTime, default=func.now(), nullable=False)  # pylint: disable=not-callable
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)  # pylint: disable=not-callable
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

    created_at = Column(DateTime, default=func.now(), nullable=False)  # pylint: disable=not-callable
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)  # pylint: disable=not-callable
    deleted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<TemplateComplement {self.nombre}>"


class TemplateCode(Base):
    __tablename__ = "main_template_codes"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    template_code_image_id = Column(MySQLBigInt(unsigned=True), ForeignKey("cms_media.id"), nullable=True)
    type = Column(
        __import__('sqlalchemy').Enum(
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

    created_at = Column(DateTime, default=func.now(), nullable=False)  # pylint: disable=not-callable
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)  # pylint: disable=not-callable
    deleted_at = Column(DateTime, nullable=True)

    template_code_image = relationship("Media")
    templates = relationship(
        "Template",
        secondary=main_template_code_templates,
        back_populates="template_codes",
    )

    def __repr__(self):
        return f"<TemplateCode {self.nombre}>"
