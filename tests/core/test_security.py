"""
Pruebas unitarias para las funciones de seguridad, hashing y tokens JWT.
"""
from datetime import timedelta
import pytest
from jose import jwt
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_token,
    get_password_hash,
    verify_password
)

# ==============================================================================
# TESTS DE HASHING DE CONTRASEÑAS
# ==============================================================================

def test_password_hashing_and_verification():
    """Prueba el ciclo de vida del hashing de contraseñas con bcrypt."""
    password = "password_test"
    hashed = get_password_hash(password)

    # 1. El hash no debe ser igual al texto plano
    assert hashed != password

    # 2. La verificación con la clave correcta debe ser True
    assert verify_password(password, hashed) is True

    # 3. La verificación con una clave incorrecta debe ser False
    assert verify_password("wrong_password", hashed) is False


# ==============================================================================
# TESTS DE TOKENS JWT
# ==============================================================================

def test_create_and_verify_access_token():
    """Prueba la generación de un token válido y su correcta decodificación."""
    subject_id = "user_789"
    token = create_access_token(subject=subject_id)

    # Verificamos que se haya generado un string
    assert isinstance(token, str)

    # Decodificamos y validamos el payload
    payload = verify_token(token)
    assert payload["sub"] == subject_id
    assert payload["type"] == "access"
    assert "exp" in payload


def test_create_access_token_with_custom_expiration():
    """Prueba que el token respete un tiempo de expiración personalizado."""
    subject_id = "test_user"
    delta = timedelta(minutes=15)

    token = create_access_token(subject=subject_id, expires_delta=delta)
    payload = verify_token(token)

    assert payload["sub"] == subject_id


def test_verify_token_invalid_signature():
    """Prueba que un token modificado o falso sea rechazado lanzando HTTPException 401."""
    # Creamos un token malformado
    invalid_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.invalid_signature_here"

    with pytest.raises(HTTPException) as exc_info:
        verify_token(invalid_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


def test_verify_token_invalid_type():
    """
    Prueba la validación estricta del tipo de token.
    La función exige que el payload tenga "type": "access".
    """
    # Creamos manualmente un token válido pero de tipo "refresh"
    to_encode = {
        "sub": "user_123",
        "type": "refresh" # Tipo incorrecto
    }
    wrong_type_token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    with pytest.raises(HTTPException) as exc_info:
        verify_token(wrong_type_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token type"


def test_verify_token_expired():
    """
    Valida que un token cuya fecha de expiración ya pasó sea rechazado.
    Crucial para la seguridad de las sesiones.
    """
    # Creamos un token que expiró hace 1 minuto (viajamos al pasado)
    past_delta = timedelta(minutes=-1)
    expired_token = create_access_token(subject="user_123", expires_delta=past_delta)

    with pytest.raises(HTTPException) as exc_info:
        verify_token(expired_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


def test_verify_token_malformed():
    """
    Valida el rechazo absoluto de strings que no tienen formato JWT 
    (no tienen 3 partes separadas por puntos).
    """
    garbage_token = "esto.no_es.un_jwt_real"

    with pytest.raises(HTTPException) as exc_info:
        verify_token(garbage_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"
