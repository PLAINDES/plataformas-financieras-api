# app/api/main/reports/router.py

import os
import logging
from typing import Optional
from fastapi.responses import FileResponse
import tempfile
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from app.db.database import get_db
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.encoders import jsonable_encoder
from app.services.query_service import apply_filters
from app.models.main import (
    Report,
    Cover,
    CalculationType,
    Calculation
)
from .utils import _sanitize_text, flatten_dict
from app.api.main.calculations.router import get_default_or_latest_master_template
logger = logging.getLogger(__name__)
from app.schemas.main import (
    ReportUpdate
)
from app.api.main.router import _cover_to_dict
from app.api.main.master_templates import router as master_templates_router

router = APIRouter(prefix="/main", tags=["Main"])

# Función para borrar el archivo temporal
def delete_temp_file(path: str):
    if os.path.exists(path):
        os.remove(path)
        print(f"Archivo temporal eliminado: {path}")

def _report_to_response(report: Report) -> dict:
    def _iso(v):
        try:
            return v.isoformat() if v is not None and hasattr(v, "isoformat") else v
        except Exception:
            return str(v)
    return {
        "id": report.id,
        "nombre": report.nombre,
        "file": report.file,
        "precio": float(report.precio) if report.precio is not None else None,
        "moneda": report.moneda,
        "sector_empresa": report.sector_empresa,
        "bono_ajustado": report.bono_ajustado,
        "link_pago": report.link_pago,
        "contenido": report.contenido,
        "contentEditor": report.contentEditor,
        "activo": report.activo,
        "created_at": _iso(report.created_at),
        "updated_at": _iso(report.updated_at),
        "portada": _cover_to_dict(report.portada),
    }


@router.get("/reports")
def list_reports(
    limit: Optional[int] = None,
    page: Optional[int] = None,
    search: Optional[str] = None,
    type: Optional[str] = None,
    activo: Optional[bool] = 1,
    db: Session = Depends(get_db),
):
    base_query = select(Report)

    eager = [
        joinedload(Report.portada).joinedload(Cover.portada),
        joinedload(Report.portada).joinedload(Cover.primer_imagen_footer),
        joinedload(Report.portada).joinedload(Cover.segundo_imagen_footer),
        joinedload(Report.portada).joinedload(Cover.logo_superior),
        joinedload(Report.portada).joinedload(Cover.imagen_central),
        joinedload(Report.portada).joinedload(Cover.logo_inferior),
        joinedload(Report.portada).joinedload(Cover.imagen_fondo),
    ]

    params = {
        "limit": limit,
        "page": page,
        "search": search,
        "type": type,
        "activo": activo,
    }

    query = apply_filters(
        base_query,
        Report,
        params,
        search_fields=["nombre", "contenido", "sector_empresa"],
        enum_fields={"type": CalculationType},
        eager_loads=eager,
    )

    # order newest first
    query = query.order_by(Report.created_at.desc(), Report.id.desc())

    result = db.execute(query)
    reports = result.unique().scalars().all()
    return [_report_to_response(r) for r in reports]


