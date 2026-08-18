import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

TOKEN_MAX_ATTEMPTS = 3
TOKEN_RETRY_BASE_DELAY_SECONDS = 1.5
TOKEN_TIMEOUT = httpx.Timeout(30.0, connect=20.0)


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
        async with httpx.AsyncClient(timeout=TOKEN_TIMEOUT) as client:
            for attempt in range(1, TOKEN_MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post(url, data=data)
                    resp.raise_for_status()
                    token_data = resp.json()
                    self._access_token = token_data["access_token"]
                    expires_in = int(token_data.get("expires_in", 3600))
                    self._token_expires_at = time.time() + expires_in
                    return self._access_token
                except httpx.HTTPStatusError:
                    # Invalid credentials and other HTTP responses are not
                    # transient transport failures and must remain visible.
                    raise
                except httpx.TransportError as exc:
                    if attempt == TOKEN_MAX_ATTEMPTS:
                        logger.error(
                            "No se pudo conectar con Microsoft OAuth tras %s intentos",
                            TOKEN_MAX_ATTEMPTS,
                        )
                        raise

                    delay = TOKEN_RETRY_BASE_DELAY_SECONDS * attempt
                    logger.warning(
                        "Microsoft OAuth no disponible (intento %s/%s, %s). "
                        "Reintentando en %.1f segundos.",
                        attempt,
                        TOKEN_MAX_ATTEMPTS,
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError("No se pudo obtener el token de Microsoft OAuth")

    async def _force_refresh_token(self) -> str:
        self._access_token = None
        self._token_expires_at = 0
        return await self._get_token()

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
