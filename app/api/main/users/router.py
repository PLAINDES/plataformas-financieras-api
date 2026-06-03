from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.database import get_db
from app.models.user import Session as SessionModel
from app.models.user import User, UserRole
from app.schemas.user import (
    PaginatedUserResponse,
    UserAdminUpdate,
    UserCreate,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(
    prefix="/main/users",
    tags=["Users Management"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("", response_model=PaginatedUserResponse)
def list_users(
    limit: int = 10,
    offset: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # Consulta base excluyendo usuarios eliminados logicamente
    query = select(User).where(User.deleted_at.is_(None))

    if search:
        query = query.where(
            or_(
                User.email.ilike(f"%{search}%"),
                User.name.ilike(f"%{search}%"),
                User.lastname.ilike(f"%{search}%"),
            )
        )

    # Conteo total
    total_query = select(func.count(User.id)).where(User.deleted_at.is_(None))
    if search:
        total_query = total_query.where(
            or_(
                User.email.ilike(f"%{search}%"),
                User.name.ilike(f"%{search}%"),
                User.lastname.ilike(f"%{search}%"),
            )
        )

    total_count = db.execute(total_query).scalar_one()
    pages = (total_count + limit - 1) // limit if limit > 0 else 1
    page = (offset // limit) + 1 if limit > 0 else 1

    # Obtencion de registros
    users = (
        db.execute(query.order_by(User.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )

    return {
        "items": users,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    # Reutiliza el servicio de autenticacion para encriptar la contraseña y validar duplicados
    try:
        auth_service = AuthService(db)
        response = auth_service.register(user_data)

        # auth_service.register devuelve un TokenResponse, extraemos el usuario
        user = db.get(User, response.user.id)
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int, user_data: UserAdminUpdate, db: Session = Depends(get_db)
):
    user = db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")

    update_dict = user_data.model_dump(exclude_unset=True)

    # Manejo de actualizacion de contraseña si el admin decide cambiarla
    if "password" in update_dict:
        auth_service = AuthService(db)
        update_dict["password"] = auth_service._hash_password(update_dict["password"])

    # Validacion de rol
    if "role" in update_dict:
        try:
            update_dict["role"] = UserRole(update_dict["role"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role specified")

    for key, value in update_dict.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")

    # Eliminacion logica
    user.deleted_at = datetime.utcnow()
    user.is_active = False

    db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))

    db.commit()
    return None
