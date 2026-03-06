# app/schemas/main.py
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime


# ==================== TEMPLATE SCHEMAS ====================
class TemplateBase(BaseModel):
    nombre: str = Field(..., max_length=255)
    template_file_id: Optional[int] = None
    is_default: bool = False


class TemplateCreate(TemplateBase):
    template_code_ids: List[int] = []


class TemplateUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=255)
    template_file_id: Optional[int] = None
    is_default: Optional[bool] = None
    template_code_ids: Optional[List[int]] = None


class TemplateResponse(TemplateBase):
    id: int
    template_code_ids: List[int] = []
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== TEMPLATE COMPLEMENT SCHEMAS ====================
class TemplateComplementBase(BaseModel):
    nombre: str = Field(..., max_length=255)
    fecha: datetime
    data: Optional[Dict[str, Any]] = None


class TemplateComplementCreate(TemplateComplementBase):
    pass


class TemplateComplementUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=255)
    fecha: Optional[datetime] = None
    data: Optional[Dict[str, Any]] = None


class TemplateComplementResponse(TemplateComplementBase):
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== CALCULATION SCHEMAS ====================
class CalculationBase(BaseModel):
    calculation_file_id: Optional[int] = None
    user_id: int
    type: Literal["valora", "kapital"]
    data: Optional[Dict[str, Any]] = None


class CalculationCreate(CalculationBase):
    pass


class CalculationUpdate(BaseModel):
    calculation_file_id: Optional[int] = None
    user_id: Optional[int] = None
    type: Optional[Literal["valora", "kapital"]] = None
    data: Optional[Dict[str, Any]] = None


class CalculationResponse(CalculationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== TEMPLATE CODE SCHEMAS ====================
class TemplateCodeBase(BaseModel):
    template_code_image_id: Optional[int] = None
    type: Literal["valora", "kapital"]
    hoja: Optional[str] = Field(None, max_length=255)
    nombre: str = Field(..., max_length=255)
    code: str = Field(..., max_length=255)


class TemplateCodeCreate(TemplateCodeBase):
    template_ids: List[int] = []


class TemplateCodeUpdate(BaseModel):
    template_code_image_id: Optional[int] = None
    type: Optional[Literal["valora", "kapital"]] = None
    hoja: Optional[str] = Field(None, max_length=255)
    nombre: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=255)
    template_ids: Optional[List[int]] = None


class TemplateCodeResponse(TemplateCodeBase):
    id: int
    template_ids: List[int] = []
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
