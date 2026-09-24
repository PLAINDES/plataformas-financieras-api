# app/schemas/user.py
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# Request Schemas
class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    lastname: Optional[str] = Field(None, max_length=255)
    phone_number: str = Field(..., min_length=7, max_length=30)
    birth_date: date
    document_type: str = Field(..., pattern="^(dni|ruc|ce)$")
    document_number: str = Field(..., min_length=8, max_length=30)
    ruc: Optional[str] = Field(None, min_length=11, max_length=20)
    password: str = Field(..., min_length=8)
    password_confirmation: str
    role: Optional[str] = Field(default="user")

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("document_number")
    @classmethod
    def validate_document_number(cls, value: str, info) -> str:
        value = value.strip()
        document_type = info.data.get("document_type")
        if document_type == "dni" and (not value.isdigit() or len(value) != 8):
            raise ValueError("DNI must contain exactly 8 digits")
        if document_type == "ruc" and (not value.isdigit() or len(value) != 11):
            raise ValueError("RUC must contain exactly 11 digits")
        if document_type == "ce" and not (8 <= len(value) <= 20):
            raise ValueError("CE must contain between 8 and 20 characters")
        return value

    @field_validator("ruc", mode="before")
    @classmethod
    def normalize_ruc(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not any(char.isupper() for char in value) or not any(not char.isalnum() for char in value):
            raise ValueError("Password must contain an uppercase letter and a symbol")
        return value

    @field_validator("password_confirmation")
    @classmethod
    def validate_password_confirmation(cls, value: str, info):
        if value != info.data.get("password"):
            raise ValueError("Passwords do not match")
        return value


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    lastname: Optional[str] = None
    phone_number: Optional[str] = Field(None, max_length=30)
    email: Optional[EmailStr] = None
    avatar: Optional[str] = None
    settings: Optional[dict] = None


# Response Schemas
class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    lastname: Optional[str]
    phone_number: Optional[str] = None
    birth_date: Optional[date] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    ruc: Optional[str] = None
    role: str
    is_active: bool
    avatar: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Última actividad registrada (última sesión de analytics). Se informa
    # solo en el listado; en el resto de endpoints es None.
    last_activity_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserAdminUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    lastname: Optional[str] = None
    phone_number: Optional[str] = Field(None, max_length=30)
    email: Optional[EmailStr] = None
    birth_date: Optional[date] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = Field(None, max_length=30)
    ruc: Optional[str] = Field(None, max_length=20)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6)


class PaginatedUserResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    limit: int
    pages: int
