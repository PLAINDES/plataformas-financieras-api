import logging
from urllib.parse import quote

import httpx

from .config import GRAPH_BASE

logger = logging.getLogger(__name__)


class OneDriveExcelMixin:
    """Mixin para interactuar con sesiones y cálculo de Excel Online."""

    # === EXCEL SESSION MANAGEMENT ============================================

    async def _create_workbook_session(
        self, item_id: str, persist_changes: bool = False
    ) -> str:
        """
        Crea una sesión de trabajo (workbook session) en Excel Online.
        Todas las operaciones dentro de la misma sesión comparten el
        mismo contexto de cálculo.

        Args:
            item_id: ID del archivo en OneDrive
            persist_changes: Si True, los cambios se guardan en el archivo.
                             Si False, sesión de solo lectura (no persiste).
        Returns:
            session_id: ID de la sesión creada
        """
        import time

        t_start = time.perf_counter()
        token = await self._get_token()
        headers = self._headers(token)
        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/createSession"
        )
        payload = {"persistChanges": persist_changes}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        session_id = data.get("id")
        logger.info(f"[EXCEL TIMER] create_workbook_session: {time.perf_counter()-t_start:.3f}s")
        return session_id

    async def _close_workbook_session(self, item_id: str, session_id: str) -> None:
        """Cierra una sesión de trabajo de Excel Online."""
        import time

        t_start = time.perf_counter()
        token = await self._get_token()
        headers = self._headers(token)
        headers["workbook-session-id"] = session_id
        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/closeSession"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, headers=headers)
            logger.debug(f"Workbook session closed: {session_id}")
        except Exception as e:
            logger.warning(f"Could not close workbook session {session_id}: {e}")
        logger.info(f"[EXCEL TIMER] close_workbook_session: {time.perf_counter()-t_start:.3f}s")

    async def _refresh_workbook_session(self, item_id: str, session_id: str) -> None:
        """Reinicia el timeout de 5 minutos de una sesión activa."""
        token = await self._get_token()
        headers = self._headers(token)
        headers["workbook-session-id"] = session_id
        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/refreshSession"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers)
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"No se pudo refrescar la sesión {session_id}: {e}")

    # === EXCEL OPERATIONS ====================================================

    async def force_calculate_excel(self, item_id: str, session_id: str | None = None):
        """
        Fuerza a Excel Online a recalcular todas las fórmulas del libro.
        Si se pasa session_id, el cálculo se hace dentro de esa sesión
        (necesario para que read_excel_cell vea los resultados).
        """
        import time

        t_start = time.perf_counter()
        token = await self._get_token()
        headers = self._headers(token)
        if session_id:
            headers["workbook-session-id"] = session_id

        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/application/calculate"
        )
        # fullRebuild recalcula todo, incluyendo dependencias entre hojas
        payload = {"calculationType": "fullRebuild"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 401:
                token = await self._force_refresh_token()
                headers = self._headers(token)
                if session_id:
                    headers["workbook-session-id"] = session_id
                resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        logger.info(f"[EXCEL TIMER] force_calculate_excel: {time.perf_counter()-t_start:.3f}s")

    async def read_excel_cell(
        self,
        item_id: str,
        sheet_name: str,
        cell_address: str,
        session_id: str | None = None,
    ):
        """
        Lee un rango/celda de un Excel alojado en OneDrive.
        Si se pasa session_id, la lectura se hace dentro de esa sesión
        para aprovechar el contexto de cálculo compartido.
        """
        import time

        t_start = time.perf_counter()
        token = await self._get_token()
        headers = self._headers(token)
        if session_id:
            headers["workbook-session-id"] = session_id

        encoded_sheet = quote(sheet_name)
        encoded_cell = quote(cell_address)
        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/worksheets('{encoded_sheet}')/range(address='{encoded_cell}')"
        )

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401:
                token = await self._force_refresh_token()
                headers = self._headers(token)
                if session_id:
                    headers["workbook-session-id"] = session_id
                resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        logger.info(
            f"[EXCEL TIMER] read_excel_cell({sheet_name}!{cell_address}): "
            f"{time.perf_counter()-t_start:.3f}s"
        )
        return {
            "values": data.get("values"),
            "text": data.get("text"),
            "formulas": data.get("formulas"),
        }

    async def get_excel_chart_image(
        self,
        item_id: str,
        sheet_name: str,
        chart_name: str,
        session_id: str | None = None,
    ) -> str:
        """
        Extrae la imagen en base64 de un gráfico de Excel usando Microsoft Graph.
        """

        token = await self._get_token()
        headers = self._headers(token)
        headers["Content-Type"] = "application/json"

        if session_id:
            headers["workbook-session-id"] = session_id

        # Codificar los nombres para evitar errores en la URL
        encoded_sheet = quote(sheet_name)
        encoded_chart = quote(chart_name)

        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/worksheets('{encoded_sheet}')/charts('{encoded_chart}')/image(width=0,height=0,fittingMode='fit')"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)

            # Manejo estándar de token expirado que ya tienes en otros métodos
            if resp.status_code == 401:
                token = await self._force_refresh_token()
                headers = self._headers(token)
                headers["Content-Type"] = "application/json"
                if session_id:
                    headers["workbook-session-id"] = session_id
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                error_data = resp.text
                logger.error(f"Error extrayendo gráfico {chart_name}: {error_data}")
                return ""  # Retornamos string vacío para no romper la generación del reporte

            data = resp.json()
            return data.get("value", "")

    async def read_excel_cell_with_session(
        self,
        item_id: str,
        sheet_name: str,
        cell_address: str,
    ):
        """
        Lee una celda forzando recálculo completo dentro de una sesión
        de Excel Online. Esto garantiza que las fórmulas (VLOOKUP,
        referencias cruzadas entre hojas, etc.) se resuelvan
        correctamente y devuelvan el valor calculado, no #N/D o #REF!.

        Flujo:
          1. Crea una sesión de solo lectura
          2. Fuerza fullRebuild de todas las fórmulas
          3. Lee la celda (ya con fórmulas evaluadas)
          4. Cierra la sesión
        """
        session_id = await self._create_workbook_session(item_id, persist_changes=False)
        try:
            # Forzar recálculo completo dentro de la sesión
            await self.force_calculate_excel(item_id, session_id=session_id)
            # Leer la celda con las fórmulas ya evaluadas
            result = await self.read_excel_cell(
                item_id, sheet_name, cell_address, session_id=session_id
            )
            return result
        finally:
            await self._close_workbook_session(item_id, session_id)

    async def update_excel_cell(
        self,
        item_id: str,
        sheet_name: str,
        cell_address: str,
        value,
        session_id: str | None = None,
    ):
        """Actualiza un rango/celda de un Excel alojado en OneDrive."""
        import time

        t_start = time.perf_counter()
        token = await self._get_token()
        headers = self._headers(token)
        if session_id:
            headers["workbook-session-id"] = session_id

        encoded_sheet = quote(sheet_name)
        encoded_cell = quote(cell_address)
        url = (
            f"{GRAPH_BASE}/users/{self.config.user_email}/drive/items/{item_id}"
            f"/workbook/worksheets('{encoded_sheet}')/range(address='{encoded_cell}')"
        )
        payload = {"values": [[value]]}

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.patch(url, headers=headers, json=payload)
            if resp.status_code == 401:
                token = await self._force_refresh_token()
                headers = self._headers(token)
                if session_id:
                    headers["workbook-session-id"] = session_id
                resp = await client.patch(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        logger.info(
            f"[EXCEL TIMER] update_excel_cell({sheet_name}!{cell_address}): "
            f"{time.perf_counter()-t_start:.3f}s"
        )
        return data.get("values")
