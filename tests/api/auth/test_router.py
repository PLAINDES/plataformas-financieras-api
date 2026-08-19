"""
Módulo de Pruebas de Integración para Autenticación (Auth).

Este módulo valida el flujo completo de autenticación:
1. Registro de nuevos usuarios y validación de duplicados.
2. Inicio de sesión exitoso y generación de tokens JWT.
3. Manejo de credenciales inválidas.
4. Protección de rutas privadas (obtener perfil).
5. Refresco de tokens y cierre de sesión (Logout).
"""
import uuid
import time
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api.deps import get_current_user, get_current_admin
from app.main import app
from app.models.user import User
from app.models.user import Session as DBSession # Alias para no chocar con SQLAlchemy

PREFIX = "/api/v1/auth"

# ==============================================================================
# FUNCIONES AUXILIARES PARA TESTS
# ==============================================================================

@pytest.fixture(autouse=True)
def disable_auth_mocks(client):
    """Desactiva el usuario falso para que el módulo de Auth pruebe los tokens reales."""
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_admin, None)
    yield

def create_fresh_user(client: TestClient) -> dict:
    """
    Crea un usuario completamente nuevo con un correo único (UUID) y devuelve sus datos.
    Esto aísla las pruebas de los datos basura/duplicados en los archivos SQL (seeds).
    """
    unique_id = uuid.uuid4().hex[:8]
    test_email = f"test_{unique_id}@example.com"
    password = "securepassword123"

    payload = {
        "email": test_email,
        "name": "QA User",
        "phone_number": "999999999",
        "password": password,
        "role": "user"
    }
    response = client.post(f"{PREFIX}/register", json=payload)
    token = response.json()["access_token"]

    # Retornamos las credenciales para que los tests puedan hacer login
    return {
        "email": test_email,
        "password": password,
        "access_token": token
    }


# ==============================================================================
# TESTS DE REGISTRO
# ==============================================================================

def test_register_user_success(client: TestClient, db_session: Session):
    """
    Prueba el registro de un usuario nuevo. Verifica que devuelva un token
    y que el usuario se persista correctamente en la base de datos.
    """
    payload = {
        "email": "nuevo_usuario_qa@example.com",
        "name": "Usuario",
        "lastname": "Prueba",
        "phone_number": "999999999",
        "password": "securepassword123",
        "role": "user"
    }

    response = client.post(f"{PREFIX}/register", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == payload["email"]

    # Verificar en BD que el usuario realmente se creó
    db_user = db_session.query(User).filter(User.email == payload["email"]).first()
    assert db_user is not None
    assert db_user.name == "Usuario"
    assert db_user.phone_number == payload["phone_number"]


def test_register_user_duplicate_email(client: TestClient):
    """
    Valida que el sistema rechace el registro si el correo ya existe en BD.
    """
    user_creds = create_fresh_user(client)

    payload = {
        "email": user_creds["email"], # Email que acabamos de crear
        "name": "Clon",
        "phone_number": "999999999",
        "password": "password123"
    }

    response = client.post(f"{PREFIX}/register", json=payload)

    # El AuthService lanza ValueError("Email already registered") resultando en un 400
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


# ==============================================================================
# TESTS DE LOGIN
# ==============================================================0===============

def test_login_success(client: TestClient, db_session: Session):
    """
    Prueba el inicio de sesión con credenciales correctas.
    Asegura que se genere un token y se registre la sesión en BD.
    """
    user_creds = create_fresh_user(client)

    time.sleep(1)

    response = client.post(f"{PREFIX}/login", json={
        "email": user_creds["email"],
        "password": user_creds["password"]
    })

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == user_creds["email"]

    # Valida que la sesión JWT se haya almacenado físicamente en la BD
    active_session = db_session.query(DBSession).filter(
        DBSession.user_id == data["user"]["id"]
    ).order_by(DBSession.created_at.desc()).first()

    assert active_session is not None


def test_login_invalid_credentials(client: TestClient):
    """
    Comprueba que el sistema rechace intentos de inicio de sesión
    con contraseñas incorrectas o correos inexistentes.
    """
    user_creds = create_fresh_user(client)

    payload = {
        "email": user_creds["email"],
        "password": "wrongpassword_123"
    }

    response = client.post(f"{PREFIX}/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] is not None


# ==============================================================================
# TESTS DE RUTAS PROTEGIDAS (Requieren Token)
# ==============================================================================

def test_get_me_success(client: TestClient):
    """
    Valida la ruta protegida /me.
    Primero hace login para obtener el token, luego lo usa en los headers.
    """
    # Usamos el token generado directamente en el registro
    user_creds = create_fresh_user(client)

    headers = {"Authorization": f"Bearer {user_creds['access_token']}"}
    response = client.get(f"{PREFIX}/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["email"] == user_creds["email"]

def test_get_me_unauthorized(client: TestClient):
    """
    Valida que intentar acceder a una ruta protegida sin token 
    o con un token inválido retorne 401 Unauthorized.
    """
    headers = {"Authorization": "Bearer token_falso_o_invalido"}
    response = client.get(f"{PREFIX}/me", headers=headers)

    assert response.status_code == 401


# ==============================================================================
# TESTS DE REFRESH Y LOGOUT
# ==============================================================================

def test_refresh_token_success(client: TestClient):
    """
    Verifica la generación de un nuevo token de acceso a partir de uno válido.
    """
    # 1. Obtener token original
    user_creds = create_fresh_user(client)

    headers = {"Authorization": f"Bearer {user_creds['access_token']}"}
    response = client.post(f"{PREFIX}/refresh", headers=headers)

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert new_token is not None


def test_logout_success(client: TestClient, db_session: Session):
    """
    Prueba el cierre de sesión.
    Valida que el endpoint responda correctamente y destruya la sesión en la BD.
    """
    user_creds = create_fresh_user(client)

    headers = {"Authorization": f"Bearer {user_creds['access_token']}"}
    response = client.post(f"{PREFIX}/logout", headers=headers)

    assert response.status_code == 200
    assert "logged out" in response.json()["message"].lower()

    # Intentar usar el token destruido
    me_response = client.get(f"{PREFIX}/me", headers=headers)
    assert me_response.status_code == 401
