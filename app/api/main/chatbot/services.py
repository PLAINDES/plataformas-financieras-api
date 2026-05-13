# app/api/main/chatbot/services.py
import httpx, re, asyncio, logging
from app.core.config import settings
from app.api.main.chatbot.constants import (
    SYSTEM_PROMPT_TEMPLATE,
    FALLBACK_MODELS,
    GENERATION_CONFIG,
    ENFORCEMENT_MODEL_ACK,
    get_enforced_user_message
)
from app.api.main.chatbot.schemas import ChatRequest, ChatResponse, AnalyzeCompaniesRequest, YahooFinanceResponse
from app.api.main.chatbot.utils import extract_tickers, extract_beta_update, build_form_context
from app.api.main.chatbot.boa import calculate_sector_beta

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

async def generate_chat_response(request: ChatRequest) -> ChatResponse:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("API Key de Gemini no configurada en el servidor.")


    # Elimina modelos duplicados
    seen = set()
    models_to_try = []
    for model, version in FALLBACK_MODELS:
        if model not in seen:
            seen.add(model)
            models_to_try.append((model, version))

    # Preparamos el contexto del formulario para inyectarlo al prompt
    form_context = build_form_context(request.form_data)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(form_data_context=form_context)

    # Construimos el array de contenidos para enviar a Gemini
    contents = []
    contents.append({"role": "user", "parts": [{"text": system_prompt}]})
    contents.append({"role": "user", "parts": [{"text": ENFORCEMENT_MODEL_ACK}]})

    for msg in request.history:
        contents.append(msg.model_dump())

    # Agregamos el historial pasado
    for msg in request.history:
        contents.append(msg.model_dump())

    enforced_message = get_enforced_user_message(request.message)
    contents.append({"role": "user", "parts": [{"text": enforced_message}]})

    # Agregamos el mensaje actual del usuario
    contents.append({"role": "user", "parts": [{"text": request.message}]})

    payload = {
        "contents": contents,
        "generationConfig": GENERATION_CONFIG
    }

    # Base URL genérica de Gemini
    data = None
    last_exception = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        for model, version in models_to_try:
            url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={api_key}"
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                logger.info(f"Éxito con el modelo: {model}")
                break

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                last_exception = e

                # Hacemos fallback SOLO en errores de capacidad (503) o rate limit (429)
                if status == 503:
                    logger.warning(f"Modelo {model} saturado (Error {status}). Intentando fallback...")
                    continue
                elif status == 429:
                    logger.warning(f"Rate limit alcanzado para el modelo {model} (Error {status}). Intentando fallback...")
                    continue
                elif status == 404:
                    logger.warning(f"Modelo {model} no encontrado (Error {status}). Intentando fallback...")
                    continue
                else:
                    logger.error(f"Error {status} irrecuperable con el modelo {model}.")
                    raise e

            except httpx.RequestError as e:
                last_exception = e
                logger.warning(f"Error de red con el modelo {model}: {str(e)}. Intentando fallback...")
                continue

    if not data:
        logger.error("ALERTA: Todos los modelos de fallback fallaron.")
        raise last_exception or Exception("Fallo en la comunicación con Gemini API tras agotar los fallbacks.")

    raw_response = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

    # Procesamos la respuesta usando nuestras utilidades
    tickers = extract_tickers(raw_response)
    new_beta = extract_beta_update(raw_response)

    # Limpiamos los tags técnicos de la respuesta final
    clean_text = raw_response

    # Esta regex elimina "TICKERS:" y todo lo que le siga en esa misma línea
    clean_text = re.sub(r'TICKERS:.*', '', clean_text, flags=re.IGNORECASE).strip()

    # Elimina "BETA_UPDATE:" y el valor numérico asociado
    if new_beta is not None:
        clean_text = re.sub(r'BETA_UPDATE:\s*[\d.]+', '', clean_text, flags=re.IGNORECASE).strip()

    #clean_text = clean_text.strip()

    return ChatResponse(
        text=clean_text,
        tickers=tickers,
        new_beta=new_beta,
        raw_history_appends=[
            {"role": "user", "parts": [{"text": request.message}]},
            {"role": "model", "parts": [{"text": raw_response}]}
        ]
    )

async def process_company_analysis(request: AnalyzeCompaniesRequest) -> YahooFinanceResponse:
    """
    Ejecuta el script boa.py (Yahoo Finance) de forma asíncrona usando threads
    para no bloquear el servidor FastAPI mientras hace las descargas.
    """
    result = await asyncio.to_thread(calculate_sector_beta, request.tickers)

    return YahooFinanceResponse(**result)
