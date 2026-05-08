# app/api/main/chatbot/services.py
import httpx, re, asyncio
from app.core.config import settings
from app.api.main.chatbot.constants import GEMINI_API_URL, SYSTEM_PROMPT_TEMPLATE
from app.api.main.chatbot.schemas import ChatRequest, ChatResponse, AnalyzeCompaniesRequest, YahooFinanceResponse
from app.api.main.chatbot.utils import extract_tickers, extract_beta_update, build_form_context
from app.api.main.chatbot.boa import calculate_sector_beta

async def generate_chat_response(request: ChatRequest) -> ChatResponse:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("API Key de Gemini no configurada en el servidor.")

    # Preparamos el contexto del formulario para inyectarlo al prompt
    form_context = build_form_context(request.form_data)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(form_data_context=form_context)

    # Construimos el array de contenidos para enviar a Gemini
    contents = []

    # Si es el primer mensaje, inyectamos el prompt de sistema
    if not request.history:
        contents.append({"role": "user", "parts": [{"text": system_prompt}]})
        contents.append({"role": "model", "parts": [{"text": "Perfecto. Soy tu asistente especializado en análisis de beta para WACC. ¿Quieres que analice tus datos actuales?"}]})

    # Agregamos el historial pasado
    for msg in request.history:
        contents.append(msg.model_dump())

    # Agregamos el mensaje actual del usuario
    contents.append({"role": "user", "parts": [{"text": request.message}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "topP": 0.8,
            "topK": 40,
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{GEMINI_API_URL}?key={api_key}", json=payload)
        response.raise_for_status()
        data = response.json()

    raw_response = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

    # Procesamos la respuesta usando nuestras utilidades
    tickers = extract_tickers(raw_response)
    new_beta = extract_beta_update(raw_response)

    # Limpiamos los tags técnicos de la respuesta final
    clean_text = raw_response
    if tickers:
        clean_text = re.sub(r'TICKERS:\[.*?\]', '', clean_text, flags=re.IGNORECASE)
    if new_beta is not None:
        clean_text = re.sub(r'BETA_UPDATE:\s*[\d.]+', '', clean_text, flags=re.IGNORECASE)

    clean_text = raw_response

    # Esta regex elimina "TICKERS:" y todo lo que le siga en esa misma línea
    clean_text = re.sub(r'TICKERS:.*', '', clean_text, flags=re.IGNORECASE).strip()

    if new_beta is not None:
        clean_text = re.sub(r'BETA_UPDATE:\s*[\d.]+', '', clean_text, flags=re.IGNORECASE).strip()

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
