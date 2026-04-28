# tests/services/test_auth_service.py
import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.services.auth_service import AuthService
from app.schemas.user import UserLogin
from app.models.user import User, UserRole
from app.models.user import Session as DBSession

KNOWN_EMAIL = "sabeteta03@gmail.com"

# ==============================================================================
# TESTS DE LÓGICA INTERNA Y CASOS LÍMITE (No probados en el Router)
# ==============================================================================

def test_login_inactive_user(db_session: Session):
    """
    Valida que un usuario inactivo no puede iniciar sesión.
    Se prueba aquí porque manipular el estado 'is_active' es más fácil directo en BD.
    """
    auth_service = AuthService(db_session)

    # 1. Crear usuario inactivo directamente en BD
    inactive_user = User(
        email="inactive@example.com",
        name="Inactive",
        password=auth_service._hash_password("123456"),
        is_active=False
    )
    db_session.add(inactive_user)
    db_session.commit()

    # 2. Validar que el SERVICIO lanza el ValueError esperado
    with pytest.raises(ValueError, match="User account is inactive"):
        auth_service.login(UserLogin(email="inactive@example.com", password="123456"))


def test_get_current_user_expired_session(db_session: Session):
    """
    Verifica el comportamiento cuando la sesión de BD expiró.
    """
    auth_service = AuthService(db_session)

    # 1. Creamos un usuario de prueba y su sesión
    user = db_session.query(User).filter(User.email == KNOWN_EMAIL).first()
    token = auth_service._create_access_token(user.id)
    auth_service._create_session(user.id, token)
    db_session.commit()

    # 2. Forzamos la expiración de la sesión en BD simulando que pasó el tiempo
    session_db = db_session.query(DBSession).filter(DBSession.token == token).first()
    session_db.expires_at = datetime.utcnow() - timedelta(minutes=10)
    db_session.commit()

    # 3. Intentamos recuperar el usuario
    retrieved_user = auth_service.get_current_user(token)

    # El servicio debe retornar None y limpiar la sesión muerta de la BD
    assert retrieved_user is None
    deleted_session = db_session.query(DBSession).filter(DBSession.token == token).first()
    assert deleted_session is None


def test_verify_admin(db_session: Session):
    """
    Valida la lógica interna de roles.
    """
    auth_service = AuthService(db_session)

    admin_user = User(role=UserRole.ADMIN)
    master_user = User(role=UserRole.MASTER)
    normal_user = User(role=UserRole.USER)

    assert auth_service.verify_admin(admin_user) is True
    assert auth_service.verify_admin(master_user) is True
    assert auth_service.verify_admin(normal_user) is False
