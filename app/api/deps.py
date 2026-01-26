# app/api/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from ..db.database import get_db
from ..models.user import User
from ..services.auth_service import AuthService

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Obtiene el usuario actual desde el token JWT
    Requiere autenticación
    """
    token = credentials.credentials
    auth_service = AuthService(db)
    
    user = auth_service.get_current_user(token)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Verifica que el usuario actual sea ADMIN o MASTER
    """
    auth_service = AuthService(db)
    
    if not auth_service.verify_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return current_user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Obtiene el usuario actual si está autenticado, None si no
    Útil para endpoints públicos que cambian según autenticación
    """
    if credentials is None:
        return None
    
    try:
        token = credentials.credentials
        auth_service = AuthService(db)
        user = auth_service.get_current_user(token)
        
        if user and user.is_active:
            return user
        return None
    except:
        return None

