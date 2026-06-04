# app/api/main/reports/router.py

import asyncio
import logging
import os
import tempfile
from typing import Optional
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.main.calculations.router import get_default_or_latest_master_template
from app.db.database import get_db
from app.models.main import Calculation, CalculationType, Cover, Report, TemplateCode
from app.models.templates import MasterTemplate
from app.services.onedrive.service import get_onedrive_service
from app.services.query_service import apply_filters

logger = logging.getLogger(__name__)
from app.api.main.covers.router import _cover_to_dict
from app.api.main.master_templates import router as master_templates_router
from app.schemas.main import ReportUpdate

from .utils import _sanitize_text

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
                    "value": None,
                }
            else:
                try:
                    c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                except Exception:
                    c_dict = dict(c)
                entry = {
                    "id": c_dict.get("id", -1),
                    "nombre": c_dict.get("nombre")
                    or c_dict.get("original_name")
                    or c_dict.get("filename")
                    or c_dict.get("code"),
                    "code": c_dict.get("code"),
                    "type": t,
                    "hoja": c_dict.get("hoja"),
                    "value": c_dict.get("value"),
                }

            img_url = image_map.get(entry.get("code"))
            if img_url:
                entry["template_code_image_url"] = img_url

            result.append(entry)
        return result

    # `get_template_codes` returns keys: template_id, template_name, codes, statistics
    codes_block = (
        codes_payload.get("codes", {}) if isinstance(codes_payload, dict) else {}
    )

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
        type=CalculationType(data.type)
        if getattr(data, "type", None)
        else CalculationType.KAPITAL,
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info(f"_report_to_response(report): {_report_to_response(report)}")
    response = _report_to_response(report)
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
    request: Request,
    report_id: int,
    calculation_id: int,
    background_tasks: BackgroundTasks,
    is_preview: bool = True,
    db: Session = Depends(get_db),
):
    report = db.get(Report, report_id)
    calculation = db.get(Calculation, calculation_id)
    if not report or not calculation:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")

    browser = request.app.state.browser
    if not browser:
        raise HTTPException(status_code=500, detail="Browser instance not available")

    onedrive_service = get_onedrive_service()
    html_content = report.contentEditor or ""

    session_id = (
        calculation.data.get("active_session_id")
        if isinstance(calculation.data, dict)
        else None
    )
    item_id = report.template.onedrive_item_id

    template_codes = (
        db.execute(
            select(TemplateCode)
            .join(TemplateCode.master_templates)
            .where(MasterTemplate.id == report.template_id)
        )
        .scalars()
        .all()
    )

    def _is_image_code(code_obj: TemplateCode) -> bool:
        return (
            code_obj.template_code_image_id is not None
            or code_obj.template_code_image is not None
        )

    def _normalise_code(raw_code: str) -> str:
        return f"$${str(raw_code).replace('$$', '').upper()}$$"

    # 1. Separar códigos encontrados en el HTML (Textos vs Gráficos)
    text_codes = []
    image_codes = []

    for code_obj in template_codes:
        normalized_code = _normalise_code(code_obj.code)

        if normalized_code not in html_content:
            continue

        if _is_image_code(code_obj):
            image_codes.append((normalized_code, code_obj))
        else:
            text_codes.append((normalized_code, code_obj))

    # 2. PROCESAMIENTO DE GRÁFICOS
    for normalized_code, code_obj in image_codes:
        if not code_obj.hoja or not code_obj.nombre:
            html_content = html_content.replace(
                normalized_code,
                f"<p><em>[Configuración incompleta: {normalized_code}]</em></p>",
            )
            continue

        try:
            base64_chart = await onedrive_service.get_excel_chart_image(
                item_id=item_id,
                sheet_name=code_obj.hoja,
                chart_name=code_obj.nombre,
                session_id=session_id,
            )
            if base64_chart:
                img_tag = f'<img src="data:image/png;base64,{base64_chart}" style="max-width: 100%; height: auto; display: block; margin: 0 auto;" />'
                html_content = html_content.replace(normalized_code, img_tag)
            else:
                html_content = html_content.replace(
                    normalized_code,
                    f"<p><em>[Gráfico vacio: {code_obj.nombre}]</em></p>",
                )
        except Exception as e:
            logger.error(f"Error procesando grafico {normalized_code}: {e}")
            html_content = html_content.replace(
                normalized_code, f"<p><em>[Fallo al cargar: {code_obj.nombre}]</em></p>"
            )

    # 3. PROCESAMIENTO DE TEXTOS EN BATCH
    if text_codes:
        read_requests = []
        mapping = {}  # req_id -> (normalized_code, code_obj)
        req_id = 1
        user_email = onedrive_service.config.user_email

        # Armar el payload de peticiones para Graph API
        for normalized_code, code_obj in text_codes:
            if not code_obj.hoja or not code_obj.coordinate:
                html_content = html_content.replace(
                    normalized_code,
                    f"<p><em>[Configuración incompleta: {normalized_code}]</em></p>",
                )
                continue

            mapping[str(req_id)] = (normalized_code, code_obj)

            # URL relativa requerida por Microsoft Graph para $batch
            url = f"/users/{user_email}/drive/items/{item_id}/workbook/worksheets('{quote(code_obj.hoja)}')/range(address='{quote(code_obj.coordinate)}')"

            read_requests.append(
                {
                    "id": str(req_id),
                    "method": "GET",
                    "url": url,
                    "headers": {"workbook-session-id": session_id}
                    if session_id
                    else {},
                }
            )
            req_id += 1

        # Ejecutar peticiones en lotes de 20 simultáneamente
        if read_requests:
            chunks = [
                read_requests[i : i + 20] for i in range(0, len(read_requests), 20)
            ]
            batch_tasks = [onedrive_service.execute_batch(chunk) for chunk in chunks]
            batch_results = await asyncio.gather(*batch_tasks)

            # Reemplazar resultados en el HTML
            for chunk_responses in batch_results:
                for resp in chunk_responses:
                    request_id = resp.get("id")
                    if not request_id or request_id not in mapping:
                        continue

                    norm_code, c_obj = mapping[request_id]
                    rendered_value = None

                    if resp.get("status") == 200:
                        body = resp.get("body", {})
                        text_block = body.get("text")
                        values_block = body.get("values")

                        # Prioriza texto renderizado (text), fallback a crudo (values)
                        if (
                            isinstance(text_block, list)
                            and text_block
                            and isinstance(text_block[0], list)
                            and text_block[0]
                        ):
                            rendered_value = text_block[0][0]
                        elif (
                            isinstance(values_block, list)
                            and values_block
                            and isinstance(values_block[0], list)
                            and values_block[0]
                        ):
                            rendered_value = values_block[0][0]

                    if rendered_value is None or str(rendered_value).strip() == "":
                        html_content = html_content.replace(
                            norm_code, f"<p><em>[Sin valor: {c_obj.nombre}]</em></p>"
                        )
                    else:
                        html_content = html_content.replace(
                            norm_code, str(rendered_value)
                        )

    html_content = _sanitize_text(html_content)
    html_content = html_content.replace("<code>", "<b>").replace("</code>", "</b>")

    # Formato de portada
    cover_html = ""
    if report.portada and report.portada.portada and report.portada.portada.url:
        cover_url = report.portada.portada.url
        cover_html = f"""
        <div class="cover-container">
            <img src="{cover_url}" class="cover-image" />
        </div>
        """

    # Ensamblado HTML
    full_html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{ margin: 0; }}
            body {{
                font-family: Helvetica, Arial, sans-serif;
                font-size: 12px; color: #000; margin: 0; padding: 0; background-color: #fff;
            }}
            .cover-container {{ width: 100vw; height: 100vh; page-break-after: always; }}
            .cover-image {{ width: 100%; height: 100%; object-fit: cover; }}
            .content-container {{ padding: 20mm; box-sizing: border-box; }}
            p {{ text-align: justify; }}
        </style>
    </head>
    <body>
        {cover_html}
        <div class="content-container">
            {html_content}
        </div>
    </body>
    </html>
    """

    # Generacion de PDF
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    context = await browser.new_context()
    page = await context.new_page()
    try:
        await page.set_content(full_html, wait_until="networkidle")
        await page.pdf(path=temp_path, format="A4", print_background=True)
    finally:
        await page.close()
        await context.close()

    # Procesamiento de preview
    if is_preview:
        reader = PdfReader(temp_path)
        if len(reader.pages) > 2:
            writer = PdfWriter()
            writer.add_page(reader.pages[0])
            writer.add_page(reader.pages[1])
            with open(temp_path, "wb") as f:
                writer.write(f)

    background_tasks.add_task(delete_temp_file, temp_path)

    return FileResponse(
        temp_path,
        media_type="application/pdf",
        filename=f"Reporte-{report.nombre}.pdf",
        headers={"Content-Disposition": "inline"},
    )
