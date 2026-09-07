"""
Pruebas unitarias para la configuración del core (Pydantic Settings).
"""
import pytest
from app.core.config import Settings
from app.core.config import get_settings

# Valores base necesarios para instanciar Settings sin que Pydantic reclame
MOCK_ENV_VARS = {
    "DATABASE_USER": "test_user",
    "DATABASE_PASSWORD": "test_password",
    "DATABASE_NAME": "test_db"
}

# ==============================================================================
# TESTS DE VALIDADOR DE CORS
# ==============================================================================

def test_cors_origins_as_list():
    """Valida que si se pasa una lista nativa de Python, se mantenga intacta."""
    settings = Settings(
        **MOCK_ENV_VARS,
        BACKEND_CORS_ORIGINS=["http://localhost:3000", "https://app.com"]
    )
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:3000", "https://app.com"]


def test_cors_origins_as_valid_json_string():
    """Valida el parseo de un string JSON perfecto."""
    settings = Settings(
        **MOCK_ENV_VARS,
        BACKEND_CORS_ORIGINS='["http://localhost:5173", "https://prod.com"]'
    )
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:5173", "https://prod.com"]


def test_cors_origins_as_comma_separated_string():
    """
    Valida el parseo robusto cuando los orígenes vienen separados por comas,
    previniendo errores de sintaxis o de formato en el .env.
    """
    settings = Settings(
        **MOCK_ENV_VARS,
        BACKEND_CORS_ORIGINS="http://localhost:8000, https://qa.app.com"
    )
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:8000", "https://qa.app.com"]


def test_cors_origins_as_broken_github_string():
    """Valida la limpieza cuando un CI (como GitHub Actions) aplana las comillas."""
    settings = Settings(
        **MOCK_ENV_VARS,
        BACKEND_CORS_ORIGINS="['http://localhost:8000', 'https://qa.app.com']"
    )
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:8000", "https://qa.app.com"]


def test_cors_origins_invalid_type():
    """Valida que el validador rechace tipos de datos no conocidos."""
    with pytest.raises(ValueError):
        Settings(**MOCK_ENV_VARS, BACKEND_CORS_ORIGINS=12345)


# ==============================================================================
# TESTS DE PROPIEDADES
# ==============================================================================

def test_database_url_property():
    """Verifica que la URL de conexión a MySQL se construya correctamente."""
    settings = Settings(
        DATABASE_USER="admin_db",
        DATABASE_PASSWORD="super_password",
        DATABASE_HOST="db.miempresa.com",
        DATABASE_PORT=3306,
        DATABASE_NAME="finanzas_prod"
    )

    expected_url = "mysql+pymysql://admin_db:super_password@db.miempresa.com:3306/finanzas_prod?charset=utf8mb4"
    assert settings.DATABASE_URL == expected_url

def test_get_settings_is_cached():
    """
    Valida que get_settings() utilice @lru_cache correctamente.
    Esto asegura que la app no lea el archivo .env desde el disco
    en cada petición HTTP, protegiendo el rendimiento (Singleton pattern).
    """
    settings_1 = get_settings()
    settings_2 = get_settings()

    # 'is' verifica que ambas variables apunten exactamente a la misma
    # dirección de memoria, confirmando que la caché funciona.
    assert settings_1 is settings_2
