# app/models/user.py
from sqlalchemy import Column, BigInteger, String, DateTime, Enum as SQLEnum, Boolean, JSON, Text
from sqlalchemy.sql import func
from datetime import datetime
import enum
from ..db.base import Base


class UserRole(enum.Enum):
    MASTER = "master"
    ADMIN = "admin"
    USER = "user"


class User(Base):
    __tablename__ = "sys_users"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    lastname = Column(String(255), nullable=True)
    role = Column(SQLEnum(UserRole, values_callable=lambda enum_cls: [e.value for e in enum_cls]), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    avatar = Column(String(255), nullable=True)
    settings = Column(JSON, nullable=True, comment="Preferencias de usuario")
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<User {self.email}>"


class Session(Base):
    __tablename__ = "sys_sessions"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    token = Column(String(500), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<Session {self.id} - User {self.user_id}>"
