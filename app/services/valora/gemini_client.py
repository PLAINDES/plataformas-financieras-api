# app/services/valora/gemini_client.py
"""
Cliente compartido para llamadas a Gemini desde los servicios de Valora.
Maneja fallback entre modelos y errores comunes.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_VERSION = "v1"

FALLBACK_MODELS = [
    (GEMINI_MODEL, GEMINI_API_VERSION),
    ("gemini-2.5-pro", "v1"),
    ("gemini-3.5-flash-lite", "v1"),
    ("gemini-3.1-flash-lite", "v1beta"),
]

GEMINI_API_BASE_URL = (
    "https://generativelanguage.googleapis.com/{version}/models/{model}"
    ":generateContent?key={api_key}"
)


async def call_gemini(payload: dict) -> tuple[str | None, str | None]:
    """
    Llama a Gemini con fallback entre modelos configurados.

    Args:
        payload: Payload JSON completo para la API de Gemini.

    Returns:
        Tuple (texto_respuesta, modelo_usado). Si falla todo retorna (None, None).
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.info("[GEMINI] GEMINI_API_KEY no configurada; omitiendo llamada.")
        return None, None

    last_exception: Exception | None = None
    model_used: str | None = None
    data_json: dict | None = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        for model, version in FALLBACK_MODELS:
            url = GEMINI_API_BASE_URL.format(
                version=version, model=model, api_key=api_key
            )
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data_json = response.json()
                model_used = model
                logger.info(f"[GEMINI] Éxito con el modelo: {model}")
                break
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                last_exception = e
                if status in (503, 429, 404):
                    logger.warning(
                        f"[GEMINI] Modelo {model} error {status}; intentando fallback..."
                    )
                    continue
                logger.error(f"[GEMINI] Error {status} irrecuperable con {model}.")
                return None, None
            except httpx.RequestError as e:
                last_exception = e
                logger.warning(
                    f"[GEMINI] Error de red con {model}: {e}; intentando fallback..."
                )
                continue
        else:
            logger.error("[GEMINI] Todos los modelos fallaron.")
            return None, None

    raw_text = (
        (data_json or {})
        .get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    return raw_text, model_used
