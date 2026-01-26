# app/repositories/user_repository.py
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from typing import Optional
from datetime import datetime
from ..models.user import User, Session as UserSession


class UserRepository:
    """Repositorio para manejo de usuarios"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Obtiene un usuario por email"""
        result = self.db.execute(
            select(User)
            .where(
                and_(
                    User.email == email,
                    User.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        """Obtiene un usuario por ID"""
        result = self.db.execute(
            select(User)
            .where(
                and_(
                    User.id == user_id,
                    User.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none()
    
    def create(self, user_data: dict) -> User:
        """Crea un nuevo usuario"""
        print("Creating user with data-REPOSITORY:", user_data)
        user = User(**user_data)
        print("User object created-REPOSITORY:", user)


        self.db.add(user)
        print("User added to session-REPOSITORY:", user)
        self.db.flush()
        print("Session flushed-REPOSITORY:", user)
        try:
            self.db.refresh(user)
        except Exception as e:
            print("Error refreshing user from DB-REPOSITORY:", e)
            raise
        self.db.refresh(user)
        print("User refreshed from DB-REPOSITORY:", user)

        return user
    
    def update(self, user_id: int, update_data: dict) -> Optional[User]:
        """Actualiza un usuario"""
        user = self.get_by_id(user_id)
        if user:
            for key, value in update_data.items():
                if hasattr(user, key) and value is not None:
                    setattr(user, key, value)
            self.db.flush()
            self.db.refresh(user)
        return user
    
    def soft_delete(self, user_id: int) -> bool:
        """Soft delete de un usuario"""
        user = self.get_by_id(user_id)
        if user:
            user.deleted_at = datetime.utcnow()
            user.is_active = False
            self.db.flush()
            return True
        return False
    
    # ==================== SESSIONS ====================
    
    def create_session(self, session_data: dict) -> UserSession:
        """Crea una nueva sesión"""
        session = UserSession(**session_data)
        self.db.add(session)
        self.db.flush()
        self.db.refresh(session)
        return session
    
    def get_session_by_token(self, token: str) -> Optional[UserSession]:
        """Obtiene sesión por token"""
        result = self.db.execute(
            select(UserSession)
            .where(UserSession.token == token)
        )
        return result.scalar_one_or_none()
    
    def delete_session(self, token: str) -> bool:
        """Elimina una sesión"""
        session = self.get_session_by_token(token)
        if session:
            self.db.delete(session)
            self.db.flush()
            return True
        return False