@router.get("/reports/get-current-codes")
async def get_current_codes(db: Session = Depends(get_db)):
    """
    Obtiene la plantilla maestra por defecto (si existe), y si no, usa
    la más reciente no borrada. Devuelve sus códigos reusando la lógica
    de `get_template_codes`.
    """
    obj = get_default_or_latest_master_template(db)

    if not obj:
        raise HTTPException(status_code=404, detail="No master template found")

    # Get template codes (async) and chart images (sync) from the master templates router
    codes_payload = await master_templates_router.get_template_codes(obj.id, db)
    images_payload = master_templates_router.get_template_chart_images(obj.id, db)

    # Build a map code -> image url (codes are returned as strings like $$CODE$$)
    image_map = {}
    for t in ("valora", "kapital"):
        for img in images_payload.get(t, []):
            code = img.get("code")
            if code:
                image_map[code] = img.get("url")

    # Attach image url to each template code if available
    def attach_urls(codes_list, t):
        # Return a minimal object for each code with only the fields the frontend expects
        result = []
        for c in codes_list:
            # c may be a Pydantic model or dict or a plain string
            if not c:
                continue
            if isinstance(c, str):
                code_val = c
                entry = {
                    "id": -1,
                    "nombre": c,
                    "code": code_val,
                    "type": t,
                    "hoja": None,
                    "value": None
                }
            else:
                try:
                    c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                except Exception:
                    c_dict = dict(c)
                entry = {
                    "id": c_dict.get("id", -1),
                    "nombre": c_dict.get("nombre") or c_dict.get("original_name") or c_dict.get("filename") or c_dict.get("code"),
                    "code": c_dict.get("code"),
                    "type": t,
                    "hoja": c_dict.get("hoja"),
                    "value": c_dict.get("value")
                }

            img_url = image_map.get(entry.get("code"))
            if img_url:
                entry["template_code_image_url"] = img_url

            result.append(entry)
        return result

    # `get_template_codes` returns keys: template_id, template_name, codes, statistics
    codes_block = codes_payload.get("codes", {}) if isinstance(codes_payload, dict) else {}

    return {
        "template_id": codes_payload.get("template_id"),
        "template_name": codes_payload.get("template_name"),
        "extracted_codes": {
            "valora": attach_urls(codes_block.get("valora", []), "valora"),
            "kapital": attach_urls(codes_block.get("kapital", []), "kapital"),
        },
        "extracted_chart_codes": None,
        "extracted_chart_images": images_payload,
        "chart_extraction_stats": None,
        "statistics": codes_payload.get("statistics"),
        "processed_sheets": None,
    }


@router.get("/reports/get-default-template-codes")
async def get_default_template_codes(db: Session = Depends(get_db)):
    """Alias explícito para obtener los códigos de la plantilla maestra por defecto."""
    return await get_current_codes(db)

@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Report)
        .where(Report.id == report_id, Report.deleted_at.is_(None))
        .options(
            joinedload(Report.portada).joinedload(Cover.portada),
            joinedload(Report.portada).joinedload(Cover.primer_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.segundo_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.logo_superior),
            joinedload(Report.portada).joinedload(Cover.imagen_central),
            joinedload(Report.portada).joinedload(Cover.logo_inferior),
            joinedload(Report.portada).joinedload(Cover.imagen_fondo),
        )
    )
    report = result.unique().scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_response(report)


