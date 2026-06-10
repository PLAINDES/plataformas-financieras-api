import logging
import time

import httpx

logger = logging.getLogger(__name__)


class OneDriveAuthMixin:
    """Mixin para manejar la autenticación con Microsoft Graph API."""

    async def _get_token(self) -> str:
        if self._access_token and time.time() < (self._token_expires_at - 60):
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
            expires_in = int(token_data.get("expires_in", 3600))
            self._token_expires_at = time.time() + expires_in
            return self._access_token

    async def _force_refresh_token(self) -> str:
        self._access_token = None
        self._token_expires_at = 0
        return await self._get_token()

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
