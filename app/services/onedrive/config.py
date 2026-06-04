import os
from typing import Literal

from app.core.config import settings

Environment = Literal["development", "production", "test"]
Folder = Literal["plantillas_maestras", "kapital", "valora"]

ROOT_FOLDER = "PLATAFORMAS_FINANCIERAS"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OneDriveConfig:
    """Lee credenciales desde variables de entorno / settings."""

    def __init__(self):
        self.client_id: str = getattr(
            settings, "AZURE_CLIENT_ID", os.getenv("AZURE_CLIENT_ID", "")
        )
        self.client_secret: str = getattr(
            settings, "AZURE_CLIENT_SECRET", os.getenv("AZURE_CLIENT_SECRET", "")
        )
        self.tenant_id: str = getattr(
            settings, "AZURE_TENANT_ID", os.getenv("AZURE_TENANT_ID", "")
        )
        self.user_email: str = getattr(
            settings, "ONEDRIVE_USER_EMAIL", os.getenv("ONEDRIVE_USER_EMAIL", "")
        )

    def is_configured(self) -> bool:
        return all(
            [self.client_id, self.client_secret, self.tenant_id, self.user_email]
        )