@router.post("/reports")
def create_report(data: ReportUpdate, db: Session = Depends(get_db)):
    # Require at least a nombre for creation
    if not data.nombre:
        raise HTTPException(status_code=400, detail="Field 'nombre' is required")

    # Try to pick a default master template for new reports
    template = get_default_or_latest_master_template(db)
    if not template:
        raise HTTPException(
            status_code=400,
            detail="No master template available to assign to the report",
        )

    report = Report(
        template_id=template.id,
        nombre=data.nombre,
        precio=data.precio,
        moneda=data.moneda or "SOLES",
        sector_empresa=data.sector_empresa,
        bono_ajustado=data.bono_ajustado,
        link_pago=data.link_pago,
        contenido=data.contenido,
        contentEditor=data.contentEditor,
        portada_id=data.portada_id,
        activo=data.activo if data.activo is not None else True,
        type=CalculationType(data.type) if getattr(data, "type", None) else CalculationType.KAPITAL,
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info(f"_report_to_response(report): {_report_to_response(report)}")
    response =_report_to_response(report)
    return jsonable_encoder(response)


@router.put("/reports/{report_id}")
def update_report(report_id: int, data: ReportUpdate, db: Session = Depends(get_db)):

    result = db.execute(
        select(Report)
        .where(Report.id == report_id, Report.deleted_at.is_(None))
        .options(joinedload(Report.portada))
    )
    report = result.unique().scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    update_dict = data.model_dump(exclude_unset=True, exclude={"cover_data"})

    for key, value in update_dict.items():
        if key == "type" and value is not None:
            try:
                setattr(report, key, CalculationType(value))
            except Exception:
                setattr(report, key, value)
        else:
            setattr(report, key, value)

    if data.cover_data and report.portada:
        cover_dict = data.cover_data.model_dump(exclude_unset=True)
        for key, value in cover_dict.items():
            setattr(report.portada, key, value)

    try:
        db.commit()
        db.refresh(report)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al actualizar: {str(e)}")

    return _report_to_response(report)


STORAGE_DIR = os.path.join(os.path.dirname(__file__), "../../files")

@router.post("/reports/{report_id}/upload", status_code=status.HTTP_200_OK)
async def upload_report_file(
    report_id: int,
    file: UploadFile = File(...),
    html: str = Form(...),
    db: Session = Depends(get_db),
):
    report = db.get(Report, report_id)
    if not report or report.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Report not found")

    print("STORAGE_DIR:", STORAGE_DIR)
    print("STORAGE_DIR absoluto:", os.path.abspath(STORAGE_DIR))
    print("__file__:", __file__)

    os.makedirs(STORAGE_DIR, exist_ok=True)

    filename = f"Reporte-{report_id}.pdf"
    pdf_path = os.path.join(STORAGE_DIR, filename)

    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    html_path = os.path.join(STORAGE_DIR, f"Reporte-{report_id}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    report.file = filename
    # persist editor content to the DB as well
    try:
        report.contentEditor = html
    except Exception:
        pass
    db.commit()
    return {"message": "Archivo guardado", "file": filename}


@router.get("/reports/{report_id}/content")
def get_report_content(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report or report.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Report not found")

    html_path = os.path.join(STORAGE_DIR, f"Reporte-{report_id}.html")
    if not os.path.exists(html_path):
        return {"html": ""}

    with open(html_path, "r", encoding="utf-8") as f:
        return {"html": f.read()}

@router.get("/reports/{report_id}/generate", response_class=FileResponse)
async def generate_report_pdf(
    report_id: int,
    calculation_id: int,
    background_tasks: BackgroundTasks,
    is_preview: bool = True, # Parámetro para limitar las páginas
    db: Session = Depends(get_db)
):
    report = db.get(Report, report_id)
    calculation = db.get(Calculation, calculation_id)
    if not report or not calculation:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")

    flat_data = flatten_dict(calculation.data)

    html_content = report.contentEditor or ""
    for key, value in flat_data.items():
        placeholder = f"$${key}$$"
        html_content = html_content.replace(placeholder, str(value) if value is not None else "")

    html_content = _sanitize_text(html_content)
    html_content = html_content.replace("<code>", "<b>").replace("</code>", "</b>")

    pdf = FPDF()

    if report.portada and report.portada.portada and report.portada.portada.url:
        pdf.add_page()
        try:
            pdf.image(report.portada.portada.url, x=0, y=0, w=pdf.w, h=pdf.h)
        except Exception:
            pass

    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    try:
        pdf.write_html(html_content)
    except Exception as e:
        pdf.multi_cell(0, 10, txt=f"Error renderizando contenido: {str(e)}")

    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    pdf.output(temp_path)

    # Lógica de limitación de páginas
    if is_preview:
        reader = PdfReader(temp_path)
        if len(reader.pages) > 2:
            writer = PdfWriter()
            writer.add_page(reader.pages[0])
            writer.add_page(reader.pages[1])

            # Sobrescribir el archivo temporal con la versión de 2 páginas
            with open(temp_path, "wb") as f:
                writer.write(f)

    background_tasks.add_task(delete_temp_file, temp_path)

    return FileResponse(
        temp_path, 
        media_type="application/pdf", 
        filename=f"Reporte-{report.nombre}.pdf",
        headers={"Content-Disposition": "inline"}
    )
