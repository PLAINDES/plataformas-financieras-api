# app/services/onedrive_service.py
"""
Microsoft OneDrive service via Microsoft Graph API
Estructura de carpetas sugerida en OneDrive:
  PLATAFORMAS_FINANCIERAS/
  ├== development/
  │   ├== plantillas_maestras/
  │   ├== kapital/
  │   └== valora/
  ├== production/
  │   ├== plantillas_maestras/
  │   ├== kapital/
  │   └== valora/
  └== test/
      ├== plantillas_maestras/
      ├== kapital/
      └== valora/

NOTA: Este servicio es REUTILIZABLE. No está limitado a la
estructura anterior. Puede usarse para cualquier carpeta en OneDrive.

Variables de entorno requeridas (en .env):
  AZURE_CLIENT_ID       -> App registration -> Application (client) ID
  AZURE_CLIENT_SECRET   -> App registration -> Certificates & secrets
  AZURE_TENANT_ID       -> Azure Active Directory -> Tenant ID
  ONEDRIVE_USER_EMAIL   -> Email del usuario cuyo OneDrive se usa
                          (o SERVICE_ACCOUNT_EMAIL si es cuenta de servicio)

Cómo obtenerlas:
  1. portal.azure.com -> Azure Active Directory -> App registrations -> New registration
  2. Nombre: plataformas-financieras-api
  3. API Permissions -> Add -> Microsoft Graph:
       - Files.ReadWrite.All  (Application)
       - Sites.ReadWrite.All  (Application, si es SharePoint/OD Business)
  4. Grant admin consent
  5. Certificates & secrets -> New client secret -> copiar valor
"""

import logging
from functools import lru_cache
from typing import Optional

import httpx

from .auth_mixin import OneDriveAuthMixin
from .config import GRAPH_BASE, OneDriveConfig
from .drive_mixin import OneDriveDriveMixin
from .excel_mixin import OneDriveExcelMixin

logger = logging.getLogger(__name__)


class OneDriveService(OneDriveAuthMixin, OneDriveDriveMixin, OneDriveExcelMixin):
    """
    Servicio para interactuar con OneDrive via Microsoft Graph API.

    Uso:
        service = OneDriveService()
        # Subir archivo
        item = await service.upload_file(
            content=file_bytes,
            filename="plantilla_v1.xlsx",
            env="development",
            folder="plantillas_maestras",
        )
        # Descargar archivo
        content = await service.download_file(item_id="ABC123...")
        # Listar archivos
        files = await service.list_files(env="development", folder="plantillas_maestras")
    """

    def __init__(self, config: Optional[OneDriveConfig] = None):
        self.config = config or OneDriveConfig()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def execute_batch(self, requests_payload: list[dict]) -> list[dict]:
        """
        Ejecuta un lote (Batch) de hasta 20 peticiones individuales hacia Graph API.
        requests_payload debe ser una lista de diccionarios:
        [{"id": "1", "method": "GET", "url": "/users/..."}]
        """
        if not requests_payload:
            return []

        token = await self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = f"{GRAPH_BASE}/$batch"
        payload = {"requests": requests_payload}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 401:
                token = await self._force_refresh_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.post(url, headers=headers, json=payload)

            resp.raise_for_status()
            data = resp.json()
            return data.get("responses", [])


# === SINGLETON ================================================================
@lru_cache(maxsize=1)
def get_onedrive_service() -> OneDriveService:
    """Devuelve instancia singleton del servicio."""
    return OneDriveService()
