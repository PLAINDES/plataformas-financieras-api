# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime


# Request Schemas
class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    lastname: Optional[str] = Field(None, max_length=255)
    password: str = Field(..., min_length=6)
    role: Optional[str] = Field(default="user")


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    lastname: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar: Optional[str] = None
    settings: Optional[dict] = None


# Response Schemas
class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    lastname: Optional[str]
    role: str
    is_active: bool
    avatar: Optional[str]
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

