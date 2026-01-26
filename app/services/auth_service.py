# app/services/auth_service.py
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError
from ..models.user import User
from ..repositories.user_repository import UserRepository
from ..schemas.user import UserCreate, UserLogin, TokenResponse, UserResponse

# Configuración
SECRET_KEY = "your-secret-key-here"  # Cambiar en producción
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 horas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Servicio de autenticación y autorización"""
    
    def __init__(self, db: Session):
        self.db = db
        self.repository = UserRepository(db)
    
    def register(self, user_data: UserCreate) -> TokenResponse:
        """
        Registra un nuevo usuario
        
        Args:
            user_data: Datos del usuario a crear
            
        Returns:
            TokenResponse con el token y datos del usuario
            
        Raises:
            ValueError: Si el email ya existe
        """
        print("user_data_service:", user_data)
        # Verificar si el email ya existe
        existing_user = self.repository.get_by_email(user_data.email)
        if existing_user:
            raise ValueError("Email already registered")
        print("No existing user found for email:", user_data.email)


        # Hash de la contraseña
        hashed_password = self._hash_password(user_data.password)
        if not hashed_password:
            print("Failed to hash password for user:", user_data.email)
            raise ValueError("Error processing password")
        print("Password hashed successfully for user:", user_data.email)

        # Crear usuario
        user = self.repository.create({
            "email": user_data.email,
            "name": user_data.name,
            "lastname": user_data.lastname,
            "password": hashed_password,
            "role": user_data.role or "user"
        })

        if not user:
            print("Failed to create user in database for email:", user_data.email)
            raise ValueError("Error creating user")
        
        print("User created successfully in database:", user.email)
        
        self.db.commit()
        print("Database commit successful for user:", user.email)

        # Generar token
        access_token = self._create_access_token(user.id)
        if not access_token:
            print("Failed to generate access token for user:", user.id)
            raise ValueError("Error generating access token")
        
        print("Generated access token for user:", user.id)
        # Crear sesión
        self._create_session(user.id, access_token)
        self.db.commit()
        print("User registered successfully:", user.email)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=self._user_to_response(user)
        )
    
    def login(self, credentials: UserLogin) -> TokenResponse:
        """
        Inicia sesión con email y contraseña
        
        Args:
            credentials: Email y contraseña
            
        Returns:
            TokenResponse con el token y datos del usuario
            
        Raises:
            ValueError: Si las credenciales son inválidas
        """
        # Buscar usuario
        user = self.repository.get_by_email(credentials.email)
        
        if not user:
            raise ValueError("Invalid credentials")
        
        # Verificar contraseña
        if not self._verify_password(credentials.password, user.password):
            raise ValueError("Invalid credentials")
        
        # Verificar si está activo
        if not user.is_active:
            raise ValueError("User account is inactive")
        
        # Generar token
        access_token = self._create_access_token(user.id)
        
        # Crear sesión
        self._create_session(user.id, access_token)
        self.db.commit()
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=self._user_to_response(user)
        )
    
    def logout(self, token: str) -> bool:
        """
        Cierra sesión eliminando el token
        
        Args:
            token: Token de sesión
            
        Returns:
            True si se cerró sesión correctamente
        """
        result = self.repository.delete_session(token)
        if result:
            self.db.commit()
        return result
    
    def get_current_user(self, token: str) -> Optional[User]:
        try:
            payload = jwt.decode(
                token,
                SECRET_KEY,
                algorithms=[ALGORITHM]
            )

            user_id = payload.get("sub")
            if user_id is None:
                return None

            session = self.repository.get_session_by_token(token)
            if not session:
                return None

            if session.expires_at < datetime.utcnow():
                self.repository.delete_session(token)
                self.db.commit()
                return None

            return self.repository.get_by_id(int(user_id))

        except PyJWTError:
            return None

    
    def verify_admin(self, user: User) -> bool:
        return user.role in ("admin", "master")

    
    # ==================== PRIVATE METHODS ====================
    
    def _hash_password(self, password: str) -> str:
        """Hashea una contraseña"""
        return pwd_context.hash(password)
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verifica una contraseña contra su hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def _create_access_token(self, user_id: int) -> str:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            "sub": str(user_id),  # JWT recomienda string
            "exp": expire
        }

        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    
    def _create_session(self, user_id: int, token: str) -> None:
        """Crea una sesión en la BD"""
        expires_at = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        self.repository.create_session({
            "user_id": user_id,
            "token": token,
            "expires_at": expires_at
        })
    
    def _user_to_response(self, user: User) -> UserResponse:
        """Convierte User model a UserResponse schema"""
        return UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            lastname=user.lastname,
            role=user.role.value,
            is_active=user.is_active,
            avatar=user.avatar,
            created_at=user.created_at
        )
