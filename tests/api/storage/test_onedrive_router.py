"""
Módulo de Pruebas de Integración para el Router de OneDrive.
"""

import os
import asyncio
import time
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.api.deps import get_current_admin, get_current_user
from app.services.onedrive_service import get_onedrive_service


PREFIX = "/api/v1/storage/onedrive"


def test_onedrive_health_endpoint(client: TestClient):
    """
    Prueba de conexión a OneDrive mediante el endpoint HTTP protegido.
    """
    response = client.post(f"{PREFIX}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_onedrive_folder_lifecycle(client: TestClient):
    """
    Ciclo de vida seguro en el Sandbox:
    Crea -> Consulta -> Lista -> Elimina recursivamente.
    """
    current_env = getattr(settings, "ENVIRONMENT", "test")
    assert current_env == "test", "ERROR: Intentando crear/borrar carpetas fuera del entorno 'test'."

    test_folder_name = f"sandbox_{os.urandom(4).hex()}"

    # 1. SETUP: Le decimos que asegure la existencia de PLATAFORMAS_FINANCIERAS/test
    # y que cree nuestro sandbox adentro.
    setup_payload = {
        "PLATAFORMAS_FINANCIERAS": {
            current_env: [test_folder_name]
        }
    }

    setup_response = client.post(f"{PREFIX}/setup", json=setup_payload)
    assert setup_response.status_code == 200

    # 2. FOLDER INFO (Obtener ID del sandbox)
    folder_path = f"PLATAFORMAS_FINANCIERAS/{current_env}/{test_folder_name}"
    info_response = client.get(f"{PREFIX}/folder-info?path={folder_path}")

    assert info_response.status_code == 200
    folder_id = info_response.json()["id"]

    try:
        # 3. LIST FOLDERS (Listamos dentro de la carpeta 'test' para buscar el sandbox)
        parent_path = f"PLATAFORMAS_FINANCIERAS/{current_env}"
        list_response = client.get(f"{PREFIX}/folders?path={parent_path}")
        assert list_response.status_code == 200

        folders = list_response.json()["folders"]
        assert any(f["id"] == folder_id for f in folders)

    finally:
        # 4. DELETE RECURSIVE (Elimina SOLO el sandbox creado, dejando 'test' intacto)
        delete_response = client.delete(f"{PREFIX}/folder/{folder_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"


def test_onedrive_endpoints_block_unauthorized(client: TestClient):
    """
    Verifica que si NO somos admin, se bloquea el acceso a los endpoints.
    """
    # 1. Retiramos la simulación de administrador que hace el conftest.py
    app.dependency_overrides.pop(get_current_admin, None)
    app.dependency_overrides.pop(get_current_user, None)
    try:
        # 2. Intentamos hacer una petición
        response = client.post(f"{PREFIX}/health")
        # 3. Validamos que la API nos rechace correctamente
        assert response.status_code in [401, 403]
    finally:
        # Restaurar el estado en caso de que otros tests necesiten limpieza
        app.dependency_overrides.clear()


def test_onedrive_files_list_and_delete(client: TestClient):
    """
    Prueba los endpoints HTTP para listar archivos y eliminar un item específico.
    Usa asyncio.run para inyectar el archivo de prueba directamente con el servicio.
    """
    current_env = getattr(settings, "ENVIRONMENT", "test")
    assert current_env == "test"

    service = get_onedrive_service()
    filename = f"router_test_{os.urandom(4).hex()}.txt"
    folder_name = "valora"

    # 1. Inyectar archivo usando el servicio real (forzando ejecución síncrona)
    upload_result = asyncio.run(
        service.upload_file(
            content=b"dummy content",
            filename=filename,
            env=current_env,
            folder=folder_name
        )
    )
    item_id = upload_result["id"]

    time.sleep(1.5)  # Esperar un segundo para asegurar la sincronización

    # 2. LIST FILES: Probar endpoint GET /files
    folder_path = f"PLATAFORMAS_FINANCIERAS/{current_env}/{folder_name}"
    list_response = client.get(f"{PREFIX}/files?path={folder_path}")

    assert list_response.status_code == 200
    files = list_response.json()["files"]
    assert any(f["id"] == item_id for f in files)

    # 3. DELETE ITEM: Probar endpoint DELETE /item/{id}
    delete_response = client.delete(f"{PREFIX}/item/{item_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
