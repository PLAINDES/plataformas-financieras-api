"""
Módulo de Pruebas de Integración para OneDriveService.
"""

import os

import pytest

from app.core.config import settings
from app.services.onedrive.service import get_onedrive_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_onedrive_connection_health():
    """Valida que las credenciales del .env se conecten exitosamente a Graph API."""
    service = get_onedrive_service()
    assert service.config.is_configured() is True

    info = await service.check_connection()
    assert info["status"] == "connected"
    assert "drive_id" in info


def test_build_path_generation():
    """
    Valida que el servicio construya las rutas internas correctamente (solo lógica, sin red).
    """

    service = get_onedrive_service()
    path = service.build_path(env="test", folder="valora", filename="reporte.xlsx")
    assert path == "PLATAFORMAS_FINANCIERAS/test/valora/reporte.xlsx"


@pytest.mark.anyio
async def test_upload_download_and_delete_file_roundtrip():
    """
    Flujo completo de archivo estrictamente en la carpeta 'test'.
    """
    current_env = getattr(settings, "ENVIRONMENT", "test")

    # Verificación de seguridad: Evita ejecución si el entorno no es test
    assert current_env == "test", (
        "ERROR: Intentando ejecutar pruebas fuera del entorno 'test'."
    )

    service = get_onedrive_service()
    file_content = b"Contenido de prueba para el CI de Plataformas Financieras"
    filename = f"test_file_{os.urandom(4).hex()}.txt"

    # 1. Upload
    upload_result = await service.upload_file(
        content=file_content,
        filename=filename,
        env=current_env,
        folder="valora",  # Esto se guardará en PLATAFORMAS_FINANCIERAS/test/valora/
    )

    assert "id" in upload_result
    item_id = upload_result["id"]
    try:
        # 2. Download
        downloaded_bytes = await service.download_file(item_id)
        assert downloaded_bytes == file_content

    finally:
        # 3. Cleanup: Eliminar SIEMPRE el archivo creado
        await service.delete_file(item_id)


@pytest.mark.anyio
async def test_list_files_and_get_download_url():
    """
    Valida la lectura de lista de archivos y la generación de URLs de descarga.
    """
    current_env = getattr(settings, "ENVIRONMENT", "test")
    assert current_env == "test"

    service = get_onedrive_service()
    filename = f"dummy_list_{os.urandom(4).hex()}.txt"

    # 1. Subir archivo
    upload_result = await service.upload_file(
        content=b"test", filename=filename, env=current_env, folder="valora"
    )
    item_id = upload_result["id"]

    try:
        # 2. Listar archivos y verificar que el nuestro está ahí
        # Usamos el path completo que construimos
        folder_path = f"PLATAFORMAS_FINANCIERAS/{current_env}/valora"
        files = await service.list_files(path=folder_path)

        assert len(files) > 0
        assert any(f["id"] == item_id for f in files)

        # 3. Obtener URL de descarga directa
        download_url = await service.get_download_url(item_id)
        assert download_url.startswith("https://")
    finally:
        # 4. Limpiar
        await service.delete_file(item_id)
