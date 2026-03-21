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

import os
import logging
from typing import Literal, Optional
from functools import lru_cache
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# === TIPOS ====================================================================
Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]

ROOT_FOLDER = "PLATAFORMAS_FINANCIERAS"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OneDriveConfig:
    """Lee credenciales desde variables de entorno / settings."""

    def __init__(self):
        self.client_id: str = getattr(settings, "AZURE_CLIENT_ID", os.getenv("AZURE_CLIENT_ID", ""))
        self.client_secret: str = getattr(settings, "AZURE_CLIENT_SECRET", os.getenv("AZURE_CLIENT_SECRET", ""))
        self.tenant_id: str = getattr(settings, "AZURE_TENANT_ID", os.getenv("AZURE_TENANT_ID", ""))
        self.user_email: str = getattr(settings, "ONEDRIVE_USER_EMAIL", os.getenv("ONEDRIVE_USER_EMAIL", ""))

    def is_configured(self) -> bool:
        return all([self.client_id, self.client_secret, self.tenant_id, self.user_email])


class OneDriveService:
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

    # === AUTH =================================================================

    async def _get_token(self) -> str:
        """Obtiene un access token via OAuth2 client_credentials flow."""
        if self._access_token:
            return self._access_token

        url = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            token_data = resp.json()
            self._access_token = token_data["access_token"]
            return self._access_token

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # === PATHS ================================================================

    @staticmethod
    def build_path(env: Environment, folder: Folder, filename: Optional[str] = None) -> str:
        """
        Construye el path relativo dentro del OneDrive del usuario.
        Ej: PLATAFORMAS_FINANCIERAS/development/plantillas_maestras/archivo.xlsx
        """
        parts = [ROOT_FOLDER, env, folder]
        if filename:
            parts.append(filename)
        return "/".join(parts)

    def _drive_url(self, path: Optional[str] = None, item_id: Optional[str] = None) -> str:
        """Construye la URL base de Graph para el drive del usuario."""
        base = f"{GRAPH_BASE}/users/{self.config.user_email}/drive"
        if item_id:
            return f"{base}/items/{item_id}"
        if path:
            return f"{base}/root:/{path}"
        return f"{base}/root"

    # === HEALTH CHECK =========================================================

    async def check_connection(self) -> dict:
        """
        Valida que la conexión a OneDrive funciona.
        Retorna info sobre la cuenta conectada y el drive accesible.
        
        Con client_credentials grant no se puede usar /me, entonces 
        se verifica acceso directo al drive del usuario.
        """
        try:
            token = await self._get_token()
            headers = self._headers(token)
            # Use direct user email instead of /me with app-only auth
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return {
                    "status": "connected",
                    "drive_id": data.get("id"),
                    "owner_email": self.config.user_email,
                    "owner_display_name": data.get("owner", {}).get("displayName", "Unknown"),
                }
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            raise

    # === FOLDER SETUP =========================================================

    async def ensure_folder_structure(self, structure: dict) -> dict:
        """
        Crea la estructura de carpetas especificada.
        
        IMPORTANTE: `structure` es OBLIGATORIO. No hay plantilla por defecto.
        
        Ejemplo de estructura:
        ```python
        structure = {
            "PLATAFORMAS_FINANCIERAS": {
                "development": ["plantillas_maestras", "kapital", "valora"],
                "production": ["plantillas_maestras", "kapital", "valora"],
                "test": ["plantillas_maestras", "kapital", "valora"],
            }
        }
        await service.ensure_folder_structure(structure)
        ```
        
        También soporta estructuras planas:
        ```python
        structure = {
            "proyecto_x": ["reportes", "datos", "backups"]
        }
        ```
        
        Args:
            structure: Dict con la estructura de carpetas a crear.
                      Claves = nombres de carpetas raíz
                      Valores = dict de subcarpetas o lista de carpetas
        
        Returns:
            dict con keys "created", "errors", "success"
        """
        if not structure:
            raise ValueError("structure es requerido y no puede estar vacío")

        token = await self._get_token()
        headers = self._headers(token)

        created = []
        errors = []

        async with httpx.AsyncClient() as client:
            for root_name, sub_structure in structure.items():
                try:
                    # Create root folder
                    root_result = await self._ensure_folder(client, headers, "root", root_name)
                    created.append(root_name)

                    # Create subfolders
                    if isinstance(sub_structure, dict):
                        # Subfolder structure is a dict (levels)
                        for env, folders_list in sub_structure.items():
                            await self._ensure_folder(client, headers, f"root:/{root_name}", env)
                            created.append(f"{root_name}/{env}")

                            if isinstance(folders_list, list):
                                for folder in folders_list:
                                    await self._ensure_folder(client, headers, f"root:/{root_name}/{env}", folder)
                                    created.append(f"{root_name}/{env}/{folder}")
                    elif isinstance(sub_structure, list):
                        # Subfolder structure is a flat list
                        for folder in sub_structure:
                            await self._ensure_folder(client, headers, f"root:/{root_name}", folder)
                            created.append(f"{root_name}/{folder}")
                except Exception as e:
                    errors.append(f"{root_name}: {str(e)}")

        logger.info(f"OneDrive folder structure setup complete. Created: {len(created)}, Errors: {len(errors)}")
        return {
            "created": created,
            "errors": errors,
            "success": len(errors) == 0,
        }

    async def _ensure_folder(
        self, client: httpx.AsyncClient, headers: dict, parent_path: str, folder_name: str
    ) -> dict:
        """Crea una carpeta si no existe. Retorna el ID del item."""
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/{parent_path}/children"
        payload = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "replace",
        }
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            logger.warning(f"Could not create folder '{folder_name}': {resp.text}")
            return {}
        return resp.json()

    # === UPLOAD ===============================================================

    async def upload_file(
        self,
        content: bytes,
        filename: str,
        env: Environment,
        folder: Folder,
    ) -> dict:
        """
        Sube un archivo a OneDrive.
        Para archivos >4MB usa upload session (chunked).
        Retorna el item metadata de OneDrive (incluye 'id' para guardar en BD).
        """
        token = await self._get_token()
        path = self.build_path(env, folder, filename)

        if len(content) < 4 * 1024 * 1024:
            return await self._simple_upload(token, path, content)
        else:
            return await self._chunked_upload(token, path, content)

    async def _simple_upload(self, token: str, path: str, content: bytes) -> dict:
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{path}:/content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(url, headers=headers, content=content)
            resp.raise_for_status()
            return resp.json()

    async def _chunked_upload(self, token: str, path: str, content: bytes) -> dict:
        """Upload session para archivos grandes (>4MB)."""
        # 1. Create upload session
        session_url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{path}:/createUploadSession"
        headers = self._headers(token)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(session_url, headers=headers, json={})
            resp.raise_for_status()
            upload_url = resp.json()["uploadUrl"]

            # 2. Upload in chunks of 5MB
            chunk_size = 5 * 1024 * 1024
            total = len(content)
            start = 0
            result = {}
            while start < total:
                end = min(start + chunk_size, total)
                chunk = content[start:end]
                chunk_headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end - 1}/{total}",
                    "Content-Type": "application/octet-stream",
                }
                resp = await client.put(upload_url, headers=chunk_headers, content=chunk)
                if resp.status_code in (200, 201):
                    result = resp.json()
                start = end
            return result

    # === DOWNLOAD =============================================================

    async def download_file(self, item_id: str) -> bytes:
        """Descarga un archivo por su item ID de OneDrive."""
        token = await self._get_token()
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}/content"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content

    async def get_download_url(self, item_id: str) -> str:
        """Obtiene una URL temporal de descarga directa para el item."""
        token = await self._get_token()
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
        headers = self._headers(token)
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("@microsoft.graph.downloadUrl", "")

    # === LIST =================================================================

    async def list_files(self, path: Optional[str] = None, env: Optional[Environment] = None, folder: Optional[Folder] = None) -> list[dict]:
        """
        Lista TODOS los archivos (no carpetas) en una ruta.
        
        Usar con path genérico:
             files = await service.list_files(path="PLATAFORMAS_FINANCIERAS/development/kapital")
          
        Args:
            path: Ruta genérica en OneDrive (toma precedencia)
            env: Ambiente (development|production|test) - deprecated
            folder: Carpeta específica - deprecated
        
        Returns:
            Lista de dicts con metadatos de archivos
        """
        token = await self._get_token()
        headers = self._headers(token)

        # Determinar qué path usar
        if path:
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{path}:/children"
        elif env and folder:
            # Legacy: usar env/folder
            constructed_path = self.build_path(env, folder)
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{constructed_path}:/children"
        else:
            raise ValueError("Necesitas proporcionar 'path' o ambos 'env' y 'folder'")

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            items = resp.json().get("value", [])
            # Filter only files (not folders)
            return [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": "file",
                    "size": item.get("size"),
                    "created_at": item.get("createdDateTime"),
                    "modified_at": item.get("lastModifiedDateTime"),
                    "web_url": item.get("webUrl"),
                }
                for item in items
                if "folder" not in item  # Only files
            ]

    async def delete_file(self, item_id: str) -> None:
        """Elimina un archivo de OneDrive por su item ID."""
        token = await self._get_token()
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers)
            if resp.status_code != 204:
                logger.warning(f"Unexpected status deleting item {item_id}: {resp.status_code}")

    # === FOLDER OPERATIONS ====================================================

    async def list_folders(self, path: Optional[str] = None) -> list[dict]:
        """
        Lista solo las CARPETAS en una ruta (no archivos).
        Si path es None, lista desde root.
        Retorna lista de dicts con: id, name, type, created_at, modified_at
        """
        token = await self._get_token()
        headers = self._headers(token)

        if path:
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{path}:/children"
        else:
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root/children"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                logger.warning(f"Path not found: {path}")
                return []
            resp.raise_for_status()
            items = resp.json().get("value", [])
            # Filter only folders
            folders = [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": "folder" if "folder" in item else "file",
                    "created_at": item.get("createdDateTime"),
                    "modified_at": item.get("lastModifiedDateTime"),
                    "folder": item.get("folder"),
                }
                for item in items
                if "folder" in item
            ]
            logger.debug(f"Found {len(folders)} folders in {path or 'root'}")
            return folders

    async def delete_folder_recursive(self, item_id: str) -> dict:
        """
        Elimina una carpeta y TODO su contenido de forma recursiva.
        Esta operación es destructiva.
        Retorna stats sobre lo que se eliminó.
        """
        token = await self._get_token()
        headers = self._headers(token)
        deleted_count = {"files": 0, "folders": 0}

        async def delete_recursively(id_to_delete: str) -> None:
            """Recursively delete folder contents then the folder itself."""
            url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{id_to_delete}/children"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    items = resp.json().get("value", [])
                    for item in items:
                        item_id = item.get("id")
                        is_folder = "folder" in item
                        if is_folder:
                            await delete_recursively(item_id)
                        else:
                            delete_url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
                            del_resp = await client.delete(delete_url, headers=headers)
                            if del_resp.status_code == 204:
                                deleted_count["files"] += 1

            # Delete the folder itself
            delete_folder_url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{id_to_delete}"
            async with httpx.AsyncClient() as client:
                resp = await client.delete(delete_folder_url, headers=headers)
                if resp.status_code == 204:
                    deleted_count["folders"] += 1

        await delete_recursively(item_id)
        logger.info(f"Deleted folder recursively: {deleted_count}")
        return deleted_count

    async def get_folder_by_path(self, path: str) -> Optional[dict]:
        """Obtiene info de una carpeta por su ruta."""
        token = await self._get_token()
        headers = self._headers(token)
        url = f"{GRAPH_BASE}/users/{self.config.user_email}/drive/root:/{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()


# === SINGLETON ================================================================
@lru_cache(maxsize=1)
def get_onedrive_service() -> OneDriveService:
    """Devuelve instancia singleton del servicio."""
    return OneDriveService()
