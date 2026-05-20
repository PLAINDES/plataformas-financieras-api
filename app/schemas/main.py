# app/schemas/main.py
from datetime import datetime
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


# ==================== TEMPLATE COMPLEMENT SCHEMAS ====================
class TemplateComplementBase(BaseModel):
    nombre: str = Field(..., max_length=255)
    fecha: datetime
    data: Optional[Any] = None


class TemplateComplementCreate(TemplateComplementBase):
    pass


class TemplateComplementUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=255)
    fecha: Optional[datetime] = None
    data: Optional[Any] = None


class TemplateComplementResponse(TemplateComplementBase):
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== CALCULATION SCHEMAS ====================
class CalculationBase(BaseModel):
    calculation_file_id: Optional[str] = Field(None, max_length=36)
    user_id: Optional[int] = None
    code: str = Field(..., max_length=64)
    type: Literal["valora", "kapital"]
    data: Optional[Dict[str, Any]] = None
    @field_validator("type", mode="before")
    @classmethod
    def extract_enum_value(cls, v):
        return v.value if hasattr(v, "value") else v


class CalculationCreate(CalculationBase):
    pass


class CalculationUpdate(BaseModel):
    calculation_file_id: Optional[str] = Field(None, max_length=36)
    user_id: Optional[int] = None
    type: Optional[Literal["valora", "kapital"]] = None
    data: Optional[Dict[str, Any]] = None


class CalculationResponse(CalculationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ==================== COVER CODE SCHEMAS ====================
class CoverUpdate(BaseModel):

    nombre: Optional[str] = None
    tipo: Optional[str] = None
    portada_id: Optional[int] = None
    primer_imagen_footer_id: Optional[int] = None
    segundo_imagen_footer_id: Optional[int] = None
    logo_superior_id: Optional[int] = None
    imagen_central_id: Optional[int] = None
    logo_inferior_id: Optional[int] = None
    imagen_fondo_id: Optional[int] = None


# ==================== REPORT CODE SCHEMAS ====================
class ReportUpdate(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    precio: Optional[float] = None
    moneda: Optional[str] = None
    sector_empresa: Optional[str] = None
    bono_ajustado: Optional[str] = None
    link_pago: Optional[str] = None
    contenido: Optional[str] = None
    # HTML content produced by the rich text editor
    contentEditor: Optional[str] = None

    # Tipo de reporte: 'valora' o 'kapital'
    type: Optional[Literal["valora", "kapital"]] = None

    # ── NEW ──────────────────────────────────────────────────────────────
    # Reassigns the Cover FK on the Report row.
    # Send null to detach the current cover.
    portada_id: Optional[int] = None
    # ─────────────────────────────────────────────────────────────────────

    # Kept for backwards-compat: patches fields on the already-linked Cover.
    cover_data: Optional[CoverUpdate] = None


# ==================== APP CONFIGURATION SCHEMAS ====================
class AppConfigurationBase(BaseModel):
    module: str = Field(..., max_length=50)
    settings: Dict[str, Any]

class AppConfigurationUpdate(BaseModel):
    settings: Dict[str, Any]

class AppConfigurationResponse(AppConfigurationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)