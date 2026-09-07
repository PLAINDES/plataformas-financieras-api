import logging
import threading

import io
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.main.chatbot.boa import (
    calculate_subsectores_boa,
    cancel_job,
    extract_company_rows_from_xlsx,
    extract_first_companies_from_xlsx,
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


@router.post("/calculate-subsectores-boa/upload", response_model=SubsectorBoaResponse)
async def start_subsectores_boa_upload(file: UploadFile = File(...)):
    """
    Modo de recálculo dirigido: lee el XLSX completo y procesa TODAS las empresas.
    Antes solo procesaba 185 filas configuradas; ahora procesa el archivo completo
    y guarda resultados en la base de datos desde el inicio.
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó ningún archivo.")

    ext = (file.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in {"xlsx", "xls"}:
        raise HTTPException(status_code=400, detail="Solo se permiten archivos Excel (.xlsx, .xls)")

    content = await file.read()
    try:
        company_rows = extract_company_rows_from_xlsx(content)
        tickers_to_process = [
            str(row["ticker"]).strip().upper()
            for row in company_rows
            if row.get("ticker")
        ]
        logger.info(
            "[BOA][UPLOAD] Total de empresas en Excel: %s, a procesar: %s",
            len(company_rows),
            len(tickers_to_process),
        )
        # Merge aditivo en main_template_complements subsectores (preserva histórico, fija mojibake)
        try:
            from collections import defaultdict
            from app.db.database import SessionLocal
            from app.models.main import TemplateComplement
            import datetime
            def _fix(s):
                if not isinstance(s, str) or not s: return s
                s = s.replace("AgencAPP","Agencias").replace("TerapAPP","Terapias").replace("memorAPP","memorias")
                if "Ã" in s or "Â" in s:
                    try: return s.encode("latin1").decode("utf-8")
                    except: pass
                return s
            groups: dict[tuple[str,str], dict] = {}
            for r in company_rows:
                sec = _fix((r.get("sector") or "").strip())
                sub = _fix((r.get("subsector") or "").strip())
                tic = (r.get("ticker") or "").strip().upper()
                if not sub or not tic: continue
                key = (sec.lower(), sub.lower())
                if key not in groups:
                    groups[key] = {"sector": sec, "subsector": sub, "empresas": []}
                if tic not in groups[key]["empresas"]:
                    groups[key]["empresas"].append(tic)
            new_items = list(groups.values())
            # merge con existente
            db = SessionLocal()
            try:
                old = db.query(TemplateComplement).filter(TemplateComplement.nombre=="subsectores", TemplateComplement.deleted_at.is_(None)).order_by(TemplateComplement.created_at.desc()).first()
                if old and isinstance(old.data, list):
                    merged: dict[tuple[str,str], dict] = {}
                    for it in old.data:
                        s = _fix((it.get("sector") or "").strip())
                        ss = _fix((it.get("subsector") or "").strip())
                        if s and ss:
                            it["sector"]=s; it["subsector"]=ss
                            merged[(s.lower(), ss.lower())] = dict(it)
                    for it in new_items:
                        k=(it["sector"].lower(), it["subsector"].lower())
                        if k in merged:
                            ex=merged[k]
                            ex["empresas"]=list(dict.fromkeys([*(e.strip() for e in (ex.get("empresas") or []) if e), *(e.strip() for e in (it.get("empresas") or []) if e)]))
                        else:
                            merged[k]=it
                    new_items=list(merged.values())
                    old.deleted_at=datetime.datetime.utcnow()
                    db.commit()
                db.add(TemplateComplement(nombre="subsectores", fecha=datetime.datetime.utcnow(), data=new_items))
                db.commit()
                logger.info(f"[BOA][UPLOAD] Subsectores mergeado: {len(new_items)} grupos")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[BOA][UPLOAD] Merge subsectores no crítico: {e}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el Excel: {exc}") from exc

    if not tickers_to_process:
        return SubsectorBoaResponse(
            success=True,
            valid_companies=[],
            errors=[],
            total=0,
            processed=0,
            failed=0,
            job_id=None,
            message="El archivo Excel no contiene empresas con ticker válido.",
        )

    job_id = create_job(len(tickers_to_process))

    def _run():
        try:
            calculate_subsectores_boa(
                tickers_to_process,
                job_id=job_id,
                batch_size=50,       # lote mayor para procesar más rápido
                max_companies=None,  # Sin límite máximo - todas las empresas
                save_to_db=True,     # Guardar en BD desde el inicio
                emit_ticker_logs=False,
            )
        except Exception as exc:
            fail_job(job_id, str(exc))
            logger.exception(f"Error en background BOA job {job_id}")

    threading.Thread(target=_run, daemon=True).start()

    return SubsectorBoaResponse(
        success=True,
        valid_companies=[],
        errors=[],
        total=len(tickers_to_process),
        processed=0,
        failed=0,
        complete_count=0,
        incomplete_count=0,
        complete_tickers=[],
        incomplete_tickers=[],
        empty_batch_tickers=[],
        job_id=job_id,
        message=f"Procesando {len(tickers_to_process)} empresas del archivo Excel en segundo plano. " +
                "Los resultados se guardarán en la base de datos automáticamente. " +
                "Use el indicador flotante para seguir el progreso.",
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
