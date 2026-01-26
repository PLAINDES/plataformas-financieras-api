
# app/api/auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import Optional
from ...db.database import get_db
from ...schemas.user import UserLogin, TokenResponse, UserResponse, UserCreate, UserUpdate
from ...models.user import User
from ...services.auth_service import AuthService
from ..deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Registra un nuevo usuario
    
    - **email**: Email único del usuario
    - **name**: Nombre del usuario
    - **lastname**: Apellido (opcional)
    - **password**: Contraseña (mínimo 6 caracteres)
    - **role**: Rol del usuario (user por defecto)
    """
    try:
        print("user_data_router:", user_data)
        auth_service = AuthService(db)
        return auth_service.register(user_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating user"
        )


@router.post("/login", response_model=TokenResponse)
def login(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """
    Inicia sesión con email y contraseña
    
    Retorna un token JWT y la información del usuario
    """
    try:
        auth_service = AuthService(db)
        return auth_service.login(credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error during login"
        )


@router.post("/logout")
def logout(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cierra sesión eliminando la sesión del servidor
    """
    try:
        # Extraer token del header "Bearer <token>"
        token = authorization.replace("Bearer ", "")
        
        auth_service = AuthService(db)
        success = auth_service.logout(token)
        
        if success:
            return {"message": "Successfully logged out"}
        else:
            return {"message": "Session not found"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error during logout"
        )


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene información del usuario actual
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        lastname=current_user.lastname,
        role=current_user.role.value,
        is_active=current_user.is_active,
        avatar=current_user.avatar,
        created_at=current_user.created_at
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Refresca el token de acceso
    Genera un nuevo token para el usuario actual
    """
    from ...services.auth_service import AuthService
    
    auth_service = AuthService(db)
    access_token = auth_service._create_access_token(current_user.id)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=current_user.id,
            email=current_user.email,
            name=current_user.name,
            lastname=current_user.lastname,
            role=current_user.role.value,
            is_active=current_user.is_active,
            avatar=current_user.avatar,
            created_at=current_user.created_at
        )
    )

