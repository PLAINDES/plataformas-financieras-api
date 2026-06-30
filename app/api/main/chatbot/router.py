# app/api/main/chatbot/router.py
import logging
import threading

from fastapi import APIRouter, HTTPException

from app.api.main.chatbot.boa import (
    calculate_subsectores_boa,
    cancel_job,
    create_job,
    delete_job,
    fail_job,
    get_active_jobs,
    get_job,
)
from app.api.main.chatbot.schemas import (
    AnalyzeCompaniesRequest,
    ChatRequest,
    ChatResponse,
    SubsectorBoaProgressResponse,
    SubsectorBoaResponse,
)
from app.api.main.chatbot.services import generate_chat_response

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
    job_id = create_job(len(request.tickers))

    def _run():
        try:
            calculate_subsectores_boa(request.tickers, job_id=job_id)
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
