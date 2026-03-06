from sqlalchemy import Column, BigInteger, String, DateTime, Enum as SQLEnum, Boolean, JSON, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from ..db.base import Base


class CalculationType(enum.Enum):
    VALORA = "valora"
    KAPITAL = "kapital"


class TemplateCodeType(enum.Enum):
    VALORA = "valora"
    KAPITAL = "kapital"


main_template_code_templates = Table(
    "main_template_codes_main_templates",
    Base.metadata,
    Column("template_code_id", BigInteger, ForeignKey("main_template_codes.id"), primary_key=True),
    Column("template_id", BigInteger, ForeignKey("main_templates.id"), primary_key=True),
)


class Template(Base):
    __tablename__ = "main_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    template_file_id = Column(BigInteger, ForeignKey("cms_media.id"), nullable=True)
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

    id = Column(BigInteger, primary_key=True, autoincrement=True)
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

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    calculation_file_id = Column(BigInteger, ForeignKey("cms_media.id"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("sys_users.id"), nullable=False)
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

    def __repr__(self):
        return f"<Calculation {self.id} - {self.type.value}>"


class TemplateCode(Base):
    __tablename__ = "main_template_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_code_image_id = Column(BigInteger, ForeignKey("cms_media.id"), nullable=True)
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
