# app/api/storage/onedrive_router.py
"""
Router genérico para operaciones de OneDrive.
Servicio REUTILIZABLE para cualquier operación con archivos/carpetas en OneDrive.

Endpoints:
  POST   /storage/onedrive/health         -> Validar conexión
  POST   /storage/onedrive/setup          -> Crear estructura de carpetas
  GET    /storage/onedrive/folders        -> Listar carpetas
  GET    /storage/onedrive/folder-info    -> Obtener info de una carpeta
  DELETE /storage/onedrive/item/{id}      -> Eliminar item (archivo o carpeta)
  DELETE /storage/onedrive/folder/{id}    -> Eliminar carpeta (recursivo)
"""

import io
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig

router = APIRouter(
    prefix="/storage/onedrive",
    tags=["Storage - OneDrive"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)


# === HEALTH CHECK =============================================================
@router.post("/health")
async def check_onedrive_connection():
    """
    Valida que la conexión a OneDrive funciona.
    Retorna información sobre la cuenta conectada.
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "OneDrive no está configurado. Verifica que estas variables de entorno estén presente: "
                "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, ONEDRIVE_USER_EMAIL"
            ),
        )

    service = get_onedrive_service()
    try:
        info = await service.check_connection()
        return {
            "status": "ok",
            "message": "Conectado a OneDrive exitosamente",
            "account": info,
        }
    except Exception as e:
        logger.error(f"OneDrive connection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo conectar a OneDrive: {str(e)}",
        )


# === SETUP ====================================================================
@router.post("/setup")
async def setup_onedrive_structure(
    body: dict = Body(..., example={
        "PLATAFORMAS_FINANCIERAS": {
            "development": ["plantillas_maestras", "kapital", "valora"],
            "production": ["plantillas_maestras", "kapital", "valora"],
            "test": ["plantillas_maestras", "kapital", "valora"]
        }
    })
):
    """
    Crea la estructura de carpetas especificada en OneDrive.
    
    La estructura es OBLIGATORIA. No hay plantilla por defecto.
    
    Ejemplos de estructura:
    
    **Estructura jerárquica (3 niveles):**
    ```json
    {
      "PLATAFORMAS_FINANCIERAS": {
        "development": ["plantillas_maestras", "kapital", "valora"],
        "production": ["plantillas_maestras", "kapital", "valora"],
        "test": ["plantillas_maestras", "kapital", "valora"]
      }
    }
    ```
    
    **Estructura plana (2 niveles):**
    ```json
    {
      "proyecto_x": ["reportes", "datos", "backups"]
    }
    ```
    
    **Estructura mixta:**
    ```json
    {
      "raiz1": {
        "subnivel": ["carpeta_a", "carpeta_b"]
      },
      "raiz2": ["simple1", "simple2"]
    }
    ```
    """
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body es OBLIGATORIO. Proporciona la estructura de carpetas en formato JSON.",
        )

    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OneDrive no está configurado.",
        )

    service = get_onedrive_service()
    try:
        result = await service.ensure_folder_structure(body)
        return {
            "status": "ok" if result["success"] else "partial_error",
            "message": "Estructura de carpetas configurada",
            "created_count": len(result["created"]),
            "created": result["created"],
            "errors": result["errors"],
        }
    except Exception as e:
        logger.error(f"OneDrive setup failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al configurar estructura: {str(e)}",
        )


# === LIST FOLDERS =============================================================
@router.get("/folders")
async def list_onedrive_folders(
    path: Optional[str] = Query(None,
                                description="Ruta donde listar carpetas (ej: PLATAFORMAS_FINANCIERAS/development)")
):
    """
    Lista todas las CARPETAS en una ruta de OneDrive.
    Si 'path' no se proporciona, lista desde root.
    
    Ejemplo:
      GET /storage/onedrive/folders?path=PLATAFORMAS_FINANCIERAS
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        folders = await service.list_folders(path=path)
        return {
            "path": path or "root",
            "folder_count": len(folders),
            "folders": folders,
        }
    except Exception as e:
        logger.error(f"Error listing folders: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al listar carpetas: {str(e)}")


# === FOLDER INFO ==============================================================
@router.get("/folder-info")
async def get_folder_info(
    path: str = Query(...,
                      description="Ruta absoluta de la carpeta (ej: PLATAFORMAS_FINANCIERAS/development/kapital)")
):
    """
    Obtiene información detallada de una carpeta específica.
    Retorna: id, name, created_at, modified_at, web_url, etc.
    
    Ejemplo:
      GET /storage/onedrive/folder-info?path=PLATAFORMAS_FINANCIERAS/development
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        info = await service.get_folder_by_path(path)
        if not info:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Carpeta no encontrada: {path}")
        return {
            "id": info.get("id"),
            "name": info.get("name"),
            "created_at": info.get("createdDateTime"),
            "modified_at": info.get("lastModifiedDateTime"),
            "web_url": info.get("webUrl"),
            "parent_reference": info.get("parentReference"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting folder info: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al obtener info: {str(e)}")


# === DELETE ITEM (FILE) =======================================================
@router.delete("/item/{item_id}")
async def delete_onedrive_item(item_id: str):
    """
    Elimina un archivo específico de OneDrive.
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        await service.delete_file(item_id)
        return {
            "status": "deleted",
            "item_id": item_id,
        }
    except Exception as e:
        logger.error(f"Error deleting item: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al eliminar: {str(e)}")


# === DELETE FOLDER (RECURSIVE) ================================================
@router.delete("/folder/{folder_id}")
async def delete_onedrive_folder_recursive(folder_id: str):
    """
    Elimina una CARPETA completa y todo su contenido de forma RECURSIVA.
    
    Esta es una operación DESTRUCTIVA.
    Se eliminarán:
      - Todos los archivos dentro de la carpeta
      - Todas las subcarpetas y su contenido
      - No se puede deshacer
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        result = await service.delete_folder_recursive(folder_id)
        return {
            "status": "deleted",
            "folder_id": folder_id,
            "deleted": result,
            "warning": "Esta operación es IRREVERSIBLE",
        }
    except Exception as e:
        logger.error(f"Error deleting folder recursively: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al eliminar carpeta: {str(e)}",
        )


# === LIST ALL FILES IN FOLDER =================================================
@router.get("/files")
async def list_all_files_in_folder(
    path: str = Query(..., description="Ruta donde listar archivos (ej: PLATAFORMAS_FINANCIERAS/development/plantillas_maestras)")
):
    """
    Lista TODOS los archivos (no carpetas) en una ruta específica.
    
    Ejemplo:
      GET /storage/onedrive/files?path=PLATAFORMAS_FINANCIERAS/development/plantillas_maestras
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        files = await service.list_files(path=path)
        return {"path": path, "file_count": len(files), "files": files}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al listar archivos: {str(e)}")

@router.post("/excel/read")
async def read_excel_cell(
    item_id: str = Body(...),
    sheet_name: str = Body(...),
    cell: str = Body(...),
):
    """
    Lee una celda/rango del archivo Excel en OneDrive.
    Usa una sesión de Excel Online con recálculo completo (fullRebuild)
    para garantizar que las fórmulas devuelvan el valor calculado real,
    no #N/D o #REF!.
    """
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        values = await service.read_excel_cell_with_session(
            item_id=item_id, sheet_name=sheet_name, cell_address=cell
        )
        return {"item_id": item_id, "sheet_name": sheet_name, "cell": cell, "values": values}
    except Exception as e:
        logger.error(f"Error reading excel cell: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al leer celda: {str(e)}")

@router.post("/excel/update")
async def update_excel_cell(
    item_id: str = Body(...),
    sheet_name: str = Body(...),
    cell: str = Body(...),
    value: object = Body(...),
):
    """Actualiza una celda/rango del archivo Excel en OneDrive."""
    config = OneDriveConfig()
    if not config.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive no configurado")

    service = get_onedrive_service()
    try:
        values = await service.update_excel_cell(
            item_id=item_id,
            sheet_name=sheet_name,
            cell_address=cell,
            value=value,
        )
        return {"item_id": item_id, "sheet_name": sheet_name, "cell": cell, "values": values}
    except Exception as e:
        logger.error(f"Error updating excel cell: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error al actualizar celda: {str(e)}")
