# app/api/main/chatbot/router.py
from fastapi import APIRouter
from app.api.main.chatbot.schemas import AnalyzeCompaniesRequest, ChatRequest, ChatResponse, YahooFinanceResponse
from app.api.main.chatbot.services import generate_chat_response, process_company_analysis
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        response = await generate_chat_response(request)
        return response
    except Exception as e:
        logger = logging.getLogger("uvicorn.error")
        if hasattr(e, 'response'):
            logger.error(f"FALLO API GEMINI: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"ERROR DESCONOCIDO: {str(e)}")
        # En caso de error, proveemos fallbacks seguros directamente desde el back
        return ChatResponse(
            text="Disculpa, tengo problemas técnicos. Notificalo al equipo de soporte por favor.",
            tickers=[],
            new_beta=None
        )

@router.post("/analyze-companies", response_model=YahooFinanceResponse)
async def analyze_companies(request: AnalyzeCompaniesRequest):
    try:
        response = await process_company_analysis(request)
        return response
    except Exception as e:
        logger.error(f"Error procesando tickers en Yahoo Finance: {str(e)}")
        return YahooFinanceResponse(success=False, valid_companies=[])
