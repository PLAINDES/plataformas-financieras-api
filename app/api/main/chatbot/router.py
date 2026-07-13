import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.main.chatbot.boa import (
    calculate_subsectores_boa,
    cancel_job,
    create_job,
    delete_job,
    fail_job,
    get_active_jobs,
    get_job,
    get_existing_tickers_with_values,
)
from app.api.main.chatbot.prompts import build_generate_subsectors_prompt
from app.api.main.chatbot.schemas import (
    AnalyzeCompaniesRequest,
    ChatRequest,
    ChatResponse,
    DefaultResponse,
    GenerateSubsectorsRequest,
    SubsectorBoaProgressResponse,
    SubsectorBoaResponse,
)
from app.api.main.chatbot.services import generate_chat_response
from app.api.main.chatbot.utils import extract_subsectors
from app.db.database import get_db


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
        return ChatResponse(
            text="Disculpa, tengo problemas técnicos. Notificalo al equipo de soporte por favor.",
            tickers=[],
            new_beta=None
        )

@router.post("/calculate-subsectores-boa", response_model=SubsectorBoaResponse)
async def start_subsectores_boa(request: AnalyzeCompaniesRequest):
    # Obtener los tickers que ya tienen valores válidos en la base de datos
    existing_tickers = get_existing_tickers_with_values()
    
    # Filtrar la lista de tickers para procesar solo los que no existen
    tickers_to_process = [t for t in request.tickers if t not in existing_tickers]
    
    # Calcular cuántos se omitieron
    omitted_count = len(request.tickers) - len(tickers_to_process)
    
    # Si no hay tickers nuevos para procesar, retornar inmediatamente
    if not tickers_to_process:
        return SubsectorBoaResponse(
            success=True,
            valid_companies=[],
            errors=[],
            total=len(request.tickers),
            processed=0,
            failed=0,
            job_id=None,
            message=f"Se omitieron {omitted_count} tickers que ya tenían valores válidos. No hay nuevos tickers para procesar."
        )

    # Crear el job solo con los tickers que se van a procesar
    job_id = create_job(len(tickers_to_process))

    def _run():
        try:
            calculate_subsectores_boa(tickers_to_process, job_id=job_id)
        except Exception as e:
            fail_job(job_id, str(e))
            logger.exception(f"Error en background BOA job {job_id}")

    threading.Thread(target=_run, daemon=True).start()

    job = get_job(job_id)
    return SubsectorBoaResponse(
        success=True,
        valid_companies=[],
        errors=[],
        total=job["total"],
        processed=0,
        failed=0,
        job_id=job_id,
        message=f"Procesando {len(tickers_to_process)} tickers. Se omitieron {omitted_count} que ya tenían valores."
    )

@router.get("/boa-active-jobs")
async def list_active_jobs():
    return get_active_jobs()

@router.get("/boa-progress/{job_id}")
async def get_boa_progress(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return SubsectorBoaProgressResponse(
        status=job["status"],
        total=job["total"],
        processed=job["processed"],
        failed=job["failed"],
        errors=job.get("errors", []),
        result=job.get("result"),
    )

@router.post("/boa-cancel/{job_id}")
async def cancel_boa_job(job_id: str):
    cancel_job(job_id)
    return {"success": True, "message": "Cancelación solicitada"}

@router.post("/boa-job/{job_id}/delete")
async def delete_boa_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    delete_job(job_id)
    return {"success": True, "message": "Job eliminado"}
