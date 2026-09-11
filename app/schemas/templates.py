# app/schemas/templates.py
from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict


# ==================== MASTER TEMPLATE SCHEMAS ====================
class MasterTemplateBase(BaseModel):
    nombre: str = Field(..., max_length=255)
    description: Optional[str] = None
    is_default: bool = False


class MasterTemplateCreate(MasterTemplateBase):
    """Schema para crear una nueva plantilla maestra."""


class MasterTemplateUpdate(BaseModel):
    """Schema para actualizar una plantilla maestra."""
    nombre: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    is_default: Optional[bool] = None


class MasterTemplateResponse(MasterTemplateBase):
    """Schema de respuesta para plantilla maestra."""
    id: int
    original_filename: Optional[str] = None
    s3_object_key: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedMasterTemplateResponse(BaseModel):
    items: List[MasterTemplateResponse]
    total: int
    page: int
    limit: int
    pages: int


# ==================== TEMPLATE CODE SCHEMAS ====================
class TemplateCodeBase(BaseModel):
    template_code_image_id: Optional[int] = None
    type: Literal["valora", "kapital"]
    hoja: Optional[str] = Field(None, max_length=255)
    nombre: str = Field(..., max_length=255)
    code: str = Field(..., max_length=255)
    value: Optional[str] = Field(None, max_length=255)
    coordinate: Optional[str] = Field(None, max_length=15)
    source_path: Optional[str] = Field(None, max_length=255)
    source_format: Optional[str] = Field(None, max_length=32)

class TemplateCodeCreate(TemplateCodeBase):
    """Schema para crear un código de plantilla."""
    template_ids: List[int] = []


class TemplateCodeUpdate(BaseModel):
    """Schema para actualizar un código de plantilla."""
    template_code_image_id: Optional[int] = None
    type: Optional[Literal["valora", "kapital"]] = None
    hoja: Optional[str] = Field(None, max_length=255)
    nombre: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=255)
    coordinate: Optional[str] = Field(None, max_length=15)
    source_path: Optional[str] = Field(None, max_length=255)
    source_format: Optional[str] = Field(None, max_length=32)
    template_ids: Optional[List[int]] = None


class TemplateCodeResponse(TemplateCodeBase):
    """Schema de respuesta para código de plantilla."""
    id: int
    template_code_image_url: Optional[str] = None
    source_path: Optional[str] = None
    source_format: Optional[str] = None
    template_ids: List[int] = []
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
