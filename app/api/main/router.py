# app/api/main/router.py
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response
import json
from fastapi.encoders import jsonable_encoder
logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, or_
from typing import List, Optional
from datetime import datetime
from ...db.database import get_db
from ...models.main import (
    Template,
    TemplateComplement,
    Calculation,
    TemplateCode,
    Report,
    Cover,
    CalculationType,
)
from ...services.query_service import apply_filters
from ...models.cms import Media
from ...services.aws_service import s3_service
from ...schemas.main import (
    ReportUpdate, TemplateCreate, TemplateUpdate, TemplateResponse,
    TemplateComplementCreate, TemplateComplementUpdate, TemplateComplementResponse,
    CalculationCreate, CalculationUpdate, CalculationResponse,
)
from app.models.templates.master_templates import MasterTemplate


router = APIRouter(prefix="/main", tags=["Main"])


@router.get("/health")
def main_health():
    return {"status": "ok"}


# ==================== TEMPLATES ====================
@router.get("/templates", response_model=List[TemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    result = db.execute(
        select(Template).where(Template.deleted_at.is_(None))
    )
    templates = result.scalars().all()
    return [_template_to_response(t) for t in templates]


@router.get("/templates/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_response(template)


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    template = Template(
        nombre=payload.nombre,
        template_file_id=payload.template_file_id,
        is_default=payload.is_default,
    )
    if payload.template_code_ids:
        template.template_codes = _get_template_codes(db, payload.template_code_ids)
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = payload.model_dump(exclude_unset=True)
    template_code_ids = update_data.pop("template_code_ids", None)

    for key, value in update_data.items():
        setattr(template, key, value)

    if template_code_ids is not None:
        template.template_codes = _get_template_codes(db, template_code_ids)

    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    template.deleted_at = datetime.utcnow()
    db.commit()
    return None

# ==================== TEMPLATE COMPLEMENTS ====================
@router.get("/template-complements", response_model=List[TemplateComplementResponse])
def list_template_complements(db: Session = Depends(get_db)):
    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()
    return [TemplateComplementResponse.model_validate(complement)] if complement else []

@router.get("/template-complements/{complement_id}", response_model=TemplateComplementResponse)
def get_template_complement_by_id(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    return TemplateComplementResponse.model_validate(complement)


@router.get("/template-complements/by-name/{complement_name}", response_model=List[TemplateComplementResponse])
def get_template_complement(complement_name: str, db: Session = Depends(get_db)):
    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.nombre == complement_name)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()
    return [TemplateComplementResponse.model_validate(complement)] if complement else []


@router.post(
    "/template-complements",
    response_model=TemplateComplementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_complement(payload: TemplateComplementCreate, db: Session = Depends(get_db)):
    """
    Creates a new complement. Soft-deletes any existing complement with the same nombre
    so that only one active record per nombre exists at a time.
    """
    # Soft-delete all previous records with the same nombre
    old_records = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.nombre == payload.nombre)
        .where(TemplateComplement.deleted_at.is_(None))
    ).scalars().all()

    for old in old_records:
        old.deleted_at = datetime.utcnow()

    complement = TemplateComplement(**payload.model_dump())
    db.add(complement)
    db.commit()
    db.refresh(complement)
    return TemplateComplementResponse.model_validate(complement)


@router.put("/template-complements/{complement_id}", response_model=TemplateComplementResponse)
def update_template_complement(
    complement_id: int, payload: TemplateComplementUpdate, db: Session = Depends(get_db)
):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(complement, key, value)
    db.commit()
    db.refresh(complement)
    return TemplateComplementResponse.model_validate(complement)


@router.delete("/template-complements/{complement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_complement(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    complement.deleted_at = datetime.utcnow()
    db.commit()
    return None


# ==================== CALCULATIONS ====================
@router.get("/calculations", response_model=List[CalculationResponse])
def list_calculations(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Calculation)
    if user_id:
        query = query.where(Calculation.user_id == user_id)
    result = db.execute(query)
    calculations = result.scalars().all()
    return [CalculationResponse.model_validate(c) for c in calculations]


@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)


@router.post("/calculations", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
def create_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):
    calculation = Calculation(**payload.model_dump())
    db.add(calculation)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.put("/calculations/{calculation_id}", response_model=CalculationResponse)
def update_calculation(calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(calculation, key, value)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(calculation)
    db.commit()
    return None


# ==================== REPORTS ====================

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
        joinedload(Report.template).joinedload(Template.template_codes),
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
    Obtiene la plantilla maestra más reciente (no borrada) y devuelve sus códigos
    reusando la lógica de `get_template_codes`.
    """
    obj = db.execute(
        select(MasterTemplate)
        .where(MasterTemplate.deleted_at.is_(None))
        .order_by(MasterTemplate.created_at.desc())
    ).scalars().first()

    if not obj:
        raise HTTPException(status_code=404, detail="No master template found")

    from . import master_templates_router

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

    # Try to pick a default template for new reports
    template = db.execute(
        select(Template).where(Template.deleted_at.is_(None), Template.is_default.is_(True))
    ).scalars().first()
    if not template:
        template = db.execute(select(Template).where(Template.deleted_at.is_(None))).scalars().first()
    if not template:
        raise HTTPException(status_code=400, detail="No template available to assign to the report")

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


# ==================== COVERS ====================

@router.get("/covers")
def list_covers(db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    covers = result.unique().scalars().all()
    return [_cover_to_dict(c) for c in covers]


@router.get("/covers/{cover_id}")
def get_cover(cover_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.id == cover_id, Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    cover = result.unique().scalar_one_or_none()
    if not cover:
        raise HTTPException(status_code=404, detail="Cover not found")
    return _cover_to_dict(cover)


def _create_media_from_upload(db: Session, file: UploadFile) -> Optional[int]:
    if not file or not file.filename:
        return None
        
    try:
        s3_result = s3_service.upload_file(file, folder="covers")
    except Exception as e:
        # Si falla AWS S3, lanzamos un 400 para que el frontend lo pueda mostrar
        # y no cause un 500 que rompe los headers CORS.
        raise HTTPException(status_code=400, detail=f"Error subiendo archivo a AWS S3: {str(e)}")
    
    media = Media(
        filename=s3_result["object_key"].split("/")[-1],
        original_name=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        url=s3_result["file_url"],
        storage_path=s3_result["object_key"],
        folder="/covers"
    )
    db.add(media)
    db.flush()  # Para obtener el ID generado
    return media.id


@router.post("/covers", status_code=status.HTTP_201_CREATED)
def create_cover(
    nombre: str = Form(...),
    tipo: str = Form(...),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),
    
    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),
    
    db: Session = Depends(get_db)
):
    # Subir nuevos archivos a S3 y crear los Media correspondientes si existen
    if portada and portada.filename:
        portada_id = _create_media_from_upload(db, portada)
    if primer_imagen_footer and primer_imagen_footer.filename:
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)
    if segundo_imagen_footer and segundo_imagen_footer.filename:
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)
    if logo_superior and logo_superior.filename:
        logo_superior_id = _create_media_from_upload(db, logo_superior)
    if imagen_central and imagen_central.filename:
        imagen_central_id = _create_media_from_upload(db, imagen_central)
    if logo_inferior and logo_inferior.filename:
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)
    if imagen_fondo and imagen_fondo.filename:
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    cover = Cover(
        nombre=nombre,
        tipo=tipo,
        portada_id=portada_id,
        primer_imagen_footer_id=primer_imagen_footer_id,
        segundo_imagen_footer_id=segundo_imagen_footer_id,
        logo_superior_id=logo_superior_id,
        imagen_central_id=imagen_central_id,
        logo_inferior_id=logo_inferior_id,
        imagen_fondo_id=imagen_fondo_id,
    )
    db.add(cover)
    db.commit()
    db.refresh(cover)
    return get_cover(cover.id, db)


@router.put("/covers/{cover_id}")
def update_cover(
    cover_id: int,
    nombre: Optional[str] = Form(None),
    tipo: Optional[str] = Form(None),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),

    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),

    db: Session = Depends(get_db),
):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")

    now = datetime.utcnow()

    # Si vienen nuevos archivos, intentar eliminar los antiguos en S3
    # y marcar los Media existentes como borrados (soft-delete) antes de subir
    if portada and portada.filename:
        existing = getattr(cover, "portada")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.portada_id = None
        portada_id = _create_media_from_upload(db, portada)

    if primer_imagen_footer and primer_imagen_footer.filename:
        existing = getattr(cover, "primer_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.primer_imagen_footer_id = None
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)

    if segundo_imagen_footer and segundo_imagen_footer.filename:
        existing = getattr(cover, "segundo_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.segundo_imagen_footer_id = None
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)

    if logo_superior and logo_superior.filename:
        existing = getattr(cover, "logo_superior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_superior_id = None
        logo_superior_id = _create_media_from_upload(db, logo_superior)

    if imagen_central and imagen_central.filename:
        existing = getattr(cover, "imagen_central")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_central_id = None
        imagen_central_id = _create_media_from_upload(db, imagen_central)

    if logo_inferior and logo_inferior.filename:
        existing = getattr(cover, "logo_inferior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_inferior_id = None
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)

    if imagen_fondo and imagen_fondo.filename:
        existing = getattr(cover, "imagen_fondo")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_fondo_id = None
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    # Actualizar campos si se proporcionaron
    if nombre is not None:
        cover.nombre = nombre
    if tipo is not None:
        cover.tipo = tipo

    # Asociar nuevos media ids si fueron proporcionados
    if portada_id is not None:
        cover.portada_id = portada_id
    if primer_imagen_footer_id is not None:
        cover.primer_imagen_footer_id = primer_imagen_footer_id
    if segundo_imagen_footer_id is not None:
        cover.segundo_imagen_footer_id = segundo_imagen_footer_id
    if logo_superior_id is not None:
        cover.logo_superior_id = logo_superior_id
    if imagen_central_id is not None:
        cover.imagen_central_id = imagen_central_id
    if logo_inferior_id is not None:
        cover.logo_inferior_id = logo_inferior_id
    if imagen_fondo_id is not None:
        cover.imagen_fondo_id = imagen_fondo_id

    db.commit()
    db.refresh(cover)
    return get_cover(cover_id, db)


@router.delete("/covers/{cover_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cover(cover_id: int, db: Session = Depends(get_db)):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")
    now = datetime.utcnow()

    # Campos de Media relacionados con la cover
    media_fields = [
        "portada",
        "primer_imagen_footer",
        "segundo_imagen_footer",
        "logo_superior",
        "imagen_central",
        "logo_inferior",
        "imagen_fondo",
    ]

    # Intentar eliminar objetos en S3 y marcar los Media como borrados (soft-delete)
    for field in media_fields:
        media = getattr(cover, field)
        if media:
            try:
                # storage_path contiene el object key
                s3_service.delete_file(media.storage_path)
            except Exception:
                # No interrumpimos si falla la eliminación en S3; marcamos el media como borrado de todos modos
                pass

            media.deleted_at = now
            db.add(media)
            # Desasociar la media de la cover
            setattr(cover, f"{field}_id", None)

    cover.deleted_at = now
    db.commit()
    return None


# ==================== HELPER FUNCTIONS ====================

def _get_template_codes(db: Session, template_code_ids: List[int]):
    if not template_code_ids:
        return []
    result = db.execute(
        select(TemplateCode).where(TemplateCode.id.in_(template_code_ids))
    )
    return list(result.scalars().all())


def _template_to_response(template: Template) -> TemplateResponse:
    return TemplateResponse(
        id=template.id,
        nombre=template.nombre,
        template_file_id=template.template_file_id,
        is_default=template.is_default,
        template_code_ids=[code.id for code in template.template_codes],
        created_at=template.created_at,
        updated_at=template.updated_at,
        deleted_at=template.deleted_at,
    )

def _media_to_dict(media: Media | None) -> dict | None:
    if not media:
        return None
    return {
        "id": media.id,
        "url": media.url,
        "filename": media.filename,
        "original_name": media.original_name,
        "mime_type": media.mime_type,
        "alt_text": media.alt_text,
    }


def _cover_to_dict(cover: Cover | None) -> dict | None:
    if not cover:
        return None
    return {
        "id": cover.id,
        "nombre": cover.nombre,
        "tipo": cover.tipo.value,
        "portada": _media_to_dict(cover.portada),
        "primer_imagen_footer": _media_to_dict(cover.primer_imagen_footer),
        "segundo_imagen_footer": _media_to_dict(cover.segundo_imagen_footer),
        "logo_superior": _media_to_dict(cover.logo_superior),
        "imagen_central": _media_to_dict(cover.imagen_central),
        "logo_inferior": _media_to_dict(cover.logo_inferior),
        "imagen_fondo": _media_to_dict(cover.imagen_fondo),
    }


def _report_to_response(report: Report) -> dict:
    template = report.template
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
        # `template` removed from response to avoid sending template metadata
        # (previously included template id, nombre, is_default and template_codes)
        "portada": _cover_to_dict(report.portada),
    }
